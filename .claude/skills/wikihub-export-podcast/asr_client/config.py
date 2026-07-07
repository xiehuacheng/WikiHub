"""ASR 客户端配置。

所有配置均通过环境变量读取，避免在代码中硬编码密钥。
"""

import os


class ConfigError(RuntimeError):
    """配置缺失或无效。"""

    pass


_REQUIRED_ENVS = [
    "DASHSCOPE_API_KEY",
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


def get_dashscope_api_key() -> str:
    return _get_required("DASHSCOPE_API_KEY")


def get_oss_credentials() -> tuple:
    """返回 (access_key_id, access_key_secret, bucket, endpoint)。"""
    return (
        _get_required("OSS_ACCESS_KEY_ID"),
        _get_required("OSS_ACCESS_KEY_SECRET"),
        _get_required("OSS_BUCKET"),
        _get_required("OSS_ENDPOINT"),
    )


def get_oss_url_expiration() -> int:
    """签名 URL 有效期，默认 3600 秒。"""
    try:
        return int(os.environ.get("OSS_URL_EXPIRATION", "3600"))
    except ValueError:
        return 3600


def get_transcription_timeout_seconds() -> int:
    """FunASR 任务整体超时，默认 3600 秒。"""
    try:
        return int(os.environ.get("TRANSCRIPTION_TIMEOUT_SECONDS", "3600"))
    except ValueError:
        return 3600


def should_cleanup_oss() -> bool:
    """转录完成后是否删除 OSS 临时对象，默认 True。"""
    return os.environ.get("ASR_CLEANUP_OSS", "1").strip() not in ("0", "false", "False", "FALSE", "no")


def validate() -> None:
    """校验所有必需配置是否存在。"""
    for name in _REQUIRED_ENVS:
        _get_required(name)
