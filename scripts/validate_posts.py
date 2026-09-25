#!/usr/bin/env python3
"""Validate Spackman family recipe posts the way Jekyll will read them.

No Ruby/Jekyll here, so this reimplements the parts that decide whether a post
builds correctly on GitHub Pages:

  * Jekyll's own YAML_FRONT_MATTER_REGEXP  (closing --- must be at column 0)
  * required front-matter keys for the Treat/post layout
  * the published URL predicted from _config.yml permalink + categories
  * every referenced image exists on disk and is within the size budget

Usage:
  python3 scripts/validate_posts.py                 # whole repo (warnings = backlog)
  python3 scripts/validate_posts.py --strict        # treat warnings as errors
  python3 scripts/validate_posts.py --post _posts/2026-06-24-butterhorn-rolls.md
  python3 scripts/validate_posts.py --json
"""
import argparse, io, json, os, re, sys, datetime

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")
try:
    from PIL import Image
except ImportError:
    Image = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Jekyll lib/jekyll/document.rb
JEKYLL_FRONT_MATTER = re.compile(r"\A(---\s*\n.*?\n?)^((---|\.\.\.)\s*$\n?)", re.M | re.S)
POST_FILENAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.(md|markdown|html)$", re.I)

# Recipe vocabulary agreed 2026-09-25: plural everywhere.
CANONICAL_CATEGORIES = {"Cakes", "Breads", "Pies", "Breakfasts", "Cookies", "Desserts"}
LEGACY_SINGULAR = {"Cake": "Cakes", "Bread": "Breads", "Breakfast": "Breakfasts", "Cookie": "Cookies", "Dessert": "Desserts"}

CORE_KEYS = ["date", "title", "categories", "recipe"]
RECIPE_KEYS = ["ingredients_markdown", "directions_markdown"]      # hard requirement
RECIPE_SOFT = ["servings", "prep", "cook"]                         # layout prints them; gaps = blank line in card
SOFT_KEYS = ["featured_image"]                                     # blank tile on /recipes/

MAX_IMAGE_BYTES = 1_000_000        # hard: anything bigger blows the repo/disk budget
TARGET_IMAGE_BYTES = 400_000       # soft: what a compressed 1560px phone photo weighs
FEATURED_WIDTH = 1560
MAX_INLINE_WIDTH = 2000
MD_IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
HTML_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def slugify(value):
    """Jekyll Utils.slugify, default mode."""
    s = str(value).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_config():
    with io.open(os.path.join(ROOT, "_config.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def predict_url(fm, slug, cfg):
    """Jekyll: permalink 'pretty' == /:categories/:year/:month/:day/:title/"""
    cats = fm.get("categories") or []
    if isinstance(cats, str):
        cats = [c.strip() for c in cats.split()] if " " in cats else [cats]
    date = fm.get("date")
    if isinstance(date, str):
        date = datetime.datetime.strptime(date.strip()[:10], "%Y-%m-%d").date()
    elif isinstance(date, datetime.datetime):
        date = date.date()
    parts = [slugify(c) for c in cats if str(c).strip()]
    if date:
        parts += ["%04d" % date.year, "%02d" % date.month, "%02d" % date.day]
    parts.append(slug)
    permalink = cfg.get("permalink", "pretty")
    if permalink == "pretty":
        return "/" + "/".join(parts) + "/"
    return "/" + "/".join(parts) + ".html"


def image_refs(fm, body):
    refs = []
    featured = (fm.get("featured_image") or "").strip()
    if featured:
        refs.append(("featured_image", featured))
    recipe = fm.get("recipe") or {}
    blob = body + "\n" + str(recipe.get("ingredients_markdown", "")) + "\n" + str(recipe.get("directions_markdown", ""))
    for m in MD_IMG.finditer(blob):
        refs.append(("body", m.group(1)))
    for m in HTML_IMG.finditer(blob):
        refs.append(("body", m.group(1)))
    out, seen = [], set()
    for kind, ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        out.append((kind, ref))
    return out


def check_image(ref, kind, strict):
    """-> (errors, warnings) for one reference."""
    errs, warns = [], []
    path = ref if ref.startswith("/") else "/" + ref
    local = os.path.join(ROOT, path.lstrip("/"))
    if re.match(r"^(https?:)?//", ref):
        return errs, warns
    if not os.path.exists(local):
        errs.append("%s image missing on disk: %s" % (kind, ref))
        return errs, warns
    size = os.path.getsize(local)
    if size > MAX_IMAGE_BYTES:
        errs.append("%s image %s is %.0f KB (> %d KB) - compress before committing" % (kind, ref, size / 1024.0, MAX_IMAGE_BYTES / 1024))
    elif size > TARGET_IMAGE_BYTES:
        warns.append("%s image %s is %.0f KB (> %d KB target) - run scripts/compress_image.py" % (kind, ref, size / 1024.0, TARGET_IMAGE_BYTES / 1024))
    if Image is not None and local.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        try:
            w, h = Image.open(local).size
            if w > MAX_INLINE_WIDTH:
                warns.append("%s image %s is %dx%d - export at %dpx wide" % (kind, ref, w, h, FEATURED_WIDTH))
            elif kind == "featured_image" and abs(w - FEATURED_WIDTH) > 40:
                warns.append("featured_image %s is %dpx wide (target %dpx)" % (ref, w, FEATURED_WIDTH))
        except Exception as exc:  # pragma: no cover
            warns.append("%s image unreadable: %s (%s)" % (kind, ref, exc))
    return errs, warns


def check_post(path, cfg, strict):
    name = os.path.basename(path)
    errs, warns = [], []
    m = POST_FILENAME.match(name)
    if not m:
        # Not a post. Jekyll ignores anything in _posts/ without a date prefix,
        # so this is dead weight (or the _defaults template), not a build error.
        return [], ["%s is ignored by Jekyll (no YYYY-MM-DD- prefix) - dead file, not published" % name], None
    date_from_name, slug = m.group(0)[:10], m.group(4)
    raw = io.open(path, encoding="utf-8").read()

    jm = JEKYLL_FRONT_MATTER.match(raw)
    if not jm:
        return ([
            "no valid front matter close: Jekyll's regex needs a line that is exactly '---' "
            "at column 0 (found an indented or missing one). Post renders with EMPTY front "
            "matter - raw YAML leaks into the body, no recipe card, no category URL."
        ], warns, None)
    try:
        fm = yaml.safe_load(jm.group(1).replace("---", "", 1)) or {}
    except yaml.YAMLError as exc:
        return ["front matter is not valid YAML: %s" % exc], warns, None
    if not isinstance(fm, dict):
        return ["front matter did not parse into a mapping"], warns, None

    body = raw[jm.end():]

    for key in CORE_KEYS:
        if fm.get(key) in (None, "", [], {}):
            errs.append("missing required key: %s" % key)
    recipe = fm.get("recipe") or {}
    if not isinstance(recipe, dict) or not recipe:
        errs.append("missing required key: recipe (mapping)")
        recipe = {}
    for key in RECIPE_KEYS:
        if not str(recipe.get(key) or "").strip():
            errs.append("missing required recipe.%s" % key)
    for key in RECIPE_SOFT:
        if not str(recipe.get(key) or "").strip():
            warns.append("recipe.%s is blank - the recipe card prints an empty slot" % key)
    for key in SOFT_KEYS:
        if not str(fm.get(key) or "").strip():
            warns.append("featured_image is blank - blank tile on /recipes/")

    cats = fm.get("categories") or []
    if isinstance(cats, str):
        cats = [cats]
    for c in cats:
        if c in LEGACY_SINGULAR:
            warns.append("category %r is legacy singular - target vocabulary is %r (URL would change)" % (c, LEGACY_SINGULAR[c]))
        elif c not in CANONICAL_CATEGORIES:
            errs.append("category %r is not in the canonical list %s" % (c, sorted(CANONICAL_CATEGORIES)))

    d = fm.get("date")
    if isinstance(d, str):
        try:
            d = datetime.datetime.strptime(d.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            errs.append("date is not YYYY-MM-DD: %r" % fm.get("date"))
            d = None
    elif isinstance(d, datetime.datetime):
        d = d.date()
    if isinstance(d, datetime.date) and d > datetime.date.today():
        warns.append("date %s is in the future - Jekyll will not publish it yet" % d)

    for kind, ref in image_refs(fm, body):
        e, w = check_image(ref, kind, strict)
        errs += e
        warns += w

    url = predict_url(fm, slug, cfg)
    if strict:
        errs += warns
        warns = []
    return errs, warns, {"file": os.path.relpath(path, ROOT), "title": fm.get("title"), "url": url,
                         "categories": cats, "date": str(d) if d else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors (use on a new post before publishing)")
    ap.add_argument("--post", help="validate a single post file instead of every post")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    posts_dir = os.path.join(ROOT, "_posts")
    if args.post:
        paths = [args.post if os.path.isabs(args.post) else os.path.join(ROOT, args.post)]
    else:
        paths = [os.path.join(posts_dir, f) for f in sorted(os.listdir(posts_dir)) if os.path.isfile(os.path.join(posts_dir, f))]

    results, bad = [], 0
    for p in paths:
        errs, warns, info = check_post(p, cfg, args.strict)
        if errs:
            bad += 1
        results.append({"file": os.path.relpath(p, ROOT), "errors": errs, "warnings": warns, "info": info})

    if args.json:
        print(json.dumps({"config": {"permalink": cfg.get("permalink"), "url": cfg.get("url")}, "results": results}, indent=2))
    else:
        for r in results:
            if r["errors"]:
                print("FAIL  %s" % r["file"])
            elif r["info"]:
                print("OK    %s" % r["info"]["file"])
                print("      title: %s" % r["info"]["title"])
                print("      published URL: %s" % r["info"]["url"])
            else:
                print("SKIP  %s" % r["file"])
            for e in r["errors"]:
                print("      ERROR  %s" % e)
            for w in r["warnings"]:
                print("      warn   %s" % w)
            print("")
        print("%d file(s) checked, %d with errors" % (len(results), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
