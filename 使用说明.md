# 新时代英语900句语音生成程序使用说明

## 功能

读取 `新时代英语900句_纯文本900行.txt`，自动解析每一行的英文和中文，生成跟读音频：

> 英文读 3 遍 → 中文读 1 遍 → 进入下一句

默认每 100 句输出一个分场景 MP3，并额外生成一个完整 MP3。

## 文件

- `generate_english900_audio.py`：主程序
- `requirements_audio.txt`：Python 依赖
- `新时代英语900句_纯文本900行.txt`：输入数据文件

## 安装依赖

```bash
python -m pip install -r requirements_audio.txt
```

还需要安装 `ffmpeg`，并确保命令行可以执行：

```bash
ffmpeg -version
```

Windows 可用：

```bash
winget install Gyan.FFmpeg
```

## 快速测试

先只生成前 5 句，确认声音、语速、停顿是否合适：

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt --start 1 --end 5
```

## 生成完整 900 句音频

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt
```

默认输出目录：

```text
output_audio/
├─ scene_01.mp3
├─ scene_02.mp3
├─ ...
├─ scene_09.mp3
└─ 新时代英语900句_跟读完整版.mp3
```

## 常用参数

### 只生成分场景音频，不合并完整版

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt --no-full
```

### 改成英式英语声音

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt --en-voice en-GB-SoniaNeural
```

### 放慢英文语速

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt --en-rate -15%
```

### 调整停顿

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt --short-pause 0.8 --mid-pause 1.0 --long-pause 1.5
```

### 调整并发数

```bash
python generate_english900_audio.py --input 新时代英语900句_纯文本900行.txt --concurrency 2
```

并发数不建议过高，否则在线 TTS 可能限流。

## 解析规则

程序兼容如下行格式：

```text
01-001. Hi. —— 嗨。
Hi. —— 嗨。
Hi. — 嗨。
Hi. || 嗨。
Hi. - 嗨。
```

如果原文件含 `01-001.` 这类编号，程序会自动去掉编号，并按 `01` 到 `09` 输出 9 个场景音频。
