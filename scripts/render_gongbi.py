#!/usr/bin/env python3
"""Render a gongbi portrait MP4: brush reveals fine ink strokes on rice paper.

Usage:
  render_gongbi.py --paths <paths.json> --features <features.json> --base <base.png>
                   --out <out.mp4> [--duration 30] [--fps 30] [--width 1080] [--height 1920]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from PIL import Image

from whiteboard_skill import whiteboard
from whiteboard_skill.preprocess import Stroke
from whiteboard_skill.whiteboard import render_scene

ROOT = Path(__file__).resolve().parent
ORIGINAL_COLOR_FILL = whiteboard._color_fill_frame

def load_path_strokes(path: Path) -> list[Stroke]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    strokes: list[Stroke] = []
    for d in payload:
        nums = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', d)]
        points = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        if len(points) >= 2:
            strokes.append(Stroke(points=points, source='gongbi'))
    return strokes

def hold_finished_canvas(canvas, source, progress, mode='contour-wipe', blocks=18, contour_cache=None):
    return canvas.copy(), None, 0.0

def no_complete_snap(canvas, *args, **kwargs):
    return canvas.copy()

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', required=True)
    ap.add_argument('--features', default=None)
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--duration', type=float, default=30.0)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1920)
    ap.add_argument('--keep-completion', action='store_true', help='let engine fill remaining ink at end')
    ap.add_argument('--line-thickness', type=int, default=2)
    ap.add_argument('--brush-tail', action='store_true', help='use engine brush-scan tail fill instead of hold')
    ap.add_argument('--paper', default=None, help='hex paper bg color (default: sample from base corner)')
    ap.add_argument('--tail-color-sec', type=float, default=2.5)
    args = ap.parse_args()

    if not args.brush_tail:
        whiteboard._color_fill_frame = hold_finished_canvas
    if not args.keep_completion:
        whiteboard._complete_line_art_canvas = no_complete_snap

    # warm paper background on the drawing canvas (no sweep = bg must be paper from frame 1)
    if args.paper:
        hx = args.paper.strip().lstrip("#")
        paper_bg = tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))
    else:
        paper_bg = Image.open(args.base).convert("RGB").getpixel((2, 2))
    whiteboard.CANVAS_BG = paper_bg

    resolution = (args.width, args.height)
    strokes = load_path_strokes(Path(args.paths))
    if args.features:
        strokes.extend(load_path_strokes(Path(args.features)))
    if resolution != (1080, 1920):
        sx, sy = args.width / 1080.0, args.height / 1920.0
        strokes = [Stroke(points=[(x * sx, y * sy) for x, y in s.points], source=s.source) for s in strokes]

    line_art = Image.open(args.base).convert('RGB').resize(resolution)
    render_scene(
        Path(args.paths),
        strokes,
        duration=args.duration,
        out_path=Path(args.out),
        fps=args.fps,
        resolution=resolution,
        tail_color_sec=args.tail_color_sec,
        line_thickness=args.line_thickness,
        source_image=line_art,
        hand_style='asian',
        hand_scale=0.4,
        complete_line_art=line_art,
        line_art_snap=True,
        line_art_snap_threshold=245,
        color_fill_mode='brush-scan' if args.brush_tail else 'fade',
    )
    print(Path(args.out))

if __name__ == '__main__':
    main()
