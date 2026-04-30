# `lp import` — Import spec/plan markdown into luplo

`lp import` ingests a spec and/or plan markdown pair (e.g. from
Superpowers, OpenSpec, GitHub Spec Kit, or any other tool that produces
markdown design docs) and stages a luplo work_unit with the decisions
and knowledge extracted from those documents — verified against the
actual repository code.

## How it works

Two-phase pipeline:

1. **`lp import begin`** — opens a work_unit, reads the source files,
   emits a manifest JSON describing what to extract and how to verify it.

2. *(agent territory)* — the calling agent (Claude Code, Codex, Gemini
   CLI) reads the manifest, extracts candidate items, and verifies each
   one against the repository code using parallel small-model subagents.

3. **`lp import finalize`** — receives the assembled results, validates
   them, strips any stray code blocks (defense-in-depth), and writes
   items into luplo linked to the work_unit.

luplo itself never calls an LLM. The protocol — manifest in, results
out — is the cross-agent contract.

## Quick start (inside Claude Code)

```
/lp-import path/to/spec.md path/to/plan.md ko
```

The slash command at `.claude/commands/lp-import.md` orchestrates the
two-phase flow with subagents for you.

## Quick start (raw CLI, agent-agnostic)

```bash
# Phase 1
lp import begin --from-spec spec.md --from-plan plan.md --dest-lang ko \
  > manifest.json

# (agent reads manifest.json, produces results.json out-of-band)

# Phase 3
lp import finalize --results results.json
```

## Configuration

`.luplo`:
```toml
[project]
id = "myproject"
name = "myproject"
language = "ko"   # optional ISO 639-1 — used as default --dest-lang
```

Resolution order for the import target language:
1. `--dest-lang` flag on the CLI / `dest_lang` MCP arg
2. `[project].language` in `.luplo`
3. Neither set → preserve source language verbatim

## Re-running with the same sources

By default, `lp import begin` refuses if the same content has been
imported before. **Dedup is keyed on the sorted set of content
hashes** (`context.content_hash_set`), not on paths — so the same
markdown imported under different filenames or from different
working directories still triggers refusal. This invariant is what
makes the import pipeline cwd-independent and cloud-friendly: the
SaaS server has no concept of the agent's filesystem layout.

The refusal includes the prior `work_unit_id` and the override flag
(`--force`). Forcing archives the prior work_unit and creates a fresh
one — the prior items remain accessible via search but are tied to
the archived bundle.

Don't auto-retry refusals from inside an agent. Surface the refusal text
to the user and ask before forcing.

## Remote (cloud) mode

`lp import` works against the SaaS backend the same way it does against
a local Postgres: configure `.luplo` with `backend.type = "remote"` and
issue an API key (or run `lps login`). The CLI reads files locally and
sends content over HTTP to the cloud's `POST /work-units` and
`GET /work-units/find-existing-import` endpoints, which are filesystem-free.

Actor identity comes from the bearer token; the `[actor]` section in
`.luplo` is optional in remote mode (the server resolves the caller
from its API key or JWT and ignores any client-supplied actor field).

## Output shape

A successful import produces:
- 1 `work_unit` titled `Import: <stem>` with `context.kind = "import"`,
  `context.content_hash_set` for dedup, and `context.source_paths` for
  audit / display
- N `decision` items — major design choices captured from the spec
- M `knowledge` items — gotchas, invariants, conventions worth remembering
- 1-2 `document` items — full translated body of spec/plan (code blocks
  stripped) with `source_url` pointing back to the original markdown
- 0 tasks (`task` items are reserved for non-Superpowers worklists)
- 0 glossary terms (glossary stays user-managed)

Tags such as `lp-import` are applied so the bundle is reachable via tag
search even after the work_unit closes.
