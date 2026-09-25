#!/usr/bin/env python3
"""Compress a phone photo for the recipe blog before committing it.

Paperwork: images/<post-slug>/<name>.jpg  ->  referenced as /images/<post-slug>/<name>.jpg
Featured images want to be ~1560px wide; a 1.5MB phone photo lands near 300-400KB.

Usage:
  python3 scripts/compress_image.py --in ~/IMG_1234.jpg --slug butterhorn-rolls --name rolls
  python3 scripts/compress_image.py --in photo.jpg --out images/butterhorn-rolls/rolls.jpg --width 1560
"""
import argparse, os, sys
from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out")
    ap.add_argument("--slug")
    ap.add_argument("--name", default="featured")
    ap.add_argument("--width", type=int, default=1560)
    ap.add_argument("--quality", type=int, default=82)
    a = ap.parse_args()

    out = a.out
    if not out:
        if not a.slug:
            sys.exit("need --out or --slug")
        out = os.path.join(ROOT, "images", a.slug, a.name + ".jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    before = os.path.getsize(a.src)
    im = ImageOps.exif_transpose(Image.open(a.src)).convert("RGB")
    w0, h0 = im.size
    if w0 > a.width:
        im = im.resize((a.width, max(1, round(h0 * a.width / w0))), Image.LANCZOS)
    im.save(out, "JPEG", quality=a.quality, optimize=True, progressive=True)
    after = os.path.getsize(out)
    print("in : %s  %dx%d  %.0f KB" % (a.src, w0, h0, before / 1024.0))
    print("out: %s  %dx%d  %.0f KB  (%.0f%% smaller)" % (out, im.size[0], im.size[1], after / 1024.0, 100.0 * (1 - after / float(before))))
    print("reference it as: /images/%s" % os.path.basename(os.path.dirname(out)) + "/" + os.path.basename(out))


if __name__ == "__main__":
    main()
