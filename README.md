# <img src="media/hat.png" height="40" alt="bowler hat"> Bookmark Butler

**Years of bookmark chaos. One conversation. A clean bar.**

An AI-agent skill that merges every browser profile you own, kills the
duplicates, repairs the dead links, trims the names, and lays it all out the
way *you* actually browse — with backups and an undo path at every step.

![Bookmark Butler — the hat flies in and lands between the words while a messy bookmark list becomes clean folders](media/hero.gif)

## ▶ Use it right now

Two ways in:

1. **The skill (recommended)** — drop this folder into your agent's skills
   directory (e.g. `~/.claude/skills/bookmark-butler/`) and say
   *"organize my bookmarks."* Tested scripts do the heavy lifting.
2. **The prompt** — no skill system? Paste
   [`PROMPT.md`](PROMPT.md) into any AI coding agent that can run code on
   your machine (Claude Code, Codex CLI, Cursor, Windsurf, Aider…). Same
   workflow, built from instructions alone.

Works with **Chrome, Edge, Brave, Vivaldi, Opera** on Windows / macOS /
Linux. Firefox is detected read-only. Python 3.9+, standard library only —
zero dependencies.

## What it actually does

| Your mess | What the Butler does |
|---|---|
| 3 profiles, 3 different messes | Finds every profile + account, merges into one identical set — nothing lost |
| `My Account Login - Pay Bills Online & Manage Your Serv…` | `My Bank` |
| 9 copies of the same site saved 9 ways | One bookmark, deduped by root domain |
| That job posting from 2023 (404) | Repaired to the site's live root instead of deleted |
| `192.168.1.1` flagged "dead" by a dumb checker | Never — LAN links are untestable from outside, so they're untouchable |
| "Sort it… somehow?" | You rank the layout rules by number: pinned folders, usage order (from your real browser history), alphabetical |

## Why you can trust it with 15 years of bookmarks

This thing is paranoid on purpose:

- 🛑 **Refuses to write while your browser is open.** A detected running
  browser can never be bypassed. If the process list itself can't be read it
  fails closed too — the only override (`--assume-closed`) covers that
  can't-check case, after you confirm the browser is closed yourself.
- 💾 **Timestamped backup of every profile before any write** — restore is one
  file copy, and the skill prints the exact paths.
- ⚛️ **Atomic writes** — a crash mid-write can't corrupt your bookmarks file.
- 🧮 **Data-loss guard** — the writer aborts unless every merged URL is
  accounted for in the final plan. On by default; bypassing takes an explicit
  flag and your explicit OK.
- 🙈 **Emails masked by default** (`a**@g**.com`) so profile listings are
  safe to screenshot.
- 🔍 **Nothing deleted without your explicit OK** — "broken" links get a
  root-domain repair attempt first, because you probably saved a login URL
  that rotted while the site lives on.

## The workflow (7 phases, approval-gated)

```
1 find profiles → 2 merge + dedupe → 3 categorize + trim names
→ 4 root-domain collapse (content pages kept whole)
→ 5 link check + repair → 6 YOU pick the layout → 7 backup + apply + verify
```

Phase 6 is a numbered menu — rank what wins: pinned most-used folders,
loose quick-links on the bar, usage order, alphabetical. Usage comes from
your browser's own history database, read locally. Nothing leaves your
machine.

Heads-up on scope: the organized layout lives on the bookmark **bar**. Since
everything merges into it, "Other bookmarks" and "Mobile bookmarks" are
emptied (their links move to the bar) — you approve that in Phase 6 before
anything is written, and it syncs like any other bookmark edit.

<details>
<summary>🖥️ <b>What Phase 1 looks like</b></summary>

```
$ python scripts/find_profiles.py
Chrome  Default      a**@g**.com     bookmarks=156
Chrome  Profile 1    a**@g**.com     bookmarks=17
Chrome  Profile 2    a**@g**.com     bookmarks=12
Edge    Default      a**@g**.com     bookmarks=861
```

Yes, it will find bookmark hoards you forgot existed.

</details>

## What's in the box

```
bookmark-butler/
├── SKILL.md                  # the workflow your agent follows
├── PROMPT.md                 # standalone paste-anywhere version
├── scripts/
│   ├── find_profiles.py      # detect browsers/profiles/accounts (read-only)
│   ├── dump_bookmarks.py     # merged, deduped dump (read-only)
│   ├── check_links.py        # liveness checker + root-repair hints (read-only)
│   └── apply_bookmarks.py    # backup + atomic write + verify (the ONLY writer)
├── media/
├── LICENSE
└── README.md
```

Three scripts can only read. One script can write, and it's wrapped in every
guard above.

## Make it yours

The categorization brain lives in `SKILL.md`, not the scripts — your agent
groups links around *your* existing folder names, so no two users get the
same layout. Want different content-page exceptions, tighter name length, an
extra layout rule? Edit the markdown. PRs welcome.

## Honest limits

- Firefox: detection only (different database — use its HTML export/import).
- Safari: not covered.
- "Usage" ordering is per-domain, not per-exact-URL — approximate by design.
- Link checking sends no credentials and skips recognized private hosts
  (private/loopback/link-local IPs, `.local`-style suffixes, unqualified
  names), but a liveness check is not a security audit.

## License

[MIT](LICENSE) — tidy responsibly.
