"""DashScope FunASR 异步任务调用。

提交音频 URL 进行识别，同步等待结果并返回原始 JSON 字典。
"""

import json
import sys
import urllib.request

import dashscope
from dashscope.audio.asr import Transcription

from .config import get_dashscope_api_key, get_transcription_timeout_seconds


class TranscriptionError(RuntimeError):
    """FunASR 识别失败。"""

    pass


def submit_and_wait(audio_url: str, language: str = "auto", timeout: int = 3600) -> dict:
    """提交 FunASR 异步任务并等待完成，返回 transcription_url 指向的 JSON 字典。

    Args:
        audio_url: 公网可访问的音频 URL。
        language: 识别语言提示，"auto" 表示自动检测。
        timeout: 最大等待时间（秒）。

    Raises:
        TranscriptionError: 任务提交失败、执行失败或超时。
    """
    dashscope.api_key = get_dashscope_api_key()

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
            timeout=timeout or get_transcription_timeout_seconds(),
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
