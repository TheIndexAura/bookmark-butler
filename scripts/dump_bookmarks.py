#!/usr/bin/env python3
"""Dump and merge bookmarks from one or more Chromium-family profiles.

Usage:
  python dump_bookmarks.py --out merged.txt PROFILE_DIR [PROFILE_DIR ...]

Read-only. Output is UTF-8: one line per bookmark
  <folder path> | <name> | <url>
plus folder markers, then a deduped merged list at the end.
"""
import argparse
import json
import os
import sys


def walk(node, path):
    rows = []
    for ch in node.get("children", []):
        if ch.get("type") == "url":
            rows.append((path or "(top)", ch.get("name", ""), ch.get("url", "")))
        else:
            sub = f"{path}/{ch.get('name', '')}" if path else ch.get("name", "")
            rows.append((path or "(top)", f"[{ch.get('name', '')}]", "FOLDER"))
            rows += walk(ch, sub)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output text file (UTF-8)")
    ap.add_argument("profiles", nargs="+", help="profile directories containing a Bookmarks file")
    args = ap.parse_args()

    lines = []
    merged = {}  # url -> name (first seen wins)
    for pdir in args.profiles:
        fp = os.path.join(pdir, "Bookmarks")
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"SKIP {pdir}: {e}", file=sys.stderr)
            continue
        lines.append(f"\n===== PROFILE: {pdir} =====")
        roots = data.get("roots", {})
        for rk in ("bookmark_bar", "other", "synced"):
            if rk not in roots:
                continue
            rows = walk(roots[rk], "")
            if not rows:
                continue
            lines.append(f"--- root: {rk} ---")
            for loc, name, url in rows:
                lines.append(f"  {loc} | {name} | {url}")
                if url != "FOLDER" and url not in merged:
                    merged[url] = name

    lines.append(f"\n===== MERGED + DEDUPED ({len(merged)} unique urls) =====")
    for url, name in merged.items():
        lines.append(f"  {name} | {url}")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {args.out}  ({len(merged)} unique bookmarks)")


if __name__ == "__main__":
    main()
