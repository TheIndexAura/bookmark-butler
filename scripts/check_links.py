#!/usr/bin/env python3
"""Check bookmark URLs for life signs. Read-only; never deletes anything.

Usage:
  python check_links.py --in urls.txt --out results.txt

Input: one URL per line (anything after a tab or ' | ' is ignored).
Output lines:  STATUS<TAB>URL
  OK n      alive (HTTP 2xx/3xx)
  AUTH n    login/bot wall (401 403 405 429 503 999) -> ALIVE, keep
  LOCAL     LAN / localhost / private host -> untestable, keep
  TIMEOUT   no answer in time (after one retry) -> uncertain, keep
  REFUSED   the host refused/reset the connection (after one retry) -> uncertain, keep
  DEAD n    404/410 or DNS failure -> candidate for root-repair, then review
  ERR msg   other failure -> uncertain, keep

Every request has a timeout (--timeout, default 12s). A TIMEOUT, REFUSED or
ERR result is retried once (--retries, default 1) before it is reported; HTTP
answers and hard DNS failures are not retried. A site that refuses is a
status line like any other - never a crash.

For every DEAD deep link the checker also tests the root domain and appends
  ROOT-OK <root>   or   ROOT-DEAD   or   ROOT-UNCERTAIN <status>
so the caller can repair instead of delete. ROOT-UNCERTAIN means the root
timed out / refused / errored: do not propose deletion from it.
"""
import argparse
import errno
import http.client
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


DEFAULT_TIMEOUT = 12
DEFAULT_RETRIES = 1
# socket.gaierror codes that mean "this name does not exist" (hard DNS dead)
DNS_DEAD_ERRNOS = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
# reasons that mean "could not reach the host at all" -> REFUSED (keep)
REFUSED_ERRNOS = {errno.ECONNREFUSED, errno.ECONNRESET, errno.ECONNABORTED,
                  errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EPIPE}
RETRYABLE_PREFIXES = ("TIMEOUT", "REFUSED", "ERR")


def _classify_exception(e):
    """Map a low-level failure to a status string. Never raises."""
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
        e = e.reason if isinstance(e.reason, BaseException) else e
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "TIMEOUT"
    if isinstance(e, socket.gaierror):
        if e.errno in DNS_DEAD_ERRNOS:
            return "DEAD DNS"
        return f"ERR dns {str(e)[:36]}"  # e.g. EAI_AGAIN: temporary, not dead
    if isinstance(e, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError,
                      http.client.RemoteDisconnected)):
        return "REFUSED"
    if isinstance(e, OSError) and e.errno in REFUSED_ERRNOS:
        return "REFUSED"
    msg = str(e)
    if isinstance(e, urllib.error.URLError):
        msg = str(e.reason)
        if any(k in msg for k in ("getaddrinfo", "Name or service", "nodename")):
            return "DEAD DNS"
        if "refused" in msg.lower() or "reset by peer" in msg.lower():
            return "REFUSED"
        if "timed out" in msg.lower():
            return "TIMEOUT"
    return f"ERR {msg[:40]}"


def fetch_once(url, timeout=DEFAULT_TIMEOUT):
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
    except Exception as e:  # noqa: BLE001 - report, don't crash the batch
        return _classify_exception(e)


def fetch(url, timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES):
    """Fetch with a timeout; retry network-level failures `retries` times.
    HTTP answers (OK/AUTH/DEAD n) and hard DNS failures are final on first try."""
    status = fetch_once(url, timeout=timeout)
    for _ in range(max(0, retries)):
        if not status.startswith(RETRYABLE_PREFIXES):
            break
        status = fetch_once(url, timeout=timeout)
    return status


def check(url, timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES):
    if not url.startswith(("http://", "https://")):
        return url, "SKIP non-http"
    if is_local(url):
        return url, "LOCAL"
    status = fetch(url, timeout=timeout, retries=retries)
    if status.startswith("DEAD"):
        s = urlsplit(url)
        root = f"{s.scheme}://{s.netloc}/"
        if root != url:
            root_status = fetch(root, timeout=timeout, retries=retries)
            kind = root_status.split()[0]
            if kind in ("OK", "AUTH"):
                tag = f"ROOT-OK {root}"
            elif kind == "DEAD":
                tag = "ROOT-DEAD"
            else:  # TIMEOUT / REFUSED / ERR: unknown, never a delete candidate
                tag = f"ROOT-UNCERTAIN {root_status}"
            status = f"{status}\t{tag}"
    return url, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile", required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help="seconds to wait per request (default 12)")
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                    help="extra attempts after a network-level failure (default 1)")
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

    def run(url):
        return check(url, timeout=args.timeout, retries=args.retries)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, urls))
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
