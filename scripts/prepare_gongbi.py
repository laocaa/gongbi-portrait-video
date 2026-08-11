#!/usr/bin/env python3
"""Prepare a portrait source as a clean 2-tone gongbi ink-on-rice-paper base.

Usage:
  prepare_gongbi.py --source <img> --out <base.png> [--width 1080] [--height 1920]
                    [--paper "#f7f2e7"] [--ink "#23201c"] [--erase X,Y,W,H]
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import cv2, numpy as np

def hex_color(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip('#')
    return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1920)
    ap.add_argument('--paper', default='#f7f2e7')
    ap.add_argument('--ink', default='#23201c')
    ap.add_argument('--ink-threshold', type=int, default=235)
    ap.add_argument('--erase', default=None, help='X,Y,W,H bbox to erase (fill+inpaint)')
    args = ap.parse_args()

    img = cv2.imread(args.source, cv2.IMREAD_UNCHANGED)
    if img is None:
        sys.exit(f'cannot read {args.source}')
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    h, w = img.shape[:2]
    target_w, target_h = args.width, args.height

    # Resize to contain, then center on paper canvas
    scale = min(target_w / w, target_h / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)

    paper = np.array(hex_color(args.paper), dtype=np.uint8)[::-1]  # BGR
    ink = np.array(hex_color(args.ink), dtype=np.uint8)[::-1]      # BGR
    canvas = np.full((target_h, target_w, 3), paper, dtype=np.uint8)
    x0, y0 = (target_w - nw) // 2, (target_h - nh) // 2
    canvas[y0:y0+nh, x0:x0+nw] = resized

    # Optional erase: remove a decoration (butterfly etc.) by inpaint to paper
    if args.erase:
        ex, ey, ew, eh = map(int, args.erase.split(','))
        mask = np.zeros((target_h, target_w), dtype=np.uint8)
        mask[ey:ey+eh, ex:ex+ew] = 255
        canvas = cv2.inpaint(canvas, mask, 5, cv2.INPAINT_TELEA)

    # Threshold to 2-tone ink on paper
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    dark = gray < args.ink_threshold
    out = np.full_like(canvas, paper)
    out[dark] = ink
    # Remove specks smaller than a few px
    d = dark.astype(np.uint8) * 255
    d = cv2.morphologyEx(d, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    out[d == 0] = paper

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, out)
    ink_frac = float((d > 0).mean())
    print(args.out)
    print(f'size={target_w}x{target_h} ink={ink_frac*100:.1f}%')

if __name__ == '__main__':
    main()
