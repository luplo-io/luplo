# luplo

[![Documentation Status](https://readthedocs.org/projects/luplo/badge/?version=latest)](https://luplo.readthedocs.io/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

> Long-term memory for engineering decisions.

PMs brief the work. Agents (or humans) execute it. Decisions and knowledge 
persist across sessions, people, and time — searchable forever.

luplo tracks:
- **Jobs** — goals you're working toward
- **Tasks** — units of execution within a job
- **Decisions** — why you chose this path (and rejected others)
- **Knowledge** — long-lived facts about your systems
- **Research** — cached web pages and references, full-text searchable

## Why luplo

Most AI coding tools forget. luplo remembers — and shares.

- **Pair handoff in one command.** Your teammate spent 2 hours building 
  context, making decisions, and researching. `luplo brief` gives you 
  all of it — instantly.
- **Verify-gated completion.** Tasks can't be marked done until your 
  verify command passes. No more "done" tasks that broke the build.
- **Full-text search built in.** PostgreSQL tsquery on knowledge, 
  decisions, and research.
- **Vendor-neutral.** Works with Claude Code, Cursor, Codex, or no AI at all.
- **Your data, your database.** Self-host with Docker. AGPL-3.0.

## Quick start

```bash
uv tool install luplo
luplo init
luplo project use myapp
luplo job create "Auth rework"
luplo task add "Add JWT validation" --job 1 --verify "go test ./..."
luplo task start
# (work)
luplo task done --summary "JWT middleware added"
```
