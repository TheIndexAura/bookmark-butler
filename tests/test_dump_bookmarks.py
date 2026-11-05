import sys

import dump_bookmarks


def run(monkeypatch, out, *profiles):
    monkeypatch.setattr(sys, "argv", ["dump_bookmarks.py", "--out", str(out), *profiles])
    dump_bookmarks.main()
    return out.read_text(encoding="utf-8")


def merged_section(text):
    tail = text.split("MERGED + DEDUPED", 1)[1].splitlines()[1:]
    return [ln.strip() for ln in tail if ln.strip()]


def test_merges_two_profiles_and_all_roots(monkeypatch, tmp_path, profiles):
    text = run(monkeypatch, tmp_path / "merged.txt", *profiles)
    assert "PROFILE: " + profiles[0] in text
    assert "PROFILE: " + profiles[1] in text
    assert "--- root: bookmark_bar ---" in text
    assert "--- root: other ---" in text          # 'other' root is read too
    assert "--- root: synced ---" not in text     # empty root not printed
    assert "Work | [Work] | FOLDER" not in text
    assert "(top) | [Work] | FOLDER" in text      # folder marker
    assert "Work | Jira - Login | https://jira.example.com/login" in text
    urls = {ln.rsplit(" | ", 1)[1] for ln in merged_section(text)}
    assert urls == {
        "https://github.com/",
        "https://jira.example.com/login",
        "http://192.168.1.1/",
        "https://docs.python.org/3/",
        "https://jobs.example.org/posting/2023/123",
        "https://news.example.net/",
    }


def test_duplicates_removed_first_seen_name_wins(monkeypatch, tmp_path, profiles):
    text = run(monkeypatch, tmp_path / "merged.txt", *profiles)
    rows = merged_section(text)
    github = [r for r in rows if r.endswith("https://github.com/")]
    pydocs = [r for r in rows if r.endswith("https://docs.python.org/3/")]
    assert len(github) == 1 and github[0] == "GitHub | https://github.com/"
    assert len(pydocs) == 1 and pydocs[0] == "Python Docs | https://docs.python.org/3/"
    assert "MERGED + DEDUPED (6 unique urls)" in text


def test_order_of_profiles_decides_winner(monkeypatch, tmp_path, profiles):
    text = run(monkeypatch, tmp_path / "merged.txt", profiles[1], profiles[0])
    rows = merged_section(text)
    assert "GitHub - Where the world builds software | https://github.com/" in rows


def test_bad_profile_is_skipped_not_fatal(monkeypatch, tmp_path, profiles, capsys):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "Bookmarks").write_text("{not json", encoding="utf-8")
    text = run(monkeypatch, tmp_path / "merged.txt", str(bad), profiles[0], str(tmp_path / "missing"))
    err = capsys.readouterr().err
    assert err.count("SKIP") == 2
    assert "MERGED + DEDUPED (4 unique urls)" in text


def test_walk_handles_nested_folders():
    node = {"children": [
        {"type": "folder", "name": "A", "children": [
            {"type": "folder", "name": "B", "children": [
                {"type": "url", "name": "deep", "url": "https://d.example/"}]}]}]}
    rows = dump_bookmarks.walk(node, "")
    assert ("A/B", "deep", "https://d.example/") in rows
    assert ("(top)", "[A]", "FOLDER") in rows
    assert ("A", "[B]", "FOLDER") in rows
