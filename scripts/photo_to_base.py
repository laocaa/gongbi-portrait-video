#!/usr/bin/env python3
"""Convert ANY photo / line-art / ink drawing into a clean 2-tone ink-on-paper base.

This is the generic front door of the gongbi hand-drawn video pipeline:
any input image becomes a 1080x1920 (default) warm rice-paper canvas with
flat ink marks, ready for skeleton tracing + stroke-by-stroke rendering.

Modes
-----
- gongbi : direct grayscale threshold (best for line art / ink drawings /
           scanned drawings that are already 2-tone-ish).
- sketch : adaptive threshold (best for real photos / color images; turns the
           photo into hand-drawn-looking line work).
- auto   : pick automatically: if the image is already mostly light paper with
           dark marks and low color, use gongbi, otherwise sketch.

Usage:
  photo_to_base.py --source <img> --out <base.png>
      [--width 1080] [--height 1920]
      [--mode auto|gongbi|sketch]
      [--paper "#fdfaf2"] [--ink "#2b2620"] [--ink-threshold 235]
      [--texture 2.5]          # paper-grain amplitude (0 = off)
      [--unsharp 0.6]          # upscale sharpening amount (0 = off)
      [--denoise 3]            # median filter kernel (odd; 0 = off)
      [--min-speck 6]          # drop ink specks smaller than this many px
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    from whiteboard_skill.preprocess import zhang_suen_skeleton
except Exception:  # pragma: no cover
    zhang_suen_skeleton = None


def hex_color(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))


def is_already_paper_ink(gray: np.ndarray, dark_threshold: int) -> tuple[bool, float]:
    """Return (looks_like_line_art, dark_fraction)."""
    light = gray > min(255, dark_threshold + 8)
    dark = gray < dark_threshold
    light_frac = float(light.mean())
    dark_frac = float(dark.mean())
    looks = light_frac > 0.35 and 0.005 < dark_frac < 0.65
    return looks, dark_frac


def trim_to_content(img: np.ndarray, gray: np.ndarray, margin_frac: float = 0.02) -> np.ndarray:
    """Crop away empty borders so the subject fills the canvas (no wasted start)."""
    h, w = gray.shape
    hist = np.bincount(gray.ravel(), minlength=256)
    bg = int(np.argmax(hist))
    dark = gray < max(0, bg - 45)
    ys, xs = np.where(dark)
    if len(ys) == 0:
        return img
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    # only trim when the content is clearly smaller than the frame
    if cw * ch > 0.9 * w * h:
        return img
    mx = max(4, int(cw * margin_frac))
    my = max(4, int(ch * margin_frac))
    x0, x1 = max(0, x0 - mx), min(w - 1, x1 + mx)
    y0, y1 = max(0, y0 - my), min(h - 1, y1 + my)
    return img[y0 : y1 + 1, x0 : x1 + 1]


def build_base(
    img: np.ndarray,
    width: int,
    height: int,
    paper: tuple[int, int, int],
    ink: tuple[int, int, int],
    mode: str,
    ink_threshold: int,
    texture: float,
    unsharp: float,
    denoise: int,
    min_speck: int,
    detail: bool = False,
    no_trim: bool = False,
) -> tuple[np.ndarray, dict]:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    elif img.ndim == 3 and img.shape[2] == 3:
        img = img.copy()

    h, w = img.shape[:2]

    # ---- auto-crop empty borders so the subject fills the canvas -----------
    if not no_trim:
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = trim_to_content(img, img_gray)
        h, w = img.shape[:2]

    # ---- resize to contain, then center on the target canvas -------------
    scale = min(width / w, height / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    resized = cv2.resize(img, (nw, nh), interpolation=interp)

    # mild unsharp after upscaling keeps thin lines crisp
    if unsharp > 0:
        blurred = cv2.GaussianBlur(resized, (0, 0), 1.2)
        resized = cv2.addWeighted(resized, 1.0 + unsharp, blurred, -unsharp, 0)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    if denoise and denoise % 2 == 1:
        gray = cv2.medianBlur(gray, denoise)

    looks_like_art, dark_frac = is_already_paper_ink(gray, ink_threshold)
    if mode == "auto":
        mode = "gongbi" if looks_like_art else "sketch"

    if mode == "sketch":
        # adaptive threshold -> hand-drawn style line work from any photo
        # detail tier is the default: fine block + low C captures the most line detail
        block = max(15, (min(nw, nh) // 24) | 1)
        cval = 8
        thr = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, cval
        )
        dark = thr > 0
    else:  # gongbi
        dark = gray < ink_threshold

    # clean tiny specks
    if min_speck > 0:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8), 8)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < min_speck:
                dark[labels == i] = False

    # ---- compose 2-tone ink on paper --------------------------------
    paper_bgr = np.array(paper, dtype=np.uint8)[::-1]
    ink_bgr = np.array(ink, dtype=np.uint8)[::-1]
    out = np.full((nh, nw, 3), paper_bgr, dtype=np.uint8)
    out[dark] = ink_bgr

    # subtle warm paper grain (kept light enough to not read as ink)
    if texture > 0:
        rng = np.random.default_rng(20260811)
        grain = np.clip(rng.normal(0.0, texture, (nh, nw, 1)).astype(np.float32), -3.0, 3.0)
        out = np.clip(out.astype(np.float32) + grain, 0, 255).astype(np.uint8)
        # clamp paper above the engine ink threshold (gray 245) so grain never
        # reads as ink specks; re-flatten ink so lines stay pure
        out = np.maximum(out, (np.asarray(paper_bgr, dtype=np.int16) - 3).reshape(1, 1, 3)).astype(np.uint8)
        out[dark] = ink_bgr

    canvas = np.full((height, width, 3), paper_bgr, dtype=np.uint8)
    x0, y0 = (width - nw) // 2, (height - nh) // 2
    canvas[y0 : y0 + nh, x0 : x0 + nw] = out

    info = {
        "mode": mode,
        "dark_frac": round(float(dark.mean()), 4),
        "placed": (nw, nh, x0, y0),
    }
    return canvas, info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--mode", choices=["auto", "gongbi", "sketch"], default="auto")
    ap.add_argument("--detail", action="store_true", help="finer sketch threshold for more detail")
    ap.add_argument("--no-trim", action="store_true", help="disable auto-crop of empty image borders")
    ap.add_argument("--paper", default="#fdfaf2")
    ap.add_argument("--ink", default="#2b2620")
    ap.add_argument("--ink-threshold", type=int, default=235)
    ap.add_argument("--texture", type=float, default=2.5)
    ap.add_argument("--unsharp", type=float, default=0.6)
    ap.add_argument("--denoise", type=int, default=3)
    ap.add_argument("--min-speck", type=int, default=6)
    args = ap.parse_args()

    img = cv2.imread(args.source, cv2.IMREAD_UNCHANGED)
    if img is None:
        sys.exit(f"cannot read {args.source}")

    canvas, info = build_base(
        img,
        args.width,
        args.height,
        hex_color(args.paper),
        hex_color(args.ink),
        args.mode,
        args.ink_threshold,
        args.texture,
        args.unsharp,
        args.denoise,
        args.min_speck,
        args.detail,
        args.no_trim,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, canvas)
    print(args.out)
    print(
        f"size={args.width}x{args.height} mode={info['mode']} "
        f"ink={info['dark_frac'] * 100:.1f}% placed={info['placed']}"
    )


if __name__ == "__main__":
    main()
