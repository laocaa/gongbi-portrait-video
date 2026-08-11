# gongbi-portrait-video 任意照片 → 全程手绘逐笔视频

把任意照片/线稿/水墨画变成竖版 (1080×1920 / 30fps) 的**全程手绘视频**：
墨线逐笔画出结构 → 厚墨区皴笔填充 → 宣纸暖底全程在 → 结尾抬笔。
无扫尾、无 AI 补全，整幅作品从头到尾都是画的。

## 一键使用

```bash
python3 scripts/run.py --source /path/to/any-photo.jpg
```

首次运行自动创建共享 venv 并安装依赖（需联网一次），之后任意图片直接复用。
成品默认输出到 `./handdraw-runs/<图片名>/<图片名>-handdrawn-1080.mp4`。

## 脚本

| 脚本 | 作用 |
| --- | --- |
| `scripts/run.py` | 一键总控：bootstrap venv → 转底图 → 骨架 → 笔划 → 渲染 → QC |
| `scripts/photo_to_base.py` | 任意图 → 双色墨线宣纸底（auto/gongbi/sketch；自动裁边） |
| `scripts/skeletonize_gongbi.py` | 细化成 1px 骨架 |
| `scripts/build_gongbi_paths_from_skeleton.py` | 骨架 → 开放笔划 + 厚墨区皴笔填充 + 长笔划拆分 |
| `scripts/render_gongbi.py` | 渲染 MP4（默认无扫尾，纸色画布从第 1 帧开始） |
| `engine_patch/whiteboard.py` | 引擎补丁（见 THIRD_PARTY_NOTICES.md），run.py 自动应用 |

## 常见参数

- `--duration` 时长（默认 50s，≤60s 均可）、`--fps` 帧率、`--width/--height` 画布
- `--min-len` 最短笔划（默认 3，越低越密）；`--detail` 高细节档（默认开启）
- `--face-box x0,y0,x1,y1` 五官区最后画；`--auto-face` 自动判断
- `--line-thickness` 画笔粗细（默认 2）

## 依赖

- Python 3.11+，首次运行自动安装：numpy / pillow / opencv-python-headless /
  whiteboard-video-engine（MIT）
- ffmpeg（需在 PATH）

## 许可证

MIT（见 LICENSE）；第三方组件见 THIRD_PARTY_NOTICES.md。
注意：请勿把含真人肖像的测试图/成品视频提交进本仓库。
