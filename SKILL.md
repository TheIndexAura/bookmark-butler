---
name: bookmark-butler
description: >
  Organize messy browser bookmarks end-to-end: find every browser profile on the
  machine, merge and dedupe bookmarks across profiles, sort links into logical
  folders, trim names to short essentials, collapse URLs to root domains (except
  content pages like GitHub repos or Google Docs), test every link and repair
  broken deep links, then apply the layout the user picks via a numbered
  priority menu. Use when the user asks to organize, clean up, sort, merge, or
  fix their bookmarks or favorites in Chrome, Edge, Brave, Vivaldi, or Opera.
---

# Bookmark Butler

Turn years of bookmark chaos into a clean, ordered bar — safely, with backups
and an undo path — across every profile on the machine.

## Supported browsers

| Browser | Support | Bookmarks file |
|---|---|---|
| Chrome, Edge, Brave, Vivaldi, Opera | Full (read + write) | JSON `Bookmarks` file per profile |
| Firefox | Detect + read-only report | `places.sqlite` (write not supported — tell the user to export/import HTML instead) |

All Chromium-family browsers share the same JSON format, so one workflow covers
them all. Scripts auto-detect Windows / macOS / Linux paths.

## Hard safety rules (non-negotiable)

1. **Never write while the browser is running.** It will overwrite your changes
   on exit. Check the process list; if running, ask the user to close it fully
   and re-check before writing.
2. **Timestamped backup of every profile's bookmarks file BEFORE any write.**
   Keep the backup beside the original. Tell the user the exact backup paths.
3. **Never delete a link without user approval.** "Broken" links get a repair
   attempt first (see Phase 5). Local/LAN links are never deletable — an
   internet check cannot reach them.
4. **Read → present plan → get approval → write.** Never write on the first
   pass. The user sees the full proposed layout before anything changes.
5. **Verify after writing** (re-parse the JSON, count folders/links) and report
   the result plainly.

## Workflow

### Phase 1 — Find profiles

```
python scripts/find_profiles.py            # emails masked (safe to screenshot)
python scripts/find_profiles.py --json     # machine-readable
python scripts/find_profiles.py --show-emails   # full emails, ask user first
```

It lists every browser install, every profile,
the signed-in account email (when recorded), and the bookmark count. Present
this table and ask which profiles to organize, and whether to:

- **Merge** — all chosen profiles end up with one identical merged set (nothing lost), or
- **Separate** — each profile keeps its own links, organized in the same style.

If profiles belong to different accounts with sync enabled, warn: the new
layout syncs to each account's cloud (and other devices) when the browser
reopens.

### Phase 2 — Read and merge

```
python scripts/dump_bookmarks.py --out merged.txt "<PROFILE_DIR_1>" "<PROFILE_DIR_2>"
```

It outputs every bookmark (name, URL, current folder) to a UTF-8 file and
dedupes by URL.
Read the dump. Note the user's existing folders — they signal the categories
the user already thinks in. Build on them, don't discard them.

### Phase 3 — Categorize and trim names

This is judgment work — do it yourself (no script):

- **Categories:** group by purpose, not by site. Aim for 8–14 folders. Reuse
  the user's existing folder names where they fit. Fold folders with only 1–2
  links into a catch-all (e.g. "Keepers") unless the user wants them separate.
- **Names:** trim every bookmark to the shortest name that still identifies it.
  Strip page-title junk (`| SiteName`, `- Home`, marketing taglines, `(1)`
  notification counts). Target ≤ 32 characters. Two links must never end up
  with the same name — disambiguate (`Router-Home`, `Router-Login`).
- Ask the user's preference on emoji folder prefixes; default to plain text.

### Phase 4 — Root-domain collapse

Rewrite each URL to `scheme://host/` **except** when the path IS the content.
Keep the full URL for: GitHub repos/profiles, Google Docs/Sheets/Slides, Notion
pages, Canva designs, YouTube videos/channels, Kickstarter projects, 3D-model
pages, specific articles, and anything else where root ≠ the saved thing.
When in doubt, keep the full URL — collapsing is lossy.

After collapsing, re-dedupe (several deep links often fold into one root) and
tell the user the before/after counts.

### Phase 5 — Link check

```
python scripts/check_links.py --in urls.txt --out results.txt
```

(`urls.txt`: one URL per line; lines like `name | url` are fine — the checker
takes the last field.) Interpret results:

- `OK` — alive.
- `AUTH` (401/403/405/429/999) — login wall or bot wall. **Alive.** Keep.
- `LOCAL` — LAN/localhost/private hostname. **Untestable from outside. Keep.**
- `TIMEOUT`/`ERR` — uncertain. Keep unless the user says otherwise.
- `DEAD` (404/410/DNS failure) — try the **root domain** before deleting:
  users often save login or deep URLs that rot while the site lives. If root
  answers, repair the bookmark to the root (or the nearest working parent
  path). Only propose deletion when the root is dead too — and let the user
  approve the delete list.

### Phase 6 — Layout menu (numbered priorities)

Present the proposed folder set and counts, then ask the user to **rank the
ordering rules by number** (1 = applied first / highest priority; skip any
they don't want):

```
How should the bar be laid out? Rank with numbers (1 = top priority,
leave blank to skip):

__  Pinned folders first  (you name 2–4 most-used folders to lead the bar)
__  Loose quick-links visible on the bar  (you name them, or keep existing)
__  Folders ordered by usage  (real visit counts from browser history)
__  Folders ordered alphabetically
__  Links inside folders by usage
__  Links inside folders alphabetically
```

Conflicting picks (usage vs alphabetical for the same level): the lower number
wins; the other becomes the tie-breaker. "Usage" ordering reads real visit
counts from the browser's history database (the scripts handle this); links
never visited sort alphabetically below the visited ones.

### Phase 7 — Apply

Build `plan.json` from the approved layout:

```json
{
  "pinned_folders": ["Accounts", "AI"],
  "loose": [["Claude", "https://example.com/"]],
  "folders": {"AI": [["name", "url"]], "Jobs": [["name", "url"]]},
  "folder_order": ["AI", "Jobs"],
  "sort_links": "usage",
  "sort_folders": "usage",
  "expected_urls": ["every", "url", "that", "must", "survive"]
}
```

`expected_urls` is **required**: fill it with the **final approved URL list**
— the URLs as they exist after Phase 4's root-collapse and Phase 5's repairs,
minus user-approved deletions (NOT the raw Phase 2 list; those URLs were
intentionally rewritten). The writer aborts if any of them is missing from
the plan (data-loss guard), and refuses to run without the list unless you
pass `--skip-url-guard` (only with the user's explicit OK). Folders omitted from `folder_order` are appended at
the end, never dropped.

**Scope note:** the writer rebuilds the bookmark bar and clears the
"Other bookmarks" and "Mobile/synced bookmarks" roots — their links were
merged into the new bar in Phase 2. Tell the user this before applying. If a
detected browser is running, the writer refuses and that refusal cannot be
bypassed; `--assume-closed` only covers the rare case where the process list
itself cannot be read (user must visually confirm the browser is closed
first).

Then:

1. **Dry-run first:**
   `python scripts/apply_bookmarks.py --plan plan.json --dry-run "<PROFILE_DIR>"`
   — validates the plan and prints counts, writes nothing.
2. Confirm the browser is fully closed. The writer also checks the process
   list itself and refuses if a browser is running — and fails closed if it
   cannot check.
3. **Apply:**
   `python scripts/apply_bookmarks.py --plan plan.json "<PROFILE_DIR_1>" "<PROFILE_DIR_2>"`
   — backs up each profile (timestamped), writes atomically, verifies, prints
   backup paths.
4. Report: final bar layout, totals (before → after), repaired links, backup
   paths, and undo instructions.
5. Ask the user to open the browser and confirm it looks right.

### Undo / restore

With the browser fully closed, copy the backup over the live file:

```
copy "<PROFILE_DIR>\Bookmarks.backup_<STAMP>" "<PROFILE_DIR>\Bookmarks"     (Windows)
cp "<PROFILE_DIR>/Bookmarks.backup_<STAMP>" "<PROFILE_DIR>/Bookmarks"       (macOS/Linux)
```

Reopen the browser — the old layout is back. If sync already pushed the new
layout to other devices, restoring and reopening pushes the restore the same
way.

## Privacy notes

- `find_profiles.py` masks signed-in emails by default; ask before using
  `--show-emails`.
- `check_links.py` never sends credentials and skips private/LAN hosts
  entirely, so internal hostnames are not leaked to external DNS.
- TLS verification is off in the link checker (liveness only, avoids
  false-dead on self-signed LAN certs) — do not repurpose it for anything
  security-sensitive.
- Usage ordering reads the browser's local History database read-only, via a
  temp copy; nothing leaves the machine.

## Output format

- Phase tables and lists, short lines, no prose walls.
- Every file path in full, copy-paste ready.
- Decisions the user must make come as numbered/lettered menus, one question
  block at a time.

## Anti-patterns

- Writing bookmark files while the browser is running (changes silently lost).
- Deleting a link just because an automated check flagged it — login walls,
  bot walls, and LAN links all flag false-dead.
- Collapsing content URLs (a GitHub repo, a Google Sheet) to bare domains —
  that deletes the thing the user saved.
- Inventing categories that ignore the user's existing folder names.
- One giant "Misc" folder — that's the mess with a new label.
- Skipping the backup because "it's just bookmarks."
