#!/usr/bin/env python3
"""Check bookmark URLs for life signs. Read-only; never deletes anything.

Usage:
  python check_links.py --in urls.txt --out results.txt

Input: one URL per line (anything after a tab or ' | ' is ignored).
Output lines:  STATUS<TAB>URL
  OK n      alive (HTTP 2xx/3xx)
  AUTH n    login/bot wall (401 403 405 429 503 999) -> ALIVE, keep
  LOCAL     LAN / localhost / private host -> untestable, keep
  TIMEOUT   no answer in time -> uncertain, keep
  DEAD n    404/410 or DNS failure -> candidate for root-repair, then review
  ERR msg   other failure -> uncertain, keep

For every DEAD deep link the checker also tests the root domain and appends
  ROOT-OK <root>   or   ROOT-DEAD
so the caller can repair instead of delete.
"""
import argparse
import ipaddress
import socket
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
ALIVE_CODES = {401, 403, 405, 429, 503, 999}
DEAD_CODES = {404, 410}

# NOTE: TLS verification is intentionally disabled — this is a liveness check,
# not a security check, and self-signed LAN/router certs would false-flag as
# dead. No credentials are ever sent.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

CGNAT = ipaddress.ip_network("100.64.0.0/10")


def is_local(url):
    """True for anything an internet-side check cannot judge: private/loopback/
    link-local/CGNAT addresses, .local-style suffixes, and unqualified
    hostnames (no dot = LAN name like 'router' or 'nas')."""
    host = urlsplit(url).hostname or ""
    if not host:
        return True
    if host == "localhost" or host.endswith(
            (".local", ".internal", ".lan", ".home", ".localdomain", ".home.arpa", ".arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or (ip.version == 4 and ip in CGNAT))
    except ValueError:
        pass  # not an IP literal
    if "." not in host:
        return True  # unqualified hostname -> LAN name
    return False


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return f"OK {r.status}"
    except urllib.error.HTTPError as e:
        if e.code in ALIVE_CODES:
            return f"AUTH {e.code}"
        if e.code in DEAD_CODES:
            return f"DEAD {e.code}"
        return f"OK {e.code}"  # other codes = server answered = alive
    except (socket.timeout, TimeoutError):
        return "TIMEOUT"
    except urllib.error.URLError as e:
        msg = str(e.reason)
        if any(k in msg for k in ("getaddrinfo", "Name or service", "nodename")):
            return "DEAD DNS"
        return f"ERR {msg[:40]}"
    except Exception as e:  # noqa: BLE001 - report, don't crash the batch
        return f"ERR {str(e)[:40]}"


def check(url):
    if not url.startswith(("http://", "https://")):
        return url, "SKIP non-http"
    if is_local(url):
        return url, "LOCAL"
    status = fetch(url)
    if status.startswith("DEAD"):
        s = urlsplit(url)
        root = f"{s.scheme}://{s.netloc}/"
        if root != url:
            root_status = fetch(root)
            tag = f"ROOT-OK {root}" if root_status.split()[0] in ("OK", "AUTH") else "ROOT-DEAD"
            status = f"{status}\t{tag}"
    return url, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile", required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    urls = []
    with open(args.infile, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            for sep in ("\t", " | "):
                if sep in line:
                    line = line.split(sep)[-1].strip()
            if line.startswith(("http://", "https://")) and line not in urls:
                urls.append(line)

    results = list(ThreadPoolExecutor(max_workers=args.workers).map(check, urls))
    with open(args.outfile, "w", encoding="utf-8") as f:
        for url, status in results:
            f.write(f"{status}\t{url}\n")

    summary = {}
    for _, status in results:
        key = status.split()[0]
        summary[key] = summary.get(key, 0) + 1
    print(f"checked {len(urls)} urls -> {args.outfile}")
    print("summary:", ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))


if __name__ == "__main__":
    main()
