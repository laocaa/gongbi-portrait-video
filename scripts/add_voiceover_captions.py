#!/usr/bin/env python3
"""Add a Douyin-style voiceover + word-synced one-line captions to any video.

Usage:
  python3 add_voiceover_captions.py --video <in.mp4> --lines-file <lines.json>
      --out <out.mp4> --assemble
      [--title "标题(可空则不显示)"] [--voice zh-CN-YunyangNeural] [--rate +6%]
      [--max-chars 18] [--font /path/to/cjk.ttc]

lines.json: {"title": "...", "lines": ["line1", ...]}

Captions:
  - Each sentence is split into short one-line chunks (<= --max-chars chars)
    at punctuation, so every caption is a single clean line (no wrapping).
  - Each chunk is shown exactly while the narrator speaks it (word-timestamp
    based), i.e. 口播说到哪，字幕跟到哪.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
]


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def find_font() -> str:
    import glob
    for c in FONT_CANDIDATES:
        if Path(c).exists():
            return c
    for c in glob.glob("/usr/share/fonts/**/*.tt[fc]", recursive=True):
        if "CJK" in c or "Noto" in c or "ukai" in c or "uming" in c:
            return c
    sys.exit("no CJK font found")


async def gen_line(out: Path, text: str, voice: str, rate: str) -> list[tuple[float, float, str]]:
    """Synthesize one line; return [(start_s, end_s, word), ...] from word boundaries."""
    c = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words: list[tuple[float, float, str]] = []
    with open(out, "wb") as f:
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                o = chunk["offset"] / 1e7
                d = chunk["duration"] / 1e7
                words.append((o, o + d, chunk["text"]))
    return words


def split_chunks(text: str, max_chars: int) -> list[str]:
    """Split a sentence into one-line chunks at punctuation (<= max_chars)."""
    pieces = [p for p in re.split(r"(?<=[，。！？、；：])", text) if p]
    chunks: list[str] = []
    cur = ""
    for p in pieces:
        if len(cur) + len(p) <= max_chars:
            cur += p
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text]


def make_caption_png(out: Path, text: str, width: int, font_path: str) -> None:
    """Single clean line, font auto-sized to fit, centered paper box."""
    max_w = int(width * 0.92)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    size = 54
    font = ImageFont.truetype(font_path, size)
    while size > 22 and probe.textlength(text, font=font) > max_w:
        size -= 2
        font = ImageFont.truetype(font_path, size)
    tw = probe.textlength(text, font=font)
    pad_x, pad_y = int(size * 0.55), int(size * 0.38)
    box_w = int(tw) + pad_x * 2
    box_h = int(size * 1.45) + pad_y * 2
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=int(size * 0.3),
                        fill=(253, 250, 242, 212), outline=(43, 38, 32, 95), width=2)
    d.text((pad_x, pad_y), text, font=font, fill=(43, 38, 32, 255))
    img.save(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--lines-file", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="zh-CN-YunyangNeural")
    ap.add_argument("--rate", default="+6%")
    ap.add_argument("--gap", type=float, default=0.45)
    ap.add_argument("--max-chars", type=int, default=18)
    ap.add_argument("--font", default=None)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--assemble", action="store_true")
    args = ap.parse_args()

    video = Path(args.video)
    data = json.loads(Path(args.lines_file).read_text(encoding="utf-8"))
    lines: list[str] = data["lines"]
    title = args.title if args.title is not None else data.get("title", "")
    work = Path(args.workdir) if args.workdir else video.parent / "vo-captions"
    work.mkdir(parents=True, exist_ok=True)
    font_path = args.font or find_font()
    print("font:", font_path)

    # 1) TTS per line + exact word timings
    clips: list[tuple[float, Path]] = []
    words_by_line: list[list[tuple[float, float, str]]] = []
    for i, text in enumerate(lines):
        mp3 = work / f"line-{i:02d}.mp3"
        wf = work / f"line-{i:02d}-words.json"
        if mp3.exists() and wf.exists():
            words = [tuple(x) for x in json.loads(wf.read_text(encoding="utf-8"))]
        else:
            words = asyncio.run(gen_line(mp3, text, args.voice, args.rate))
            wf.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        words_by_line.append(words)
        d = ffprobe_duration(mp3)
        clips.append((d, mp3))
        print(f"line {i}: mp3={d:.2f}s {text[:16]}...")

    # 2) global audio offsets + per-line speech windows
    starts: list[float] = []
    speech_wins: list[tuple[float, float]] = []
    t = 0.6
    for i, (d, _) in enumerate(clips):
        starts.append(t)
        w0, w1 = (words_by_line[i][0][0], words_by_line[i][-1][1]) if words_by_line[i] else (0.0, d)
        speech_wins.append((t + w0, t + w1))
        t += d + args.gap
    total_narration = t - args.gap

    # 3) split lines into one-line chunks; chunk window = proportional slice of speech window
    chunks: list[tuple[str, float, float]] = []
    for i, text in enumerate(lines):
        sw0, sw1 = speech_wins[i]
        subs = split_chunks(text, args.max_chars)
        total_chars = sum(len(s) for s in subs)
        pos = 0.0
        for s in subs:
            w0 = sw0 + (pos / max(1, total_chars)) * (sw1 - sw0)
            pos += len(s)
            w1 = sw0 + (pos / max(1, total_chars)) * (sw1 - sw0)
            chunks.append((s, w0, w1))
    print(f"chunks: {len(chunks)}")
    for c in chunks:
        print(f"  {c[1]:.2f}-{c[2]:.2f}s  {c[0]}")

    # 4) narration audio (concat with gaps)
    concat = work / "concat.txt"
    for name, dur in [("silence-0.6.wav", 0.6), ("silence-0.45.wav", args.gap)]:
        f = work / name
        if not f.exists():
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                            f"anullsrc=r=24000:cl=mono", "-t", str(dur), str(f)],
                           capture_output=True, check=True)
    parts = [f"file '{work / 'silence-0.6.wav'}'"]
    for d, mp3 in clips:
        parts.append(f"file '{mp3}'")
        parts.append(f"file '{work / 'silence-0.45.wav'}'")
    concat.write_text("\n".join(parts), encoding="utf-8")
    audio_full = work / "narration.wav"
    if not audio_full.exists():
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-c", "pcm_s16le", str(audio_full)], check=True)

    # 5) caption PNGs (one per chunk)
    cap_pngs: list[Path] = []
    for i, (text, _, _) in enumerate(chunks):
        png = work / f"cap-{i:02d}.png"
        make_caption_png(png, text, 1080, font_path)
        cap_pngs.append(png)
    title_png = work / "title.png"
    if title:
        make_caption_png(title_png, title, 1080, font_path)

    vid_dur = ffprobe_duration(video)
    print(f"video duration {vid_dur:.2f}s, narration ends {total_narration:.2f}s")

    if not args.assemble:
        print("done prep; rerun with --assemble")
        return

    # 6) assemble: frame-by-frame composite (low memory, robust with many chunks)
    import cv2 as _cv2

    cap = _cv2.VideoCapture(str(video))
    fps = cap.get(_cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
    cap_imgs = [Image.open(p).convert("RGBA") for p in cap_pngs]
    title_img = Image.open(title_png).convert("RGBA") if title else None

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", f"{fps:.3f}",
         "-i", "-", "-i", str(audio_full),
         "-filter_complex",
         "[1:a]aresample=48000,apad,atrim=0:%.2f,afade=t=out:st=%.2f:d=3[a]" % (vid_dur, max(0, vid_dur - 3)),
         "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-crf", "19", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(args.out)],
        stdin=subprocess.PIPE,
    )
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        img = Image.fromarray(_cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB)).convert("RGBA")
        if title_img is not None and 0.3 <= t <= 45.5:
            ta = 1.0
            if t < 0.7:
                ta = max(0.0, (t - 0.3) / 0.4)
            if t > 44.0:
                ta = max(0.0, (45.5 - t) / 1.5)
            if ta > 0:
                ti = title_img
                if ta < 1.0:
                    a = ti.split()[3].point(lambda v: int(v * ta))
                    ti = ti.copy()
                    ti.putalpha(a)
                img.alpha_composite(ti, ((W - ti.width) // 2, 80))
        for ci, (_, w0, w1) in enumerate(chunks):
            if w0 - 0.1 <= t <= w1 + 0.05:
                cimg = cap_imgs[ci]
                alpha = 1.0
                if t < w0 + 0.12:
                    alpha = max(0.0, (t - (w0 - 0.1)) / 0.12)
                if t > w1 - 0.15:
                    alpha = max(0.0, (w1 + 0.05 - t) / 0.15)
                if alpha <= 0:
                    continue
                if alpha < 1.0:
                    a = cimg.split()[3].point(lambda v: int(v * alpha))
                    cimg = cimg.copy()
                    cimg.putalpha(a)
                x = (W - cimg.width) // 2
                y = H - 220 - cimg.height
                img.alpha_composite(cimg, (x, y))
        proc.stdin.write(img.convert("RGB").tobytes())
        idx += 1
        if idx % 300 == 0:
            print(f"  composite {idx}/{int(vid_dur*fps)} frames")
    cap.release()
    proc.stdin.close()
    ret = proc.wait()
    if ret != 0:
        raise SystemExit(f"ffmpeg failed: {ret}")
    print("DONE ->", args.out)


if __name__ == "__main__":
    main()
