---
name: gongbi-portrait-video
description: Turn ANY photo or drawing into a vertical hand-drawn gongbi-style video where the ENTIRE artwork is drawn stroke by stroke (no AI sweep) — fine ink structure lines first, thick washes filled in with hatching strokes, face region last, warm rice-paper background from frame 1, hand lifts at the end. Use for 任意照片转手绘视频, 国风/工笔逐笔视频, portrait line-art videos, and turning photos into hand-drawn (白描/线稿) videos. One command: python3 scripts/run.py --source photo.jpg.
---

# Gongbi Hand-Drawn Video (任意照片 → 全程手绘逐笔视频)

## Goal

Convert **any** input image (photo, portrait, line art, ink painting, screenshot)
into a vertical **1080x1920 / 50s / 30fps** MP4 where the **whole artwork is
drawn by hand from start to finish**:

1. fine ink **structure lines** are drawn stroke by stroke (face region last),
2. thick washes / dense dark areas are completed with **hatching (皴笔) fill
   strokes** so no ink is left over,
3. warm rice-paper background is present from frame 1,
4. the hand **lifts off** at the end.

There is **no brush-sweep / AI-fill tail** — everything you see is drawn.

## One-command usage (for a pure Codex agent)

```bash
python3 scripts/run.py --source /path/to/any-photo.jpg
```

`run.py` will:

1. auto-bootstrap a shared `.whiteboard-venv` (first run needs network:
   numpy / pillow / opencv-python-headless / whiteboard-video-engine, then
   applies the tuned engine patch in `engine_patch/`),
2. convert the photo to a clean ink-on-paper base
   (`--mode auto` picks gongbi threshold for line art / sketch adaptive
   threshold for real photos; paper grain is clamped above the ink threshold),
3. skeletonize + trace open strokes (`--min-len 8`, dense), then automatically
   hatch-fill thick ink regions so the drawing covers ~100% of the artwork,
4. render the MP4 (hand + hold + lift; **no sweep by default**),
5. run QC (frame count, ink-coverage curve, final frame == base) and copy the
   final video to `<workdir>/<name>-handdrawn-1080.mp4` (or `--out`).

Output default: `./handdraw-runs/<name>/<name>-handdrawn-1080.mp4`

## Common options

| option | default | meaning |
| --- | --- | --- |
| `--source IMG` | (required) | input photo / drawing |
| `--workdir DIR` | `./handdraw-runs/<name>` | working dir (shared venv + assets) |
| `--out PATH` | workdir output | final mp4 path |
| `--width/--height` | 1080 / 1920 | canvas size |
| `--duration/--fps` | 50 / 30 | video length / frame rate (≤60s ok) |
| `--tail-sec` | 4 | final hold + hand-lift seconds |
| `--line-thickness` | 1 | pen width (1 = fine gongbi/白描 lines) |
| `--min-len` | 3 | min stroke length in px (detail tier by default) |
| `--mode auto\|gongbi\|sketch` | auto | base conversion mode |
| `--face-box x0,y0,x1,y1` | auto off | draw face-region strokes last |
| `--auto-face` | off | guess the face region automatically |
| `--keep-completion` | off | let engine fade in any remaining ink at the end |
| `--brush-tail` | off | opt-in brush-sweep tail (default: no sweep, everything drawn) |
| `--texture 0..6` | 2.5 | rice-paper grain amount (clamped above ink threshold) |

## Tips for good results

- **Real photos**: default `--mode auto` switches to a fine adaptive-threshold
  sketch (thinned to continuous ~5px line art, 白描 style); stroke counts are
  high and the whole photo gets drawn. Use `--mode sketch` to force it.
- **Line art / ink drawings**: `--mode auto` → gongbi threshold. Low-res
  sources are upscaled with unsharp; thin lines stay crisp.
- **Faces**: pass `--auto-face` (or a manual `--face-box`) so facial strokes are
  drawn last for dramatic effect.
- **Very dense small text / seals**: complex glyph regions may keep a few
  percent of ink un-drawn (visually negligible); lower `--min-len` to 4-6 or
  pass `--keep-completion` if you want them 100% filled.

## Troubleshooting

- **First run needs network** (pip + git clone). Subsequent runs reuse the
  shared venv.
- **ffmpeg not found**: install it (e.g. `apt install ffmpeg`, or download the
  johnvansickle static build to `~/.local/bin`).
- **`--engine-python PATH`**: point at any venv python that already has
  numpy+PIL+cv2+whiteboard_skill.
- **QC says coverage < 90%**: the drawing missed ink — lower `--min-len`
  (denser strokes), or add `--keep-completion`.
- **Engine patch not applied**: `run.py` copies `engine_patch/whiteboard.py`
  over the installed engine automatically; keep it next to `scripts/`.

## 中文备注

竖版工笔手绘视频：细墨线逐笔画出结构（五官最后）→ 皴笔/排笔填满厚墨区 →
宣纸暖底全程在 → 结尾抬笔。无扫尾、无 AI 补全，整幅作品从头到尾都是画的。
任意照片/线稿/水墨画一键生成，默认 50 秒 / 1080x1920 / 30fps。
