# `lp import` — manual E2E checklist

Run before each release that touches the import pipeline.

## Setup
- [ ] Local PG running with luplo schema migrated to head
- [ ] `.luplo` points at the test project
- [ ] At least one Claude Code session open with this repo

## Cases

### 1. Full-pair happy path
- [ ] `cp tests/fixtures/import/full-pair/* /tmp/`
- [ ] In Claude Code: `/lp-import /tmp/spec.md /tmp/plan.md ko`
- [ ] Verify: manifest displayed, agent dispatches subagents, finalize summary shows ≥2 items_created
- [ ] `lp items list --wu <id>` lists the new items in Korean
- [ ] No fenced code blocks in any item body (grep manually)

### 2. Spec-only
- [ ] `/lp-import /tmp/spec.md` (no plan)
- [ ] Manifest's `sources.plan` is `null`; finalize succeeds.

### 3. Plan-only
- [ ] `/lp-import /tmp/plan.md`
- [ ] Treated as plan input. Items reflect plan steps as knowledge/decision rollups.

### 4. Duplicate refusal
- [ ] Re-run case 1 verbatim
- [ ] Refusal displayed with `why`, `override`, `agent_hint`. Agent does NOT silently retry.

### 5. Force replace
- [ ] Re-run case 1 with `force=true` (instruct the slash command)
- [ ] Old work_unit shows status='archived' (`lp work list`)
- [ ] New work_unit has `context.replaces = <old_id>`

### 6. dest_lang precedence
- [ ] Set `.luplo [project].language = "en"`
- [ ] Run with `--dest-lang ko`
- [ ] Items appear in Korean (CLI overrides config)

### 7. dest_lang null → preserve source
- [ ] Remove `[project].language` from `.luplo`
- [ ] Run without `--dest-lang`
- [ ] English source produces English items; Korean source produces Korean items.

### 8. Code-block stripping defense-in-depth
- [ ] Manually craft a `results.json` with a body containing ` ``` ` fenced blocks
- [ ] `lp import finalize --results results.json`
- [ ] Resulting item body contains `[code: ...]` placeholder, not the original code.

## Sign-off
Tester: ____  Date: ____  Pass/fail per case: ____
