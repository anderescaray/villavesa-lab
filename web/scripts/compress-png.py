"""Quantise screenshots to a 256-colour palette (lossy but visually identical for UI shots).

Usage: python3 scripts/compress-png.py docs/screenshots/*.png   (requires Pillow)
"""

import sys

from PIL import Image

for path in sys.argv[1:]:
    img = Image.open(path).convert("RGB")
    q = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q.save(path, optimize=True)
    print(f"  compressed {path}")
