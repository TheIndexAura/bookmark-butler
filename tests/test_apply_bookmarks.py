import filecmp
import glob
import json
import os
import shutil
import sys

import pytest

import apply_bookmarks
from conftest import load_json

PLAN = {
    "pinned_folders": ["Work"],
    "loose": [["GitHub", "https://github.com/"]],
    "folders": {
        "Work": [["Jira", "https://jira.example.com/login"], ["Router", "http://192.168.1.1/"]],
        "Reading": [["Python Docs", "https://docs.python.org/3/"], ["News", "https://news.example.net/"]],
        "Jobs": [["Jobs Site", "https://jobs.example.org/"]],
    },
    "folder_order": ["Reading"],      # Jobs is deliberately omitted -> orphan, appended
    "sort_links": "alpha",
    "sort_folders": "keep",
    "expected_urls": [
        "https://github.com/", "https://jira.example.com/login", "http://192.168.1.1/",
        "https://docs.python.org/3/", "https://news.example.net/", "https://jobs.example.org/",
    ],
}


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(PLAN), encoding="utf-8")
    return str(p)


@pytest.fixture
def browser_closed(monkeypatch):
    monkeypatch.setattr(apply_bookmarks, "browser_running", lambda: [])


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["apply_bookmarks.py", *argv])
    apply_bookmarks.main()


def bar_layout(path):
    bar = load_json(os.path.join(path, "Bookmarks"))["roots"]["bookmark_bar"]["children"]
    return [(c["name"], [k["name"] for k in c["children"]]) if c["type"] == "folder"
            else c["url"] for c in bar]


# ---------- validate_plan ----------

def test_valid_plan_reports_orphans_only():
    errors, orphans = apply_bookmarks.validate_plan(PLAN)
    assert errors == []
    assert orphans == ["Jobs"]


def test_missing_expected_urls_blocks_unless_skipped():
    plan = {**PLAN, "expected_urls": []}
    errors, _ = apply_bookmarks.validate_plan(plan)
    assert any("expected_urls" in e for e in errors)
    errors, _ = apply_bookmarks.validate_plan(plan, skip_url_guard=True)
    assert errors == []


def test_expected_url_absent_from_plan_is_an_error():
    plan = {**PLAN, "expected_urls": PLAN["expected_urls"] + ["https://lost.example/"]}
    errors, _ = apply_bookmarks.validate_plan(plan)
    assert any("1 expected URL(s) absent" in e for e in errors)


def test_duplicate_urls_and_unknown_folder_names_are_errors():
    plan = json.loads(json.dumps(PLAN))
    plan["loose"].append(["GitHub again", "https://github.com/"])
    plan["folder_order"].append("Ghost")
    errors, _ = apply_bookmarks.validate_plan(plan)
    assert any("duplicate URLs" in e for e in errors)
    assert any("Ghost" in e for e in errors)


# ---------- dry run ----------

def test_dry_run_writes_nothing(monkeypatch, profiles, plan_file, capsys):
    before = {p: open(os.path.join(p, "Bookmarks"), "rb").read() for p in profiles}
    run(monkeypatch, "--plan", plan_file, "--dry-run", *profiles)
    out = capsys.readouterr().out
    assert out.count("DRY-RUN") == 2
    assert "would write 6 links (3 folders)" in out
    for p in profiles:
        assert open(os.path.join(p, "Bookmarks"), "rb").read() == before[p]
        assert glob.glob(os.path.join(p, "Bookmarks.backup_*")) == []


def test_invalid_plan_exits_before_anything(monkeypatch, profiles, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**PLAN, "expected_urls": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        run(monkeypatch, "--plan", str(bad), *profiles)
    assert "PLAN INVALID" in str(ei.value)


# ---------- browser guard ----------

def test_refuses_when_browser_running(monkeypatch, profiles, plan_file):
    monkeypatch.setattr(apply_bookmarks, "browser_running", lambda: ["chrome"])
    with pytest.raises(SystemExit) as ei:
        run(monkeypatch, "--plan", plan_file, "--assume-closed", *profiles)
    assert "REFUSING" in str(ei.value) and "chrome" in str(ei.value)
    assert glob.glob(os.path.join(profiles[0], "Bookmarks.backup_*")) == []


def test_fails_closed_when_process_list_unreadable(monkeypatch, profiles, plan_file):
    def broken():
        raise RuntimeError("could not read process list")
    monkeypatch.setattr(apply_bookmarks, "browser_running", broken)
    with pytest.raises(SystemExit) as ei:
        run(monkeypatch, "--plan", plan_file, *profiles)
    assert "fail closed" in str(ei.value)
    # --assume-closed covers exactly this case
    run(monkeypatch, "--plan", plan_file, "--assume-closed", *profiles)
    assert glob.glob(os.path.join(profiles[0], "Bookmarks.backup_*"))


def test_browser_running_detects_names(monkeypatch):
    class R:
        stdout = "systemd\nGoogle Chrome Helper\nbash\n"
    monkeypatch.setattr(apply_bookmarks.subprocess, "run", lambda *a, **k: R())
    assert apply_bookmarks.browser_running() == ["chrome"]
    R.stdout = ""
    with pytest.raises(RuntimeError):
        apply_bookmarks.browser_running()


# ---------- apply + backup + undo ----------

def test_apply_builds_bar_and_clears_other_roots(monkeypatch, profiles, plan_file, browser_closed, capsys):
    run(monkeypatch, "--plan", plan_file, *profiles)
    out = capsys.readouterr().out
    assert "appended at end: ['Jobs']" in out
    for p in profiles:
        layout = bar_layout(p)
        assert layout == [
            ("Work", ["Jira", "Router"]),           # pinned first, links alpha
            "https://github.com/",                  # loose
            ("Reading", ["News", "Python Docs"]),   # folder_order
            ("Jobs", ["Jobs Site"]),                # orphan appended, never dropped
        ]
        data = load_json(os.path.join(p, "Bookmarks"))
        assert data["roots"]["other"]["children"] == []
        assert "checksum" not in data
        assert "WARNING" not in out
    # synced existed only in profile_a and is cleared too
    assert load_json(os.path.join(profiles[0], "Bookmarks"))["roots"]["synced"]["children"] == []


def test_every_expected_url_survives(monkeypatch, profiles, plan_file, browser_closed):
    run(monkeypatch, "--plan", plan_file, *profiles)
    for p in profiles:
        data = load_json(os.path.join(p, "Bookmarks"))
        urls = set()
        for c in data["roots"]["bookmark_bar"]["children"]:
            urls |= {c["url"]} if c["type"] == "url" else {k["url"] for k in c["children"]}
        assert urls == set(PLAN["expected_urls"])
        ids = [c["id"] for c in data["roots"]["bookmark_bar"]["children"]]
        assert len(ids) == len(set(ids))


def test_backup_then_undo_restores_original(monkeypatch, profiles, plan_file, browser_closed, capsys):
    originals = {p: open(os.path.join(p, "Bookmarks"), "rb").read() for p in profiles}
    run(monkeypatch, "--plan", plan_file, *profiles)
    out = capsys.readouterr().out
    for p in profiles:
        live = os.path.join(p, "Bookmarks")
        backups = glob.glob(os.path.join(p, "Bookmarks.backup_*"))
        assert len(backups) == 1
        bak = backups[0]
        assert f"backup: {bak}" in out                      # path is printed for the user
        assert open(bak, "rb").read() == originals[p]       # backup is byte-identical to before
        assert open(live, "rb").read() != originals[p]      # live file really changed
        # undo = the documented one-file copy
        shutil.copy(bak, live)
        assert open(live, "rb").read() == originals[p]
        assert filecmp.cmp(bak, live, shallow=False)
        assert not glob.glob(os.path.join(p, ".bb_tmp_*"))  # no temp leftovers


def test_second_run_makes_second_backup(monkeypatch, profiles, plan_file, browser_closed):
    monkeypatch.setattr(apply_bookmarks.time, "strftime", lambda fmt: "20250101_000000")
    run(monkeypatch, "--plan", plan_file, profiles[0])
    monkeypatch.setattr(apply_bookmarks.time, "strftime", lambda fmt: "20250101_000001")
    run(monkeypatch, "--plan", plan_file, profiles[0])
    assert len(glob.glob(os.path.join(profiles[0], "Bookmarks.backup_*"))) == 2


def test_profile_without_bookmarks_is_skipped(monkeypatch, profiles, plan_file, browser_closed, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    run(monkeypatch, "--plan", plan_file, str(empty), profiles[0])
    err = capsys.readouterr().err
    assert "SKIP" in err and "no Bookmarks file" in err
    assert glob.glob(os.path.join(profiles[0], "Bookmarks.backup_*"))


def test_atomic_write_leaves_no_temp_on_failure(tmp_path):
    target = tmp_path / "Bookmarks"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(TypeError):
        apply_bookmarks.atomic_write_json(str(target), {"x": object()})  # not serialisable
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["Bookmarks"]


def test_usage_sort_uses_history_scores():
    scores = {"github.com": 50, "news.example.net": 5}
    plan = {**PLAN, "sort_links": "usage", "sort_folders": "usage"}
    b = apply_bookmarks.Builder(plan, scores)
    kids = b.bar_children(["Jobs"])
    names = [k["name"] for k in kids]
    assert names[0] == "Work"                       # pinned stays first
    assert names.index("Reading") < names.index("Jobs")   # 5 > 0 usage
    reading = [k["name"] for k in kids[names.index("Reading")]["children"]]
    assert reading == ["News", "Python Docs"]       # visited link above never-visited
