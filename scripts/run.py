#!/usr/bin/env python3
"""One-shot: ANY photo / drawing -> hand-drawn gongbi video (1080x1920, 30s).

A pure-Codex-agent entry point. Just run:

    python3 scripts/run.py --source /path/to/photo.jpg

It self-bootstraps the engine venv (needs network once), converts the photo to
a clean ink-on-paper base, traces stroke-by-stroke paths, renders the MP4 with
a hand + brush-sweep tail, grades it, and runs QC.

Options
-------
  --source IMG            input image (required)
  --workdir DIR           working dir (default: ./handdraw-runs/<name>)
  --out PATH              final mp4 path (default: <workdir>/<name>-handdrawn-1080.mp4)
  --width / --height      canvas size (default 1080 x 1920)
  --duration / --fps      video length / frame rate (default 50 / 30)
  --tail-sec              hold+lift ending seconds (default 4; no brush sweep)
  --line-thickness        pen width (default 2)
  --min-len               minimum stroke length in px (default 3; lower = denser)
  --mode auto|gongbi|sketch   base conversion mode (default auto)
  --face-box x0,y0,x1,y1  draw face-region strokes last
  --auto-face             guess the face region automatically
  --skip-region x0,y0,x1,y1  exclude region from strokes (revealed by tail sweep)
  --keep-completion       let engine fill remaining ink at the end
  --engine-python PATH    python with cv2 + whiteboard_skill (default: auto)
  --no-bootstrap          never install/create a venv
  --texture 0..6          paper-grain amount (default 2.5)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# engine discovery / bootstrap
# --------------------------------------------------------------------------

ENGINE_DEPS = ["numpy", "PIL", "cv2", "whiteboard_skill"]
REQUIREMENTS = [
    "numpy",
    "pillow",
    "opencv-python-headless",
    "git+https://github.com/gnipbao/whiteboard-video-engine.git",
]

COMMON_VENVS = [
    "~/.local/share/gongbi-whiteboard-venv/bin/python",
    "~/.whiteboard-venv/bin/python",
    "~/.venvs/gongbi/bin/python",
    "~/videos/line-portrait-3d/.whiteboard-venv/bin/python",
]


def _has_deps(py: Path) -> bool:
    if not py.exists():
        return False
    code = "import importlib; print(all(importlib.import_module(m) for m in ['numpy','PIL','cv2','whiteboard_skill']))"
    try:
        out = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=30)
        return "True" in out.stdout
    except Exception:
        return False


def find_engine_python(workdir: Path, script_dir: Path) -> Path | None:
    candidates = [
        Path(workdir) / ".whiteboard-venv/bin/python",
        Path(script_dir) / ".whiteboard-venv/bin/python",
        Path(script_dir).parent / ".whiteboard-venv/bin/python",
    ]
    candidates += [Path(p).expanduser() for p in COMMON_VENVS]
    seen = set()
    for py in candidates:
        key = str(py)
        if key in seen:
            continue
        seen.add(key)
        if _has_deps(py):
            return py
    return None


def bootstrap_engine(workdir: Path, script_dir: Path, no_bootstrap: bool) -> Path:
    """Create a shared venv next to the scripts (or in workdir) and install deps."""
    if no_bootstrap:
        sys.exit(
            "engine venv not found (needs numpy+PIL+cv2+whiteboard_skill). "
            "Rerun without --no-bootstrap, or pass --engine-python."
        )
    shared = Path(script_dir).parent / ".whiteboard-venv"
    venv_dir = shared if os.access(shared.parent, os.W_OK) else Path(workdir) / ".whiteboard-venv"
    venv_py = venv_dir / "bin/python"
    if venv_py.exists() and _has_deps(venv_py):
        return venv_py
    print("[run] bootstrapping engine venv at", venv_dir)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    pip = [str(venv_py), "-m", "pip"]
    subprocess.run(pip + ["install", "--upgrade", "pip"], check=True)
    subprocess.run(pip + ["install"] + REQUIREMENTS, check=True)
    if not _has_deps(venv_py):
        sys.exit("engine venv bootstrap failed")
    return venv_py


# --------------------------------------------------------------------------
# engine patch: pin the perfected whiteboard.py (hand-lift ending etc.)
# --------------------------------------------------------------------------


def apply_engine_patch(engine_py: Path, script_dir: Path) -> None:
    """Overwrite the installed engine's whiteboard.py with the tuned copy."""
    import hashlib

    patched = Path(script_dir).parent / "engine_patch" / "whiteboard.py"
    if not patched.exists():
        return
    site = None
    try:
        out = sh([engine_py, "-c",
                  "import whiteboard_skill, pathlib; print(pathlib.Path(whiteboard_skill.__file__).parent / 'whiteboard.py')"])
        site = Path(out.strip())
    except Exception:
        return
    if not site.exists():
        return
    cur = hashlib.md5(site.read_bytes()).hexdigest()
    want = hashlib.md5(patched.read_bytes()).hexdigest()
    if cur != want:
        site.write_bytes(patched.read_bytes())
        print(f"[run] engine patched: {site}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def run(cmd: list[str]) -> None:
    print("[run]", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def sh(cmd: list[str], **kw) -> str:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, check=True, **kw).stdout.strip()


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        exe = str(Path.home() / ".local/bin/ffmpeg")
        if not Path(exe).exists():
            sys.exit("ffmpeg not found on PATH (install it, e.g. via apt or johnvansickle static build)")
    return exe


# --------------------------------------------------------------------------
# QC
# --------------------------------------------------------------------------


def qc_video(video: Path, base_png: Path, width: int, height: int, duration: float, fps: int) -> None:
    import cv2  # engine python has cv2
    import numpy as np

    probe = sh([ffmpeg(), "-v", "error", "-i", str(video), "-f", "null", "-"])
    print("[qc] ffmpeg decode ok")
    base = cv2.imread(str(base_png), cv2.IMREAD_GRAYSCALE)
    base_ink = float((base < 235).mean())
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[qc] frames={total} (expect ~{int(duration * fps)})")
    coverage: list[tuple[float, float]] = []
    for frac in (0.02, 0.15, 0.35, 0.55, 0.75, 0.97):
        idx = min(total - 1, int(round(frac * (total - 1))))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ink = float((gray < 235).mean())
        coverage.append((round(frac, 2), round(ink, 4)))
        out = frame.copy()
        cv2.putText(out, f"t={frac * duration:.1f}s ink={ink * 100:.1f}%", (40, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 255), 6)
        cv2.imwrite(str(video.parent / f"qc-{int(frac * 100):02d}.jpg"), out)
    # exact final frame must match the base
    cap.set(cv2.CAP_PROP_POS_FRAMES, total - 1)
    ok, last = cap.read()
    cap.release()
    if ok:
        lg = cv2.cvtColor(last, cv2.COLOR_BGR2GRAY)
        last_ink = float((lg < 235).mean())
        bg = cv2.imread(str(base_png), cv2.IMREAD_GRAYSCALE)
        bg_ink = float((bg < 235).mean())
        mae = float(np.abs(last.astype(np.int16) - cv2.imread(str(base_png)).astype(np.int16)).mean())
        cov = last_ink / max(1e-6, bg_ink) * 100
        print(f"[qc] last frame ink={last_ink * 100:.2f}% base ink={bg_ink * 100:.2f}% coverage={cov:.1f}% MAE={mae:.2f}")
        if cov < 90.0:
            print("[qc] WARNING: drawing is incomplete (coverage < 90%); lower --min-len or add fill strokes")
        else:
            print("[qc] OK: artwork fully hand-drawn (no sweep needed)")
    print("[qc] ink coverage by time:", coverage)
    if len(coverage) >= 2:
        inks = [c[1] for c in coverage]
        if inks[-1] < inks[0] + 0.01:
            print("[qc] WARNING: ink coverage did not increase (drawing may be missing)")
        # note: last sampled frame (97%) is still mid-sweep; the exact
        # last-frame check above is the authoritative completion check


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Any photo -> hand-drawn gongbi video")
    ap.add_argument("--source", required=True)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--duration", type=float, default=50.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--tail-sec", type=float, default=4.0)
    ap.add_argument("--line-thickness", type=int, default=2)
    ap.add_argument("--min-len", type=int, default=3)
    ap.add_argument("--detail", action="store_true", help="finer sketch + shorter strokes for more detail")
    ap.add_argument("--mode", choices=["auto", "gongbi", "sketch"], default="auto")
    ap.add_argument("--face-box", default=None)
    ap.add_argument("--auto-face", action="store_true")
    ap.add_argument("--skip-region", action="append", default=[])
    ap.add_argument("--keep-completion", action="store_true")
    ap.add_argument("--brush-tail", action="store_true", help="brush-sweep tail (default: no sweep, everything drawn by hand)")
    ap.add_argument("--engine-python", default=None)
    ap.add_argument("--no-bootstrap", action="store_true")
    ap.add_argument("--texture", type=float, default=2.5)
    args = ap.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        sys.exit(f"source not found: {source}")

    name = source.stem
    workdir = Path(args.workdir).expanduser() if args.workdir else Path.cwd() / "handdraw-runs" / name
    workdir.mkdir(parents=True, exist_ok=True)
    script_dir = Path(__file__).resolve().parent
    out = Path(args.out).expanduser() if args.out else workdir / f"{name}-handdrawn-1080.mp4"

    # 1) engine python
    engine_py = None
    if args.engine_python:
        engine_py = Path(args.engine_python).expanduser()
        if not _has_deps(engine_py):
            sys.exit(f"--engine-python missing deps: {engine_py}")
    else:
        engine_py = find_engine_python(workdir, script_dir)
        if engine_py is None:
            engine_py = bootstrap_engine(workdir, script_dir, args.no_bootstrap)

    print(f"[run] engine python: {engine_py}")
    apply_engine_patch(engine_py, script_dir)

    # 2) photo -> base
    base_png = workdir / "base.png"
    pcmd = [engine_py, script_dir / "photo_to_base.py",
            "--source", source, "--out", base_png,
            "--width", args.width, "--height", args.height,
            "--mode", args.mode, "--texture", args.texture]
    if args.detail:
        pcmd += ["--detail"]
    run(pcmd)

    # 3) skeleton
    skel_png = workdir / "base-skel.png"
    run([engine_py, script_dir / "skeletonize_gongbi.py", "--source", base_png, "--out", skel_png])

    # 4) paths
    strokes_json = workdir / "strokes.json"
    cmd = [engine_py, script_dir / "build_gongbi_paths_from_skeleton.py",
           "--source", skel_png, "--out-json", strokes_json, "--out-svg", workdir / "strokes.svg",
           "--min-len", args.min_len,
           "--base-img", base_png]
    if args.face_box:
        cmd += ["--face-box", args.face_box]
    if args.auto_face:
        cmd += ["--auto-face"]
    for r in args.skip_region:
        cmd += ["--skip-region", r]
    run(cmd)
    n_strokes = len(json.loads(strokes_json.read_text(encoding="utf-8")))
    print(f"[run] strokes={n_strokes}")

    # 5) render
    drawn = workdir / "drawn.mp4"
    rcmd = [engine_py, script_dir / "render_gongbi.py",
            "--paths", strokes_json, "--base", base_png, "--out", drawn,
            "--duration", args.duration, "--fps", args.fps,
            "--width", args.width, "--height", args.height,
            "--line-thickness", args.line_thickness,
            "--tail-color-sec", args.tail_sec,
            "--paper", "#fdfaf2"]
    if args.keep_completion:
        rcmd += ["--keep-completion"]
    if args.brush_tail:
        rcmd += ["--brush-tail"]
    run(rcmd)

    # 6) QC
    qc_video(drawn, base_png, args.width, args.height, args.duration, args.fps)

    # 7) final copy
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(drawn, out)
    print("[run] DONE ->", out)


if __name__ == "__main__":
    main()
