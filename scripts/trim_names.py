#!/usr/bin/env python3
"""Trim bookmark names to short essentials (helper for Phase 3).

Usage:
  python trim_names.py --in merged.txt --out trimmed.txt [--max 32]

Input: lines of  <name> | <url>  (the MERGED section of dump_bookmarks.py
output works as-is; other lines pass through untouched).
Output: the same lines with the name trimmed. Read-only on everything else.

Rules (from SKILL.md Phase 3):
- strip page-title junk: a trailing "| Site", "- Home", "— Login", etc.
- strip "(3)" notification counts and surrounding whitespace
- cap at --max characters (default 32), cutting at a word boundary
- two bookmarks never share a name: later duplicates get a numeric suffix
  ("Router", "Router (2)") so nothing becomes ambiguous
- a name that trims to nothing falls back to the URL host
Judgment calls (what the "essential" part of a title is) stay with the agent;
this only does the mechanical part.
"""
import argparse
import re
from urllib.parse import urlsplit

DEFAULT_MAX = 32
# separators that split a page title into "thing | site" parts
SEPARATORS = re.compile(r"\s+[|–—·:>»-]+\s+")
NOTIF_COUNT = re.compile(r"^\(\d+\)\s*|\s*\(\d+\)$")
# tail words that carry no identity on their own
JUNK_TAILS = {"home", "homepage", "login", "log in", "sign in", "signin", "welcome",
              "official site", "official website", "dashboard", "index"}


def _host_label(url):
    host = (urlsplit(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host or "link"


def trim_name(name, url="", max_len=DEFAULT_MAX):
    """Return the shortest still-identifying form of `name`."""
    s = (name or "").strip()
    s = NOTIF_COUNT.sub("", s).strip()
    parts = [p.strip() for p in SEPARATORS.split(s) if p.strip()]
    # drop junk tails like "Home" / "Login" when something better remains
    while len(parts) > 1 and parts[-1].lower() in JUNK_TAILS:
        parts.pop()
    # drop a trailing part that is just the site name repeated in the host
    if len(parts) > 1 and url:
        host = _host_label(url).split(".")[0]
        if parts[-1].lower().replace(" ", "") == host:
            parts.pop()
    s = parts[0] if parts else ""
    s = re.sub(r"\s+", " ", s).strip(" -|:")
    if not s:
        s = _host_label(url)
    if len(s) > max_len:
        cut = s[:max_len]
        if " " in cut and len(cut.rsplit(" ", 1)[0]) >= max_len // 2:
            cut = cut.rsplit(" ", 1)[0]
        s = cut.rstrip(" -|:,")
    return s


def disambiguate(names):
    """Make a list of names unique by appending ' (2)', ' (3)', ... to repeats."""
    seen = {}
    out = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen[key] = 1
            out.append(n)
            continue
        while True:
            seen[key] += 1
            cand = f"{n} ({seen[key]})"
            if cand.lower() not in seen:
                seen[cand.lower()] = 1
                out.append(cand)
                break
    return out


def trim_lines(lines, max_len=DEFAULT_MAX):
    """Trim the name field of every 'name | url' line; other lines pass through."""
    idx, names, urls = [], [], []
    for i, line in enumerate(lines):
        body = line.strip()
        if " | " in body and body.rsplit(" | ", 1)[1].startswith(("http://", "https://")):
            name, url = body.rsplit(" | ", 1)
            idx.append(i)
            names.append(trim_name(name, url, max_len))
            urls.append(url)
    uniq = disambiguate(names)
    out = list(lines)
    for i, n, u in zip(idx, uniq, urls):
        indent = out[i][:len(out[i]) - len(out[i].lstrip())]
        out[i] = f"{indent}{n} | {u}"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile", required=True)
    ap.add_argument("--max", type=int, default=DEFAULT_MAX, help="max name length (default 32)")
    args = ap.parse_args()
    with open(args.infile, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = trim_lines(lines, args.max)
    with open(args.outfile, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"wrote {args.outfile}  ({sum(1 for a, b in zip(lines, out) if a != b)} names trimmed)")


if __name__ == "__main__":
    main()
