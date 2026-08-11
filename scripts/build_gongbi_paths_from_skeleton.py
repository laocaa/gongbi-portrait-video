#!/usr/bin/env python3
"""Trace open stroke paths along a 1px skeleton: one clean stroke per ink line.

Generic version: works for ANY drawing / photo-converted line art, not just
one portrait set. Face-region strokes are optionally ordered last.

Usage:
  build_gongbi_paths_from_skeleton.py --source <base-skel.png> --out-json paths.json
      [--out-svg paths.svg]
      [--min-len 12] [--simplify 0.8]
      [--face-box x0,y0,x1,y1]      # draw face-region strokes last
      [--auto-face]                 # guess the face box from stroke density
      [--skip-region x0,y0,x1,y1]   # exclude a region from strokes (revealed
                                    # later by the tail sweep); repeatable
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

NEI8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if not (dx == 0 and dy == 0)]


def neighbors(mask, y, x):
    h, w = mask.shape
    out = []
    for dx, dy in NEI8:
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and mask[ny, nx]:
            out.append((nx, ny))
    return out


def trace_from(mask, visited, start, ends):
    """Trace a chain from start until an endpoint/junction/visited pixel."""
    h, w = mask.shape
    chain = [start]
    visited[start[1], start[0]] = True
    cur = start
    while True:
        nbrs = [p for p in neighbors(mask, cur[1], cur[0]) if not visited[p[1], p[0]]]
        if not nbrs:
            break
        nxt = nbrs[0]
        chain.append(nxt)
        visited[nxt[1], nxt[0]] = True
        if nxt in ends:
            break
        if len(nbrs) > 1:  # junction: stop after consuming the first arm
            break
        cur = nxt
    return chain


def inside(chain, box):
    fx0, fy0, fx1, fy1 = box
    pts = np.asarray(chain)
    cx, cy = pts.mean(axis=0)
    return fx0 <= cx <= fx1 and fy0 <= cy <= fy1


def guess_face_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Find the densest stroke window in the upper half of the canvas."""
    h, w = mask.shape
    if h < 60 or w < 60:
        return None
    win_w = max(60, int(w * 0.30))
    win_h = max(60, int(h * 0.16))
    top_limit = int(h * 0.55)
    integral = cv2.integral(mask.astype(np.float32))
    best_score = -1.0
    best = None
    step = max(8, min(win_w, win_h) // 8)
    for y0 in range(0, top_limit - win_h + 1, step):
        for x0 in range(0, w - win_w + 1, step):
            area = (
                integral[y0 + win_h, x0 + win_w]
                - integral[y0, x0 + win_w]
                - integral[y0 + win_h, x0]
                + integral[y0, x0]
            )
            if area > best_score:
                best_score = area
                best = (x0, y0, x0 + win_w, y0 + win_h)
    if best is None or best_score < max(40.0, mask.sum() * 0.002):
        return None
    # pad a little
    x0, y0, x1, y1 = best
    padx, pady = int(win_w * 0.15), int(win_h * 0.18)
    return (max(0, x0 - padx), max(0, y0 - pady), min(w, x1 + padx), min(h, y1 + pady))




def add_fill_strokes(
    dark: np.ndarray,
    skel_polys: list[np.ndarray],
    radius: int,
    min_len: int,
    max_strokes: int = 12000,
) -> list[np.ndarray]:
    """Hatch-fill thick ink areas so the whole painting is covered by pen strokes.

    Coverage is tracked with the exact same primitive the renderer uses
    (PIL ImageDraw.line with width ``2*radius``), so the generated strokes are
    guaranteed to reveal ~100% of the artwork's ink when rendered.
    """
    from PIL import Image, ImageDraw

    h, w = dark.shape
    r = max(6, int(radius))
    wdt = max(6, 2 * r)
    covered_img = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(covered_img)
    for poly in skel_polys:
        if len(poly) >= 2:
            dr.line([(float(p[0][0]), float(p[0][1])) for p in poly], fill=255, width=wdt, joint="curve")
    covered = np.asarray(covered_img) > 0
    fill: list[tuple[int, int, int, int]] = []  # (a, b, c, direction)
    total_dark = int(dark.sum())

    def draw_added(added: list[tuple[int, int, int, int]]) -> None:
        for (a, b, c, direction) in added:
            if direction == 0:
                dr.line([(float(b), float(a)), (float(c), float(a))], fill=255, width=wdt)
            else:
                dr.line([(float(a), float(b)), (float(a), float(c))], fill=255, width=wdt)

    def run_pass(step: int, lo_min: int, iterations: int) -> bool:
        nonlocal covered
        made = False
        for _ in range(iterations):
            uncovered = dark & ~covered
            if uncovered.sum() < max(40, total_dark * 0.0015):
                break
            before = len(fill)
            for pass_idx in (0, 1):
                uncovered = dark & ~covered
                if uncovered.sum() < max(40, total_dark * 0.0015):
                    break
                lines = range(0, h, step) if pass_idx == 0 else range(0, w, step)
                for pos in lines:
                    idx = np.flatnonzero(uncovered[pos]) if pass_idx == 0 else np.flatnonzero(uncovered[:, pos])
                    if len(idx) == 0:
                        continue
                    splits = np.where(np.diff(idx) > 1)[0] + 1
                    for seg in np.split(idx, splits):
                        if len(seg) < lo_min:
                            continue
                        a, b = int(seg[0]), int(seg[-1])
                        fill.append((pos, a, b, pass_idx))
                        if len(fill) >= max_strokes:
                            break
                    if len(fill) >= max_strokes:
                        break
                if len(fill) >= max_strokes:
                    break
            added = fill[before:]
            draw_added(added)
            covered = np.asarray(covered_img) > 0
            if len(added) == 0:
                break
            made = True
        return made

    run_pass(max(10, int(r * 1.2)), max(3, min_len // 2), 12)   # main grid
    run_pass(max(6, r // 2), 2, 8)                               # micro pass
    run_pass(max(4, r // 4), 1, 6)                               # micro-pass 2: 1px fragments

    result = []
    for (a, b, c, direction) in sorted(fill, key=lambda t: (t[0], t[1])):
        if direction == 0:
            pts = [(float(x), float(a)) for x in range(b, c + 1, max(1, (c - b) // 200))]
        else:
            pts = [(float(a), float(y)) for y in range(b, c + 1, max(1, (c - b) // 200))]
        result.append(np.asarray(pts, dtype=np.float32))
    return result


def chaikin_smooth(pts: np.ndarray, iterations: int = 2) -> np.ndarray:
    """Corner-cutting curve smoothing that preserves the endpoints."""
    pts = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    for _ in range(iterations):
        if len(pts) < 3:
            break
        out = [pts[0]]
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            out.append(p0 * 0.75 + p1 * 0.25)
            out.append(p0 * 0.25 + p1 * 0.75)
        out.append(pts[-1])
        pts = np.asarray(out, dtype=np.float32)
    return pts


def split_polyline(pts: np.ndarray, max_len: float) -> list[np.ndarray]:
    """Split a polyline into segments each no longer than max_len."""
    pts = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    if len(pts) < 2 or max_len <= 0:
        return [pts]
    segs: list[np.ndarray] = []
    cur = [pts[0]]
    cur_len = 0.0
    for p in pts[1:]:
        d = float(math.hypot(p[0] - cur[-1][0], p[1] - cur[-1][1]))
        if cur_len + d > max_len and len(cur) >= 2:
            segs.append(np.asarray(cur, dtype=np.float32))
            cur = [cur[-1], p]
            cur_len = d
        else:
            cur.append(p)
            cur_len += d
    if len(cur) >= 2:
        segs.append(np.asarray(cur, dtype=np.float32))
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-svg", default=None)
    ap.add_argument("--min-len", type=int, default=12)
    ap.add_argument("--max-stroke-len", type=float, default=240.0,
                    help="split strokes longer than this (px) so pacing stays even")
    ap.add_argument("--simplify", type=float, default=0.8)
    ap.add_argument("--face-box", default=None, help="x0,y0,x1,y1")
    ap.add_argument("--auto-face", action="store_true", help="guess face box")
    ap.add_argument("--skip-region", action="append", default=[], help="x0,y0,x1,y1 (repeatable)")
    ap.add_argument("--base-img", default=None, help="full 2-tone base png (for thick-area fill pass)")
    ap.add_argument("--no-fill", action="store_true", help="disable thick-area hatching fill")
    ap.add_argument("--fill-radius", type=int, default=0, help="reveal half-width used to space fill strokes (0=auto)")
    args = ap.parse_args()

    gray = cv2.imread(args.source, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        sys.exit(f"cannot read {args.source}")
    mask = (gray < 245).astype(np.uint8)

    skip_boxes = [tuple(map(int, r.split(","))) for r in args.skip_region]
    for (sx0, sy0, sx1, sy1) in skip_boxes:
        mask[sy0:sy1, sx0:sx1] = 0

    # endpoints and junctions
    h, w = mask.shape
    ys, xs = np.where(mask == 1)
    ends = set()
    for x, y in zip(xs, ys):
        cnt = sum(1 for nx, ny in neighbors(mask, y, x))
        if cnt <= 1:
            ends.add((x, y))

    visited = np.zeros_like(mask, dtype=bool)
    chains = []
    for start in ends:
        if visited[start[1], start[0]]:
            continue
        chain = trace_from(mask, visited, start, ends)
        if len(chain) >= args.min_len:
            chains.append(chain)
    # any remaining unvisited skeleton (closed loops): start anywhere
    rem = np.where((mask == 1) & (~visited))
    for y, x in zip(rem[0], rem[1]):
        if visited[y, x]:
            continue
        chain = trace_from(mask, visited, (x, y), ends)
        if len(chain) >= args.min_len:
            chains.append(chain)

    # order: optional face region last, then top-to-bottom
    face_box = None
    if args.face_box:
        face_box = tuple(map(int, args.face_box.split(",")))
    elif args.auto_face:
        face_box = guess_face_box(mask)

    fill_chains: list[np.ndarray] = []
    if not args.no_fill and args.base_img:
        base_gray = cv2.imread(args.base_img, cv2.IMREAD_GRAYSCALE)
        if base_gray is not None:
            dark_full = base_gray < 245
            est_width = float(dark_full.sum()) / max(1.0, float(mask.sum()))
            # must match the engine's reveal-width formula (render_gongbi line-thickness 2)
            reveal_width = max(2 * 10 + 6, int(round(est_width * 6)), 30)
            radius = args.fill_radius if args.fill_radius > 0 else reveal_width // 2
            # coverage is computed from the chains that were actually kept
            # (the tracer drops short/branch skeleton pixels)
            traced_polys = [
                np.asarray(chain, dtype=np.int32).reshape(-1, 1, 2)
                for chain in chains if len(chain) >= 2
            ]
            fill_chains = add_fill_strokes(dark_full, traced_polys, radius, max(6, args.min_len))
            print(f"fill_strokes={len(fill_chains)} radius={radius} est_width={est_width:.1f}")

    if face_box:
        face_chains = [c for c in chains if inside(c, face_box)]
        body_chains = [c for c in chains if not inside(c, face_box)]
        body_chains.sort(key=lambda c: (min(p[1] for p in c) // 120, -len(c)))
        face_chains.sort(key=lambda c: (min(p[1] for p in c) // 60, -len(c)))
        ordered = body_chains + face_chains
    else:
        ordered = sorted(chains, key=lambda c: (min(p[1] for p in c) // 120, -len(c)))

    # insert fill strokes (hatching for thick washes) between body and face,
    # so facial detail is drawn last
    if fill_chains:
        if face_box:
            face_chains = ordered[-len(face_chains):] if face_chains else []
            ordered = ordered[: len(ordered) - len(face_chains)] + list(fill_chains) + face_chains
        else:
            ordered = ordered + list(fill_chains)

    path_data = []
    for chain in ordered:
        pts = np.asarray(chain, dtype=np.float32).reshape(-1, 2)
        if len(pts) > 4:
            pts = cv2.approxPolyDP(pts, args.simplify, False).reshape(-1, 2)
        if len(pts) < 2:
            continue
        for sub in split_polyline(pts, args.max_stroke_len):
            if len(sub) < 2:
                continue
            d = "M %.1f %.1f" % (sub[0][0], sub[0][1])
            for p in sub[1:]:
                d += " L %.1f %.1f" % (p[0], p[1])
            path_data.append(d)

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(path_data, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.out_svg:
        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (w, h, w, h),
            '  <rect width="%d" height="%d" fill="#fdfaf2"/>' % (w, h),
        ]
        for i, d in enumerate(path_data):
            svg.append(f'  <path id="s{i:03d}" d="{d}" fill="none" stroke="#2b2620" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>')
        svg.append("</svg>")
        Path(args.out_svg).write_text("\n".join(svg), encoding="utf-8")
    print(args.out_json)
    print(f"body={len(ordered) - (len(face_chains) if face_box else 0)} face={len(face_chains) if face_box else 0} total={len(path_data)}")


if __name__ == "__main__":
    main()
