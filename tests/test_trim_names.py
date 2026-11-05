import sys

import pytest

import trim_names
from trim_names import disambiguate, trim_lines, trim_name


@pytest.mark.parametrize("raw,url,expected", [
    ("GitHub - Where the world builds software", "https://github.com/", "GitHub"),
    ("My Account Login - Pay Bills Online & Manage Your Service | Big Bank",
     "https://bigbank.example/", "My Account Login"),
    ("Jira - Login", "https://jira.example.com/login", "Jira"),
    ("(3) News", "https://news.example.net/", "News"),
    ("News (3)", "https://news.example.net/", "News"),
    ("Python Docs | Home", "https://docs.python.org/", "Python Docs"),
    ("Welcome", "https://www.acme.example/", "Welcome"),           # single part kept
    ("   ", "https://www.acme.example/", "acme.example"),         # empty -> host
    ("Stack Overflow - Where Developers Learn, Share, & Build Careers",
     "https://stackoverflow.com/", "Stack Overflow"),
    ("Reddit · r/python", "https://reddit.com/r/python", "Reddit"),
])
def test_trim_rules(raw, url, expected):
    assert trim_name(raw, url) == expected


def test_length_cap_cuts_at_word_boundary():
    long = "A really quite long bookmark title that keeps going and going forever"
    out = trim_name(long, "https://x.example/")
    assert len(out) <= 32
    assert out == "A really quite long bookmark"
    assert len(trim_name(long, "https://x.example/", max_len=10)) <= 10


def test_no_spaces_hard_cut():
    assert trim_name("x" * 50, "https://x.example/") == "x" * 32


def test_disambiguate_never_repeats_a_name():
    out = disambiguate(["Router", "Router", "router", "Router (2)", "Mail"])
    assert len(set(n.lower() for n in out)) == len(out)
    assert out[0] == "Router" and out[-1] == "Mail"
    assert out[1] == "Router (2)"


def test_trim_lines_keeps_non_bookmark_lines_and_indent():
    lines = [
        "===== MERGED + DEDUPED (3 unique urls) =====",
        "  GitHub - Where the world builds software | https://github.com/",
        "  Jira - Login | https://jira.example.com/login",
        "  Jira - Home | https://jira.example.com/",
        "",
    ]
    out = trim_lines(lines)
    assert out[0] == lines[0] and out[-1] == ""
    assert out[1] == "  GitHub | https://github.com/"
    assert out[2] == "  Jira | https://jira.example.com/login"
    assert out[3] == "  Jira (2) | https://jira.example.com/"


def test_main_round_trip(monkeypatch, tmp_path, capsys):
    src = tmp_path / "in.txt"
    src.write_text("  A | B | https://a.example/\n  Thing (12) | https://t.example/\n", encoding="utf-8")
    dst = tmp_path / "out.txt"
    monkeypatch.setattr(sys, "argv", ["trim_names.py", "--in", str(src), "--out", str(dst)])
    trim_names.main()
    assert dst.read_text(encoding="utf-8") == "  A | https://a.example/\n  Thing | https://t.example/\n"
    assert "2 names trimmed" in capsys.readouterr().out
