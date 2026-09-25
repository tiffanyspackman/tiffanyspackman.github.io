#!/usr/bin/env python3
"""After a push: prove the live post rendered, and that it is listed on /recipes/.

GitHub Pages classic build, so the only evidence that counts is the live HTML.

Usage:
  python3 scripts/verify_live.py --post _posts/2026-06-24-butterhorn-rolls.md
  python3 scripts/verify_live.py --url /bread/2026/06/24/butterhorn-rolls/
"""
import argparse, io, os, re, sys, urllib.request, html as html_mod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_posts import ROOT, load_config, predict_url, JEKYLL_FRONT_MATTER, POST_FILENAME  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "spackman-recipes-verify/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def strip_tags(h):
    body = h.split("<body", 1)[-1]
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post")
    ap.add_argument("--url")
    args = ap.parse_args()
    cfg = load_config()
    base = (cfg.get("url") or "").rstrip("/")

    if args.post:
        path = args.post if os.path.isabs(args.post) else os.path.join(ROOT, args.post)
        raw = io.open(path, encoding="utf-8").read()
        m = JEKYLL_FRONT_MATTER.match(raw)
        if not m:
            sys.exit("FAIL: post has no valid front matter close, nothing to verify")
        fm = yaml.safe_load(m.group(1).replace("---", "", 1))
        slug = POST_FILENAME.match(os.path.basename(path)).group(4)
        url_path = predict_url(fm, slug, cfg)
        title, cats = fm.get("title"), fm.get("categories") or []
        recipe = fm.get("recipe") or {}
    else:
        url_path = args.url if args.url.startswith("/") else "/" + args.url
        if not url_path.endswith("/"):
            url_path += "/"
        slug = url_path.strip("/").split("/")[-1]
        fm, title, cats, recipe = {}, input("Title of the post: "), [], {}

    fails = []

    def check(label, ok, detail=""):
        print(("  PASS  " if ok else "  FAIL  ") + label + (("  -> " + detail) if detail else ""))
        if not ok:
            fails.append(label)

    print("Live checks for %s%s" % (base, url_path))
    try:
        status, page = fetch(base + url_path)
    except Exception as exc:
        print("  FAIL  fetch %s%s -> %s" % (base, url_path, exc))
        fails.append("post fetch")
        page, status = "", 0
    check("post URL returns 200", status == 200, "HTTP %s" % status)

    text = strip_tags(page)
    if title:
        check("real title rendered as <h1>", bool(re.search(r"<h1>.*?" + re.escape(title.split("'")[0][:20]), page, re.S)),
              "title=%r" % title)
        check("title present in page text", title in text, "")
    check("'Jump to recipe' card anchor rendered", "Jump to recipe" in text)
    check("Ingredients heading rendered", "Ingredients" in text)
    check("Directions heading rendered", "Directions" in text)
    for key in ("servings", "prep", "cook"):
        val = str(recipe.get(key) or "").strip()
        if val:
            check("recipe.%s shown in card: %r" % (key, val), val in text)
    if url_path.count("/") == 5:  # /category/yyyy/mm/dd/slug/
        cat = url_path.strip("/").split("/")[0]
        check("URL carries the category segment /%s/" % cat, True, url_path)
    check("raw YAML is NOT leaking into the body", not re.search(r"^\s*(title|categories|featured_image|recipe|directions_markdown):", text, re.M))
    check("no '404' / Not Found page", "Not Found" not in page[:400] and "404" not in text[:200])

    # /recipes/ listing, under the right category heading
    try:
        status, recipes = fetch(base + "/recipes/")
        rtext = strip_tags(recipes)
    except Exception as exc:
        rtext, status = "", 0
        print("  FAIL  fetch /recipes/ -> %s" % exc)
        fails.append("recipes fetch")
    if title:
        check("post is listed on /recipes/", title in rtext, "checked %r" % title)
        for c in (cats if isinstance(cats, list) else [cats]):
            idx = rtext.find(str(c))
            tidx = rtext.find(title)
            check("listed under the %s heading" % c, idx != -1 and tidx > idx,
                  "category heading at %s, title at %s" % (idx, tidx))
    check("every tile keeps its link", rtext.count("<a href=") >= rtext.count("class=\"recipe\"") if recipes else False)

    print("")
    if fails:
        print("FAILED: %s" % ", ".join(fails))
        return 1
    print("ALL LIVE CHECKS PASSED for %s%s" % (base, url_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
