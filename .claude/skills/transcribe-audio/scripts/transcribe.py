#!/usr/bin/env python3
"""通用音频转录 CLI。

通过阿里云 DashScope FunASR 将音频文件或公开音频 URL 转录为纯文本。
本地文件会先上传至 OSS 生成签名 URL，再提交给 FunASR；URL 则直接提交。

环境变量（可写在 .env 文件中）：
    DASHSCOPE_API_KEY        必填
    OSS_ACCESS_KEY_ID        本地文件转录时必填
    OSS_ACCESS_KEY_SECRET    本地文件转录时必填
    OSS_BUCKET               本地文件转录时必填
    OSS_ENDPOINT             本地文件转录时必填

可选环境变量：
    OSS_URL_EXPIRATION       签名 URL 有效期（秒），默认 3600
    TRANSCRIPTION_TIMEOUT_SECONDS   转录等待超时（秒），默认 3600
    ASR_CLEANUP_OSS          转录后是否删除 OSS 临时对象，默认 1
"""

import argparse
import json
import os
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """简单加载 .env 文件；环境变量优先于文件中的值。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # .env 文件不存在或无法读取时静默忽略
        pass


class ConfigError(RuntimeError):
    """配置缺失或无效。"""

    pass


class UploadError(RuntimeError):
    """OSS 上传失败。"""

    pass


class TranscriptionError(RuntimeError):
    """FunASR 识别失败。"""

    pass


class ParseError(RuntimeError):
    """结果解析失败。"""

    pass


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_OSS_REQUIRED_ENVS = [
    "OSS_ACCESS_KEY_ID",
    "OSS_ACCESS_KEY_SECRET",
    "OSS_BUCKET",
    "OSS_ENDPOINT",
]


def _get_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"缺少必需的环境变量：{name}")
    return value


def _get_dashscope_api_key() -> str:
    return _get_required("DASHSCOPE_API_KEY")


def _get_oss_credentials() -> tuple:
    """返回 (access_key_id, access_key_secret, bucket, endpoint)。"""
    return (
        _get_required("OSS_ACCESS_KEY_ID"),
        _get_required("OSS_ACCESS_KEY_SECRET"),
        _get_required("OSS_BUCKET"),
        _get_required("OSS_ENDPOINT"),
    )


def _get_oss_url_expiration() -> int:
    try:
        return int(os.environ.get("OSS_URL_EXPIRATION", "3600"))
    except ValueError:
        return 3600


def _get_transcription_timeout_seconds() -> int:
    try:
        return int(os.environ.get("TRANSCRIPTION_TIMEOUT_SECONDS", "3600"))
    except ValueError:
        return 3600


def _should_cleanup_oss() -> bool:
    return os.environ.get("ASR_CLEANUP_OSS", "1").strip() not in (
        "0",
        "false",
        "False",
        "FALSE",
        "no",
    )


# ---------------------------------------------------------------------------
# OSS 上传
# ---------------------------------------------------------------------------

def _object_key_for(audio_path: str) -> str:
    now = datetime.now(timezone.utc)
    ext = Path(audio_path).suffix.lower() or ".bin"
    if ext not in (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg", ".mp4", ".bin"):
        ext = ".bin"
    return f"transcribe-audio/{now:%Y/%m/%d}/{uuid.uuid4().hex}{ext}"


def _upload_audio(audio_path: str) -> tuple:
    """上传音频到 OSS，返回 (object_key, signed_url)。"""
    import oss2

    if not os.path.isfile(audio_path):
        raise UploadError(f"音频文件不存在：{audio_path}")

    access_key_id, access_key_secret, bucket_name, endpoint = _get_oss_credentials()
    object_key = _object_key_for(audio_path)
    expiration = _get_oss_url_expiration()

    try:
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.put_object_from_file(object_key, audio_path)
        signed_url = bucket.sign_url("GET", object_key, expiration, slash_safe=True)
    except oss2.exceptions.ClientError as e:
        raise UploadError(f"OSS 客户端错误：{e}") from e
    except Exception as e:
        raise UploadError(f"OSS 上传失败：{e}") from e

    return object_key, signed_url


def _delete_object(object_key: str) -> None:
    """删除 OSS 对象；失败时仅打印警告到 stderr。"""
    import oss2

    try:
        access_key_id, access_key_secret, bucket_name, endpoint = _get_oss_credentials()
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.delete_object(object_key)
    except Exception as e:
        print(f"[warn] 删除 OSS 对象 {object_key} 失败：{e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# FunASR 调用
# ---------------------------------------------------------------------------

def _submit_and_wait(audio_url: str, language: str = "auto", timeout: int = 3600) -> dict:
    import dashscope
    from dashscope.audio.asr import Transcription

    dashscope.api_key = _get_dashscope_api_key()

    kwargs = {
        "model": "fun-asr",
        "file_urls": [audio_url],
    }
    if language and language != "auto":
        kwargs["language_hints"] = [language]

    try:
        task_response = Transcription.async_call(**kwargs)
    except Exception as e:
        raise TranscriptionError(f"提交 FunASR 任务失败：{e}") from e

    try:
        result_response = Transcription.wait(
            task=task_response.output.task_id,
            timeout=timeout or _get_transcription_timeout_seconds(),
        )
    except Exception as e:
        raise TranscriptionError(f"等待 FunASR 结果失败：{e}") from e

    status = getattr(result_response.output, "task_status", None)
    if status != "SUCCEEDED":
        raise TranscriptionError(f"FunASR 任务未成功，状态：{status}")

    results = getattr(result_response.output, "results", [])
    if not results:
        raise TranscriptionError("FunASR 返回结果为空")

    transcription_url = results[0].get("transcription_url")
    if not transcription_url:
        raise TranscriptionError("FunASR 返回结果中缺少 transcription_url")

    try:
        with urllib.request.urlopen(transcription_url, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise TranscriptionError(f"下载识别结果失败：{e}") from e

    return data


# ---------------------------------------------------------------------------
# 结果解析
# ---------------------------------------------------------------------------

def _parse_result(data: dict) -> str:
    if not isinstance(data, dict):
        raise ParseError(f"识别结果不是字典：{type(data)}")

    transcripts = data.get("transcripts")
    if not isinstance(transcripts, list) or not transcripts:
        raise ParseError("识别结果中缺少 transcripts 数组")

    transcript = transcripts[0]
    if not isinstance(transcript, dict):
        raise ParseError("transcripts[0] 不是字典")

    text = transcript.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    sentences = transcript.get("sentences")
    if isinstance(sentences, list):
        parts = []
        for sentence in sentences:
            if isinstance(sentence, dict):
                part = sentence.get("text", "")
                if isinstance(part, str) and part.strip():
                    parts.append(part.strip())
        if parts:
            return "\n".join(parts)

    raise ParseError("无法从识别结果中提取文本")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def transcribe(input_value: str, language: str = "auto") -> str:
    """转录本地音频文件或公开音频 URL，返回纯文本。"""
    object_key = None
    try:
        if _is_url(input_value):
            audio_url = input_value
        else:
            object_key, audio_url = _upload_audio(input_value)

        raw_result = _submit_and_wait(
            audio_url,
            language=language,
            timeout=_get_transcription_timeout_seconds(),
        )
        return _parse_result(raw_result)
    finally:
        if object_key and _should_cleanup_oss():
            _delete_object(object_key)


def main() -> int:
    parser = argparse.ArgumentParser(description="通用音频转录工具")
    parser.add_argument("--input", required=True, help="本地音频文件路径或公开音频 URL")
    parser.add_argument("--language", default="auto", help="语言提示，默认 auto")
    args = parser.parse_args()

    _load_dotenv(".env")

    try:
        text = transcribe(args.input, language=args.language)
    except (ConfigError, UploadError, TranscriptionError, ParseError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
