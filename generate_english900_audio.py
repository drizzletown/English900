#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据“新时代英语900句_纯文本900行.txt”批量生成跟读音频：
每个条目按“英文读三遍 -> 中文读一遍”的顺序合成。

输入行示例：
01-001. Hi. —— 嗨。

默认输出：
- output_audio/scene_01.mp3 ... scene_09.mp3  每 100 句一个音频
- output_audio/新时代英语900句_跟读完整版.mp3    合并后的完整音频

依赖：
    pip install edge-tts
系统依赖：
    ffmpeg 需要可在命令行直接调用
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None


DEFAULT_EN_VOICE = "en-US-JennyNeural"
DEFAULT_ZH_VOICE = "zh-CN-XiaoxiaoNeural"


@dataclass(frozen=True)
class SentenceItem:
    index: int
    raw_no: str
    scene: int
    english: str
    chinese: str


def remove_leading_number(text: str) -> Tuple[str, str]:
    """去掉开头编号，返回 raw_no 与剩余文本。"""
    text = text.strip().lstrip("\ufeff").strip()
    patterns = [
        r"^(?P<no>\d{1,2}-\d{1,3})[\.、．]\s*(?P<body>.+)$",
        r"^(?P<no>\d{1,4})[\.、．]\s*(?P<body>.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return m.group("no"), m.group("body").strip()
    return "", text


def split_en_zh(body: str) -> Tuple[str, str]:
    """兼容多种分隔符，拆成英文和中文。"""
    separators = [" —— ", "——", " — ", "—", " || ", "||", "\t", " - "]
    for sep in separators:
        if sep in body:
            left, right = body.split(sep, 1)
            return left.strip(), right.strip()
    raise ValueError(f"无法拆分英文/中文，请检查这一行：{body}")


def infer_scene(raw_no: str, index: int, split_every: int) -> int:
    """优先从 01-001 的前缀推断场景，否则按每 split_every 句分组。"""
    m = re.match(r"^(\d{1,2})-\d{1,3}$", raw_no)
    if m:
        return int(m.group(1))
    return (index - 1) // split_every + 1


def load_items(input_file: Path, split_every: int = 100) -> List[SentenceItem]:
    if not input_file.exists():
        raise FileNotFoundError(f"找不到输入文件：{input_file}")

    lines = input_file.read_text(encoding="utf-8").splitlines()
    items: List[SentenceItem] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        raw_no, body = remove_leading_number(line)
        english, chinese = split_en_zh(body)
        index = len(items) + 1
        scene = infer_scene(raw_no, index, split_every)
        if not english or not chinese:
            raise ValueError(f"第 {line_no} 行英文或中文为空：{line}")
        items.append(SentenceItem(index=index, raw_no=raw_no, scene=scene, english=english, chinese=chinese))
    return items


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "未找到 ffmpeg。请先安装 ffmpeg，并确保在命令行执行 ffmpeg -version 能看到版本信息。"
        )



def run(cmd: Sequence[str]) -> None:
    """
    执行外部命令。

    Windows 中文系统默认编码通常是 GBK，而 ffmpeg 日志里可能包含
    UTF-8 或其他不可被 GBK 解码的字节。这里显式使用 UTF-8，并设置
    errors="replace"，避免在日志解码阶段抛 UnicodeDecodeError。
    """
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        if p.stdout:
            print(p.stdout)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise RuntimeError("命令执行失败：" + " ".join(cmd))




def make_silence_mp3(path: Path, seconds: float) -> None:
    """生成静音片段。"""
    if path.exists() and path.stat().st_size > 1024:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=24000:cl=mono",
        "-t", str(seconds),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        str(path),
    ])


async def synthesize_one(
    text: str,
    voice: str,
    output_file: Path,
    rate: str,
    pitch: str,
    volume: str,
    retries: int = 3,
) -> None:
    """调用 edge-tts 合成单个片段，失败自动重试。"""
    if output_file.exists() and output_file.stat().st_size > 1024:
        return
    output_file.parent.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            assert edge_tts is not None
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                pitch=pitch,
                volume=volume,
            )
            await communicate.save(str(output_file))
            if output_file.exists() and output_file.stat().st_size > 1024:
                return
            raise RuntimeError(f"生成文件为空：{output_file}")
        except Exception as exc:  # pragma: no cover
            last_error = exc
            await asyncio.sleep(1.5 * attempt)

    raise RuntimeError(f"TTS 失败：{text} -> {output_file}\n原因：{last_error}")


async def synthesize_all(
    items: Sequence[SentenceItem],
    temp_dir: Path,
    en_voice: str,
    zh_voice: str,
    en_rate: str,
    zh_rate: str,
    en_pitch: str,
    zh_pitch: str,
    volume: str,
    concurrency: int,
) -> None:
    """并发合成英文与中文片段。"""
    if edge_tts is None:
        raise RuntimeError("未安装 edge-tts。请先执行：pip install edge-tts")

    sem = asyncio.Semaphore(concurrency)

    async def guarded(text: str, voice: str, path: Path, rate: str, pitch: str) -> None:
        async with sem:
            await synthesize_one(text, voice, path, rate=rate, pitch=pitch, volume=volume)

    tasks = []
    total = len(items) * 2
    done = 0

    async def one_task(text: str, voice: str, path: Path, rate: str, pitch: str) -> None:
        nonlocal done
        await guarded(text, voice, path, rate, pitch)
        done += 1
        if done % 50 == 0 or done == total:
            print(f"[TTS] 已完成 {done}/{total} 个语音片段")

    for item in items:
        tasks.append(one_task(
            item.english,
            en_voice,
            temp_dir / f"en_{item.index:04d}.mp3",
            en_rate,
            en_pitch,
        ))
        tasks.append(one_task(
            item.chinese,
            zh_voice,
            temp_dir / f"zh_{item.index:04d}.mp3",
            zh_rate,
            zh_pitch,
        ))

    await asyncio.gather(*tasks)


def write_concat_manifest(files: Iterable[Path], manifest: Path) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for f in files:
        # ffmpeg concat demuxer：单引号内部的单引号需转义
        escaped = str(f.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_audio(files: Sequence[Path], output_file: Path, work_dir: Path) -> None:
    """用 ffmpeg concat demuxer 合并并重新编码，兼容不同 TTS 声音参数。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    manifest = work_dir / f"concat_{output_file.stem}.txt"
    write_concat_manifest(files, manifest)
    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(manifest),
        "-ar", "24000",
        "-ac", "1",
        "-b:a", "64k",
        str(output_file),
    ])


def build_sequence_for_items(
    items: Sequence[SentenceItem],
    temp_dir: Path,
    short_pause: Path,
    mid_pause: Path,
    long_pause: Path,
    repeat: int,
) -> List[Path]:
    """构造音频播放顺序：英文 repeat 遍 -> 中文 1 遍。"""
    seq: List[Path] = []
    for item in items:
        en = temp_dir / f"en_{item.index:04d}.mp3"
        zh = temp_dir / f"zh_{item.index:04d}.mp3"
        for k in range(repeat):
            seq.append(en)
            if k != repeat - 1:
                seq.append(short_pause)
        seq.append(mid_pause)
        seq.append(zh)
        seq.append(long_pause)
    return seq


def group_by_scene(items: Sequence[SentenceItem]) -> List[Tuple[int, List[SentenceItem]]]:
    scenes = sorted({item.scene for item in items})
    return [(scene, [item for item in items if item.scene == scene]) for scene in scenes]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成新时代英语900句跟读音频：英文读三遍，然后中文读一遍。"
    )
    parser.add_argument(
        "--input",
        default="新时代英语900句_纯文本900行.txt",
        help="输入文本文件路径，默认：新时代英语900句_纯文本900行.txt",
    )
    parser.add_argument(
        "--output-dir",
        default="output_audio",
        help="输出目录，默认：output_audio",
    )
    parser.add_argument("--repeat", type=int, default=3, help="英文重复遍数，默认 3")
    parser.add_argument("--split-every", type=int, default=100, help="无编号时每多少句分一组，默认 100")
    parser.add_argument("--en-voice", default=DEFAULT_EN_VOICE, help=f"英文声音，默认 {DEFAULT_EN_VOICE}")
    parser.add_argument("--zh-voice", default=DEFAULT_ZH_VOICE, help=f"中文声音，默认 {DEFAULT_ZH_VOICE}")
    parser.add_argument("--en-rate", default="-5%", help="英文语速，默认 -5%%")
    parser.add_argument("--zh-rate", default="+0%", help="中文语速，默认 +0%%")
    parser.add_argument("--en-pitch", default="+0Hz", help="英文音高，默认 +0Hz")
    parser.add_argument("--zh-pitch", default="+0Hz", help="中文音高，默认 +0Hz")
    parser.add_argument("--volume", default="+0%", help="音量，默认 +0%%")
    parser.add_argument("--concurrency", type=int, default=2, help="TTS 并发数，默认 2，过高可能触发限流")
    parser.add_argument("--short-pause", type=float, default=0.65, help="英文重复之间停顿秒数，默认 0.65")
    parser.add_argument("--mid-pause", type=float, default=0.90, help="英文三遍后到中文之间停顿秒数，默认 0.90")
    parser.add_argument("--long-pause", type=float, default=1.20, help="每句结束后的停顿秒数，默认 1.20")
    parser.add_argument("--start", type=int, default=None, help="只生成从第几句开始，便于测试")
    parser.add_argument("--end", type=int, default=None, help="只生成到第几句结束，便于测试")
    parser.add_argument("--no-full", action="store_true", help="只生成分场景音频，不合并完整版")
    parser.add_argument("--dry-run", action="store_true", help="只检查解析结果，不生成音频")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = Path(args.input)
    output_dir = Path(args.output_dir)
    temp_dir = output_dir / "_clips"
    work_dir = output_dir / "_work"

    items = load_items(input_file, split_every=args.split_every)
    if args.start is not None or args.end is not None:
        start = args.start or 1
        end = args.end or len(items)
        items = [item for item in items if start <= item.index <= end]

    print(f"[INFO] 读取句子数：{len(items)}")
    if items:
        print(f"[INFO] 第一句：{items[0].english} —— {items[0].chinese}")
        print(f"[INFO] 最后一句：{items[-1].english} —— {items[-1].chinese}")

    if args.dry_run:
        print("[INFO] dry-run 完成：解析正常，未生成音频。")
        return

    check_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    short_pause = work_dir / f"silence_short_{args.short_pause:.2f}.mp3"
    mid_pause = work_dir / f"silence_mid_{args.mid_pause:.2f}.mp3"
    long_pause = work_dir / f"silence_long_{args.long_pause:.2f}.mp3"
    make_silence_mp3(short_pause, args.short_pause)
    make_silence_mp3(mid_pause, args.mid_pause)
    make_silence_mp3(long_pause, args.long_pause)

    asyncio.run(synthesize_all(
        items=items,
        temp_dir=temp_dir,
        en_voice=args.en_voice,
        zh_voice=args.zh_voice,
        en_rate=args.en_rate,
        zh_rate=args.zh_rate,
        en_pitch=args.en_pitch,
        zh_pitch=args.zh_pitch,
        volume=args.volume,
        concurrency=args.concurrency,
    ))

    scene_outputs: List[Path] = []
    for scene, scene_items in group_by_scene(items):
        seq = build_sequence_for_items(
            scene_items,
            temp_dir=temp_dir,
            short_pause=short_pause,
            mid_pause=mid_pause,
            long_pause=long_pause,
            repeat=args.repeat,
        )
        scene_file = output_dir / f"scene_{scene:02d}.mp3"
        print(f"[MERGE] 生成 {scene_file}，句子数：{len(scene_items)}")
        concat_audio(seq, scene_file, work_dir)
        scene_outputs.append(scene_file)

    if not args.no_full and scene_outputs:
        full_file = output_dir / "新时代英语900句_跟读完整版.mp3"
        print(f"[MERGE] 合并完整版：{full_file}")
        concat_audio(scene_outputs, full_file, work_dir)

    print("[DONE] 全部完成。")
    print(f"[DONE] 输出目录：{output_dir.resolve()}")


if __name__ == "__main__":
    main()
