# transcribe-audio

通用音频转录工具 skill。可被任意工作流复用，不依赖 WikiHub 特定文件或状态。

## 功能

- 输入为本地音频文件时，自动上传至阿里云 OSS 生成签名 URL，再提交给 DashScope FunASR 进行转录；转录完成后默认清理 OSS 临时对象。
- 输入为公开音频 URL 时，直接提交给 FunASR 转录。
- stdout 输出纯文本转录结果，失败时 stderr 输出错误并返回非零退出码。

## 前置条件

1. Python 3.8+
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 配置以下环境变量，或在运行目录放置 `.env` 文件：
   - `DASHSCOPE_API_KEY`：阿里云 DashScope API Key（始终必填）
   - `OSS_ACCESS_KEY_ID`：阿里云 OSS AccessKeyId（本地文件必填）
   - `OSS_ACCESS_KEY_SECRET`：阿里云 OSS AccessKeySecret（本地文件必填）
   - `OSS_BUCKET`：OSS Bucket 名称（本地文件必填）
   - `OSS_ENDPOINT`：OSS Endpoint（本地文件必填）

可选环境变量：

- `OSS_URL_EXPIRATION`：签名 URL 有效期（秒），默认 `3600`
- `TRANSCRIPTION_TIMEOUT_SECONDS`：转录任务最大等待时间（秒），默认 `3600`
- `ASR_CLEANUP_OSS`：转录后是否删除 OSS 临时对象，默认 `1`（设为 `0` / `false` / `no` 可禁用）

## CLI 用法

```bash
python3 scripts/transcribe.py --input PATH_OR_URL [--language auto]
```

示例：

```bash
# 转录本地文件
python3 scripts/transcribe.py --input ./episode.m4a --language zh

# 转录公开 URL
python3 scripts/transcribe.py --input https://example.com/audio.mp3
```

## 输出格式

### 成功

stdout 仅输出纯文本转录结果：

```
大家好，欢迎收听本期播客...
```

### 失败

stderr 输出错误信息，程序返回非零退出码：

```
[error] 缺少必需的环境变量：DASHSCOPE_API_KEY
```

## 注意事项

- 本 skill 只做音频上传/转录，不读取或写入 WikiHub 的 `wikihub-exported.json`、`*-export-config.json`、pending 文件等。
- 输入 URL 必须是 FunASR 可公网访问的音频地址。
- `.env` 文件中的配置仅在对应环境变量未设置时生效，环境变量优先级更高。
