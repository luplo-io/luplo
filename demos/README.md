# demos/

Reproducible gifs for the README and docs. Two primary demos:

- `recall.tape` → `output/recall.gif` (~15s) — `lp items search` finds a
  decision with rationale and supersedes context.
- `impact.tape` → `output/impact.gif` (~30s) — `lp impact` traverses a
  small decision graph and prints the blast radius.

## Why VHS (not asciinema)

We use [VHS](https://github.com/charmbracelet/vhs) because the `.tape`
script is a single source of truth — re-running it regenerates the gif
deterministically. asciinema plus `agg` would also work but needs two
tools and two config surfaces.

## Prerequisites

```bash
brew install vhs            # macOS
# or
go install github.com/charmbracelet/vhs@latest
```

Plus a running luplo Postgres instance the demo can seed into. By
default the scripts point at `postgresql://localhost/luplo_demos`.

## Regenerate

```bash
# 1. Reset DB, apply migrations, seed fixtures (one script, idempotent)
./demos/reset-db.sh

# 2. Render the gifs
vhs demos/recall.tape
vhs demos/impact.tape
```

`reset-db.sh` drops `luplo_demos`, recreates it, runs
`alembic upgrade head`, and loads `fixtures/seed.sql`. If you prefer to
run those steps by hand, read the script — it is short on purpose.

`output/recall.gif` and `output/impact.gif` get overwritten in place —
commit the updated files.

## Fixture layout

`fixtures/seed.sql` creates:

- One project (`demos`)
- One actor (UUID `00000000-0000-0000-0000-0000000d1a5c`,
  `demo@luplo.io`)
- One work unit (`demos-websocket`)
- Seven decision items forming a realistic dependency graph,
  including a SQLite → Postgres supersedes chain
- Four typed edges (`depends`) connecting them

The IDs are fixed strings (valid UUID-format, but not random) so the
gifs stay visually stable across runs — every rerun shows the same
8-character prefix (e.g. `dec00023`).

## What's intentionally missing

- No continuous integration for rendering. Gifs are committed to the
  repo and updated manually. CI-driven rendering adds a dependency on
  VHS in Actions for no real win.
- No asciinema fallback. Pick one tool; switch only if VHS breaks.
