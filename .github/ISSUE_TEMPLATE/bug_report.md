---
name: Bug report
about: Something is broken or behaves unexpectedly
labels: bug
---

## What happened

A clear, concise description of the bug.

## How to reproduce

Steps to reproduce. Include the exact command, input, and/or code when
possible. A minimal repro is worth ten paragraphs of prose.

```text
# e.g.
lp items search "vendor"
# → traceback / wrong output
```

## Expected behaviour

What you thought should happen.

## Actual behaviour

What actually happened (paste error output, stack traces, screenshots).

## Environment

- luplo version: (e.g. `0.1.0` — `uv run lp --version` or
  `pip show luplo`)
- Python: (e.g. `3.12.7`)
- PostgreSQL: (e.g. `16.4`)
- OS: (e.g. `macOS 14.5`, `Ubuntu 24.04`)
- Mode: Local / Remote
- MCP client (if relevant): (e.g. Claude Code 0.5, Cursor 0.40)

## Additional context

Anything else that might help — related issues, recent changes, custom
configuration, DB size, whether it reproduces on a fresh `lp init`.
