#!/usr/bin/env python3
"""Thin a 2-tone gongbi base into a 1px dark skeleton on a light canvas.

Usage:
  skeletonize_gongbi.py --source <base.png> --out <base-skel.png> [--threshold 245]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from whiteboard_skill.preprocess import zhang_suen_skeleton


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=int, default=245)
    args = ap.parse_args()

    gray = cv2.imread(args.source, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        sys.exit(f"cannot read {args.source}")
    dark = gray < args.threshold
    skel = zhang_suen_skeleton(dark)
    out = np.full(gray.shape, 255, dtype=np.uint8)
    out[skel] = 0
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, out)
    print(args.out)
    print(f"skel_px={int(skel.sum())} ink_px={int(dark.sum())} ratio={dark.sum()/max(1,skel.sum()):.1f}")


if __name__ == "__main__":
    main()
