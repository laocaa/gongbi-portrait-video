# Third-Party Notices

This project uses and redistributes the following third-party components:

## whiteboard-video-engine
- Source: https://github.com/gnipbao/whiteboard-video-engine
- License: MIT
- Copyright (c) 2026 Whiteboard Video Engine contributors

`engine_patch/whiteboard.py` is a modified copy of the engine's
`whiteboard_skill/whiteboard.py` (tuned reveal widths, full-ink reveal,
paper-colored canvas, hand-lift ending). The original MIT license applies.

```
MIT License

Copyright (c) 2026 Whiteboard Video Engine contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Runtime dependencies (not bundled, declared in requirements.txt)
- edge-tts — used for Chinese voiceover (Microsoft Edge TTS service)
- opencv-python-headless, numpy, pillow — image processing
- ffmpeg — video encoding
