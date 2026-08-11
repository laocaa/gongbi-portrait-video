#!/usr/bin/env python3
"""Build ordered gongbi stroke paths from a 2-tone ink-on-paper base.

Groups: main contours, light finish contours, then fine face-region detail last.
Usage:
  build_gongbi_contours.py --source <base.png> --out-json paths.json [--out-svg paths.svg]
                           [--face-box x0,y0,x1,y1]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import cv2, numpy as np

MAIN_THRESHOLD = 235
FINISH_THRESHOLD = 245
MIN_ARC = 12.0
EPSILON = 0.8
MAX_PATHS = 1400
FACE_THRESHOLD = 245
FACE_MIN_ARC = 4.0
FACE_MAX_ARC = 140.0
FACE_EPSILON = 0.4
FACE_MAX_PATHS = 420

def contour_paths(image, mask, *, min_arc=MIN_ARC, epsilon=EPSILON, max_paths=None):
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    paths = []
    for contour in contours:
        length = cv2.arcLength(contour, True)
        if length < min_arc:
            continue
        approx = cv2.approxPolyDP(contour, epsilon, True)
        if len(approx) < 3:
            continue
        x0, y0 = approx[0][0]
        if x0 <= 3 or y0 <= 3 or x0 >= image.shape[1] - 4 or y0 >= image.shape[0] - 4:
            continue
        d = f"M {x0} {y0}"
        for point in approx[1:]:
            x, y = point[0]
            d += f" L {x} {y}"
        d += " Z"
        ys = [int(point[0][1]) for point in approx]
        paths.append((length, y0, min(ys), d))
    paths.sort(key=lambda item: (item[2] // 150, -item[0], item[1]))
    if max_paths:
        paths = paths[:max_paths]
    return paths

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--out-json', required=True)
    ap.add_argument('--out-svg', default=None)
    ap.add_argument('--face-box', default=None, help='x0,y0,x1,y1')
    ap.add_argument('--face-source', default=None, help='original grayscale for face detail pass')
    args = ap.parse_args()

    image = cv2.imread(args.source, cv2.IMREAD_GRAYSCALE)
    if image is None:
        sys.exit(f'cannot read {args.source}')

    main_paths = contour_paths(image, (image < MAIN_THRESHOLD).astype('uint8'), max_paths=MAX_PATHS)
    finish_mask = ((image < FINISH_THRESHOLD) & (image >= MAIN_THRESHOLD)).astype('uint8')
    finish_paths = contour_paths(image, finish_mask, min_arc=8.0, epsilon=0.5, max_paths=MAX_PATHS)

    if args.face_box:
        x0, y0, x1, y1 = map(int, args.face_box.split(','))
    else:
        x0, y0, x1, y1 = (270, 200, 590, 450)  # fallback for this portrait set
    face_image = cv2.imread(args.face_source, cv2.IMREAD_GRAYSCALE) if args.face_source else image
    if face_image is None:
        face_image = image
    face_crop = face_image[y0:y1, x0:x1]
    face_mask = (face_crop < FACE_THRESHOLD).astype('uint8')
    face_contours, _ = cv2.findContours(face_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    face_paths = []
    for contour in face_contours:
        length = cv2.arcLength(contour, True)
        if length < FACE_MIN_ARC or length > FACE_MAX_ARC:
            continue
        approx = cv2.approxPolyDP(contour, FACE_EPSILON, True)
        if len(approx) < 3:
            continue
        d = f"M {approx[0][0][0] + x0} {approx[0][0][1] + y0}"
        for point in approx[1:]:
            x, y = point[0]
            d += f" L {x + x0} {y + y0}"
        d += " Z"
        ys = [int(point[0][1]) + y0 for point in approx]
        face_paths.append((length, int(approx[0][0][1]) + y0, min(ys), d))
    face_paths.sort(key=lambda item: (item[2] // 100, -item[0], item[1]))
    face_paths = face_paths[:FACE_MAX_PATHS]

    paths = main_paths + finish_paths + face_paths
    path_data = [item[3] for item in paths]

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(path_data, ensure_ascii=False, indent=1), encoding='utf-8')
    if args.out_svg:
        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (image.shape[1], image.shape[0], image.shape[1], image.shape[0]),
            '  <rect width="%d" height="%d" fill="#f7f2e7"/>' % (image.shape[1], image.shape[0]),
        ]
        for index, d in enumerate(path_data):
            svg.append(f'  <path id="f{index:03d}" d="{d}" fill="none" stroke="#23201c" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>')
        svg.append('</svg>')
        Path(args.out_svg).write_text('\n'.join(svg), encoding='utf-8')
    print(args.out_json)
    print(f'main={len(main_paths)} finish={len(finish_paths)} face={len(face_paths)} total={len(paths)}')

if __name__ == '__main__':
    main()
