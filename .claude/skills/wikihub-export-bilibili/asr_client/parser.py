"""解析 FunASR 返回的 JSON 结果，提取纯文本。"""


class ParseError(RuntimeError):
    """结果解析失败。"""

    pass


def parse_result(data: dict) -> str:
    """从 FunASR transcription JSON 中提取完整文本。

    优先使用 transcripts[0].text；如果不存在，则拼接 sentences[].text。
    """
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
