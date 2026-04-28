---
description: Import a spec/plan markdown pair into luplo as a work_unit + items, with code-grounded status verification via parallel Haiku subagents.
allowed-tools: ["Bash", "Read", "Task", "mcp__luplo__luplo_import_begin", "mcp__luplo__luplo_import_finalize", "mcp__luplo-local__luplo_import_begin", "mcp__luplo-local__luplo_import_finalize"]
---

# /lp-import — Import spec/plan into luplo

## Args
- `$1` — path to spec markdown (optional)
- `$2` — path to plan markdown (optional)
- `$3` — dest language (optional, ISO 639-1 like `ko`, `en`)

At least one of $1 / $2 is required.

## Step-by-step

1. **Resolve inputs.** $1 is `--from-spec`, $2 is `--from-plan`, $3 is `--dest-lang`. If $1 looks like a language code (≤3 chars), treat it as `--dest-lang` and shift.

2. **Call `luplo_import_begin`** with the resolved paths and dest_lang. Pass `force=false` initially.

3. **Handle the response:**

   - If `bundle_id` is in the response → manifest received, proceed.
   - If `status="refused"` → display the `why`, `override`, and `agent_hint` fields verbatim. ASK THE USER whether to retry with `force=true`. Do not silently retry.

4. **Parse the manifest.** Read `sources.spec.raw_markdown` and `sources.plan.raw_markdown`, plus `protocol.rules` for the extraction policy.

5. **Extract item candidates.** Dispatch a Task subagent (Haiku-class for cost) with this prompt:

   > Read the following markdown(s) and produce a list of luplo items. Follow these rules exactly:
   > [paste protocol.rules verbatim]
   >
   > For each item, output:
   > - item_type: decision | knowledge | document
   > - title (in dest_lang if set, else source language)
   > - body (no fenced code blocks)
   > - rationale (optional)
   > - paths_to_verify: list of file paths/symbols to grep for status verification
   >
   > Spec:
   > [paste sources.spec.raw_markdown if present]
   >
   > Plan:
   > [paste sources.plan.raw_markdown if present]

6. **Verify each candidate's status in parallel.** For each candidate, dispatch a separate Task subagent (use the `Explore` subagent_type which runs Haiku):

   > For the candidate "<title>", search the repo at <repo_root> in these paths/symbols: <paths_to_verify>.
   > Return: status ∈ {done, partial, notdone, rejected} and evidence_paths (list of `path:line-range`).

7. **Assemble `ImportResults`** as JSON: `{bundle_id, items: [...], close_work_unit: false}`. Each item gets a `Status: <emoji+word>` first line in its body.

8. **Call `luplo_import_finalize`** with the assembled results.

9. **Display summary.** Show items_created and any warnings. If warnings mention stripped code blocks, surface that to the user as a violation note.

## Failure handling

- Manifest validation error → show the validation error verbatim; do not retry blindly.
- Subagent extraction inconsistencies → re-prompt the same subagent once; if still inconsistent, ask the user.
- Finalize raises ValueError on cross-project guard or unknown bundle → show the error, do not auto-retry.
