#!/usr/bin/env python3
"""
B 站视频转录 JSON 输出包装器。

用法：
    python transcribe_one_json.py BV1bt421L7t1

输出到 stdout：
    {"title": "...", "uploader": "...", "text": "..."}
"""

import json
import sys

from transcribe_one import extract_bvid, transcribe_bvid


def main():
    if len(sys.argv) < 2:
        print("用法：python transcribe_one_json.py <BV号或链接>", file=sys.stderr)
        sys.exit(1)

    bvid = extract_bvid(sys.argv[1])

    # 转录过程中可能向 stdout 打印日志，污染 JSON 输出。
    # 临时把 stdout 重定向到 stderr，恢复后再输出纯净的 JSON。
    original_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        title, uploader, text = transcribe_bvid(bvid)
    finally:
        sys.stdout = original_stdout

    print(json.dumps({
        "title": title,
        "uploader": uploader,
        "text": text,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
