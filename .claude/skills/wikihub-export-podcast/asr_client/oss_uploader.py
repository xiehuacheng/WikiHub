"""阿里云 OSS 音频上传与临时 URL 生成。

音频上传到 bucket 的 `wikihub-asr/YYYY/MM/DD/{uuid}.{ext}` 路径下，
生成带签名的公网 URL 供 FunASR 下载识别，识别完成后可选择删除。
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import oss2

from .config import get_oss_credentials, get_oss_url_expiration, ConfigError


class UploadError(RuntimeError):
    """OSS 上传失败。"""

    pass


def _object_key_for(audio_path: str) -> str:
    """生成 OSS 对象路径：wikihub-asr/YYYY/MM/DD/{uuid}.{ext}"""
    now = datetime.now(timezone.utc)
    ext = Path(audio_path).suffix.lower() or ".bin"
    if ext not in (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg", ".mp4", ".bin"):
        ext = ".bin"
    return f"wikihub-asr/{now:%Y/%m/%d}/{uuid.uuid4().hex}{ext}"


def _sign_url(bucket, object_key: str, expiration: int) -> str:
    """生成签名 URL。"""
    return bucket.sign_url("GET", object_key, expiration, slash_safe=True)


def upload_audio(audio_path: str) -> tuple:
    """上传音频到 OSS，返回 (object_key, signed_url)。

    Raises:
        ConfigError: OSS 配置缺失。
        UploadError: 上传失败。
    """
    if not os.path.isfile(audio_path):
        raise UploadError(f"音频文件不存在：{audio_path}")

    access_key_id, access_key_secret, bucket_name, endpoint = get_oss_credentials()
    object_key = _object_key_for(audio_path)
    expiration = get_oss_url_expiration()

    try:
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.put_object_from_file(object_key, audio_path)
        signed_url = _sign_url(bucket, object_key, expiration)
    except oss2.exceptions.ClientError as e:
        raise UploadError(f"OSS 客户端错误：{e}") from e
    except Exception as e:
        raise UploadError(f"OSS 上传失败：{e}") from e

    return object_key, signed_url


def delete_object(object_key: str) -> None:
    """删除 OSS 对象。失败时不抛出异常，仅打印警告。"""
    try:
        access_key_id, access_key_secret, bucket_name, endpoint = get_oss_credentials()
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.delete_object(object_key)
    except Exception as e:
        print(f"[warn] 删除 OSS 对象 {object_key} 失败：{e}", file=__import__("sys").stderr)
