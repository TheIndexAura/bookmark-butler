"""Network is fully mocked: urllib.request.urlopen is replaced in every test.
A guard fixture makes any real socket connection fail loudly."""
import io
import socket
import sys
import urllib.error
import urllib.request

import pytest

import check_links


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("test tried to open a real network connection")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def install(monkeypatch, table):
    """table: url -> int status | exception | list of those (consumed in order).
    Returns the list of URLs requested, with timeouts seen."""
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        url = req.full_url
        calls.append((url, timeout))
        item = table[url]
        if isinstance(item, list):
            item = item.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeResponse(item)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


# ---------- classification ----------

def test_ok_auth_dead_codes(monkeypatch):
    install(monkeypatch, {
        "https://a.example/": 200,
        "https://b.example/": http_error(403),
        "https://c.example/": http_error(404),
        "https://d.example/": http_error(500),
    })
    assert check_links.fetch("https://a.example/") == "OK 200"
    assert check_links.fetch("https://b.example/") == "AUTH 403"
    assert check_links.fetch("https://c.example/") == "DEAD 404"
    assert check_links.fetch("https://d.example/") == "OK 500"


def test_dns_failure_is_dead_and_not_retried(monkeypatch):
    err = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    calls = install(monkeypatch, {"https://gone.invalid/": urllib.error.URLError(err)})
    assert check_links.fetch("https://gone.invalid/") == "DEAD DNS"
    assert len(calls) == 1


def test_temporary_dns_failure_is_uncertain_not_dead(monkeypatch):
    err = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
    install(monkeypatch, {"https://flaky.example/": urllib.error.URLError(err)})
    status = check_links.fetch("https://flaky.example/")
    assert status.startswith("ERR")
    assert "DEAD" not in status


def test_timeout_wrapped_in_urlerror_is_timeout(monkeypatch):
    # urllib usually wraps socket.timeout in URLError; before the fix this
    # came out as "ERR timed out" instead of TIMEOUT
    install(monkeypatch, {"https://slow.example/": urllib.error.URLError(socket.timeout("timed out"))})
    assert check_links.fetch("https://slow.example/") == "TIMEOUT"


def test_bare_timeout_is_timeout(monkeypatch):
    install(monkeypatch, {"https://slow.example/": TimeoutError("timed out")})
    assert check_links.fetch("https://slow.example/") == "TIMEOUT"


def test_refused_is_a_status_not_a_crash(monkeypatch):
    install(monkeypatch, {
        "https://r1.example/": urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
        "https://r2.example/": ConnectionResetError(104, "Connection reset by peer"),
        "https://r3.example/": urllib.error.URLError("[Errno 111] Connection refused"),
    })
    for u in ("https://r1.example/", "https://r2.example/", "https://r3.example/"):
        assert check_links.fetch(u) == "REFUSED", u


def test_unknown_exception_is_err_not_crash(monkeypatch):
    install(monkeypatch, {"https://weird.example/": ValueError("something odd")})
    assert check_links.fetch("https://weird.example/") == "ERR something odd"


# ---------- timeout + retry ----------

def test_timeout_is_passed_to_urlopen(monkeypatch):
    calls = install(monkeypatch, {"https://a.example/": 200})
    check_links.fetch("https://a.example/", timeout=3.5)
    assert calls == [("https://a.example/", 3.5)]


def test_network_error_retried_once_then_succeeds(monkeypatch):
    calls = install(monkeypatch, {"https://a.example/": [ConnectionResetError(), 200]})
    assert check_links.fetch("https://a.example/") == "OK 200"
    assert len(calls) == 2


def test_network_error_retried_once_then_reported(monkeypatch):
    calls = install(monkeypatch, {"https://a.example/": [TimeoutError(), TimeoutError(), 200]})
    assert check_links.fetch("https://a.example/") == "TIMEOUT"
    assert len(calls) == 2  # default retries=1 -> exactly two attempts


def test_http_answers_not_retried(monkeypatch):
    calls = install(monkeypatch, {"https://a.example/": [http_error(404), 200]})
    assert check_links.fetch("https://a.example/") == "DEAD 404"
    assert len(calls) == 1


def test_retries_zero_means_single_attempt(monkeypatch):
    calls = install(monkeypatch, {"https://a.example/": [TimeoutError(), 200]})
    assert check_links.fetch("https://a.example/", retries=0) == "TIMEOUT"
    assert len(calls) == 1


# ---------- check(): local skip + root repair ----------

@pytest.mark.parametrize("url", [
    "http://192.168.1.1/", "http://10.0.0.5/admin", "http://localhost:8080/",
    "http://router/", "http://nas.local/", "http://printer.lan/", "http://[::1]/",
    "http://100.64.1.1/", "http://169.254.1.1/",
])
def test_local_urls_never_touch_network(monkeypatch, url):
    calls = install(monkeypatch, {})
    assert check_links.check(url) == (url, "LOCAL")
    assert calls == []


def test_public_ip_is_not_local():
    assert not check_links.is_local("https://8.8.8.8/")
    assert not check_links.is_local("https://example.com/")


def test_non_http_skipped(monkeypatch):
    calls = install(monkeypatch, {})
    assert check_links.check("ftp://files.example.com/") == ("ftp://files.example.com/", "SKIP non-http")
    assert calls == []


def test_dead_deep_link_with_live_root(monkeypatch):
    install(monkeypatch, {
        "https://jobs.example.org/posting/2023/123": http_error(404),
        "https://jobs.example.org/": 200,
    })
    _, status = check_links.check("https://jobs.example.org/posting/2023/123")
    assert status == "DEAD 404\tROOT-OK https://jobs.example.org/"


def test_dead_deep_link_with_auth_walled_root_is_repairable(monkeypatch):
    install(monkeypatch, {
        "https://x.example/deep": http_error(410),
        "https://x.example/": http_error(403),
    })
    _, status = check_links.check("https://x.example/deep")
    assert status == "DEAD 410\tROOT-OK https://x.example/"


def test_dead_deep_link_with_dead_root(monkeypatch):
    install(monkeypatch, {
        "https://x.example/deep": http_error(404),
        "https://x.example/": http_error(404),
    })
    _, status = check_links.check("https://x.example/deep")
    assert status == "DEAD 404\tROOT-DEAD"


def test_dead_deep_link_with_refusing_root_is_uncertain_not_dead(monkeypatch):
    install(monkeypatch, {
        "https://x.example/deep": http_error(404),
        "https://x.example/": [ConnectionRefusedError(), ConnectionRefusedError()],
    })
    _, status = check_links.check("https://x.example/deep")
    assert status == "DEAD 404\tROOT-UNCERTAIN REFUSED"
    assert "ROOT-DEAD" not in status


def test_dead_root_url_itself_gets_no_root_tag(monkeypatch):
    install(monkeypatch, {"https://x.example/": http_error(404)})
    assert check_links.check("https://x.example/") == ("https://x.example/", "DEAD 404")


# ---------- main(): file in, file out ----------

def test_main_end_to_end(monkeypatch, tmp_path, fixtures, capsys):
    calls = install(monkeypatch, {
        "https://github.com/": 200,
        "https://jira.example.com/login": http_error(401),
        "https://jobs.example.org/posting/2023/123": http_error(404),
        "https://jobs.example.org/": 200,
        "https://gone.invalid/page": urllib.error.URLError(
            socket.gaierror(socket.EAI_NONAME, "Name or service not known")),
        "https://gone.invalid/": urllib.error.URLError(
            socket.gaierror(socket.EAI_NONAME, "Name or service not known")),
        "https://slow.example.com/": TimeoutError(),
        "https://refuses.example.com/": ConnectionRefusedError(),
    })
    out = tmp_path / "results.txt"
    monkeypatch.setattr(sys, "argv", ["check_links.py", "--in", f"{fixtures}/urls.txt",
                                      "--out", str(out), "--workers", "2", "--timeout", "2"])
    check_links.main()
    # each line is STATUS[<TAB>ROOT-TAG]<TAB>URL; map url -> everything before it
    results = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        results[parts[-1]] = "\t".join(parts[:-1])
    assert results["https://github.com/"] == "OK 200"
    assert results["https://jira.example.com/login"] == "AUTH 401"
    assert results["http://192.168.1.1/"] == "LOCAL"
    assert results["https://jobs.example.org/posting/2023/123"] == "DEAD 404\tROOT-OK https://jobs.example.org/"
    assert results["https://gone.invalid/page"] == "DEAD DNS\tROOT-DEAD"
    assert results["https://slow.example.com/"] == "TIMEOUT"
    assert results["https://refuses.example.com/"] == "REFUSED"
    assert "ftp://files.example.com/" not in results        # non-http dropped on read
    assert len(results) == 7                                 # duplicate github line collapsed
    assert all(t == 2 for _, t in calls)                     # --timeout reached urlopen
    assert not any(u.startswith("http://192.168") for u, _ in calls)
    summary = capsys.readouterr().out
    assert "checked 7 urls" in summary
    assert "REFUSED=1" in summary and "TIMEOUT=1" in summary and "DEAD=2" in summary
