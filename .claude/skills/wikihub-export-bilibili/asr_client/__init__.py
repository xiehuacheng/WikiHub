"""阿里云 FunASR + OSS 中转的统一 ASR 客户端。

用法：
    from asr_client import transcribe_audio
    text = transcribe_audio("/path/to/audio.mp3", language="zh")

需要配置环境变量：
    DASHSCOPE_API_KEY
    OSS_ACCESS_KEY_ID
    OSS_ACCESS_KEY_SECRET
    OSS_BUCKET
    OSS_ENDPOINT
"""

from .config import ConfigError
from .funasr_client import TranscriptionError
from .oss_uploader import UploadError
from .parser import ParseError


class ASRError(RuntimeError):
    """ASR 统一异常基类。"""

    pass


def transcribe_audio(audio_path: str, language: str = "auto") -> str:
    """转录音频文件，返回识别文本。

    流程：
        1. 上传音频到 OSS 获得签名 URL
        2. 提交 FunASR 异步任务并等待完成
        3. 解析识别结果
        4. 清理 OSS 临时对象（默认启用）

    Args:
        audio_path: 本地音频文件路径。
        language: 识别语言提示，"auto" 表示自动检测。

    Returns:
        识别出的文本字符串。

    Raises:
        ASRError: 配置缺失、上传失败、识别失败或解析失败。
    """
    from . import config, funasr_client, oss_uploader, parser

    config.validate()
    object_key = None
    try:
        object_key, signed_url = oss_uploader.upload_audio(audio_path)
        raw_result = funasr_client.submit_and_wait(
            signed_url,
            language=language,
            timeout=config.get_transcription_timeout_seconds(),
        )
        return parser.parse_result(raw_result)
    except (ConfigError, UploadError, TranscriptionError, ParseError) as e:
        raise ASRError(str(e)) from e
    finally:
        if object_key and config.should_cleanup_oss():
            oss_uploader.delete_object(object_key)


__all__ = [
    "transcribe_audio",
    "ASRError",
    "ConfigError",
    "UploadError",
    "TranscriptionError",
    "ParseError",
]
