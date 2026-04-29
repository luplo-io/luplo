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

1. **Resolve inputs.** $1 is the spec path, $2 is the plan path, $3 is the dest language. If $1 looks like a language code (≤3 chars), treat it as `dest_lang` and shift.

2. **Read source files locally.** Use the `Read` tool to load the spec and plan markdown files into memory. The MCP tool is filesystem-free — the agent (you) is the filesystem boundary, which is what makes this command work against the cloud MCP server too. Capture the absolute path of each file as the `path` field.

3. **Call `luplo_import_begin`** with the assembled `sources` list. Each entry is `{kind: "spec"|"plan", path: <abs path>, content: <file content>}`. Also pass `dest_lang` (if provided), `repo_root` (the current working directory's absolute path), and `force=false` initially.

4. **Handle the response:**

   - If `bundle_id` is in the response → manifest received, proceed.
   - If `status="refused"` → display the `why`, `override`, and `agent_hint` fields verbatim. ASK THE USER whether to retry with `force=true`. Do not silently retry.

5. **Parse the manifest.** Read `sources.spec.raw_markdown` and `sources.plan.raw_markdown` (echoed back from the server), plus `protocol.rules` for the extraction policy.

6. **Extract item candidates.** Dispatch a Task subagent (Haiku-class for cost) with this prompt:

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

7. **Verify each candidate's status in parallel.** For each candidate, dispatch a separate Task subagent (use the `Explore` subagent_type which runs Haiku):

   > For the candidate "<title>", search the repo at <repo_root> in these paths/symbols: <paths_to_verify>.
   > Return: status ∈ {done, partial, notdone, rejected} and evidence_paths (list of `path:line-range`).

8. **Assemble `ImportResults`** as JSON: `{bundle_id, items: [...], close_work_unit: false}`. Each item gets a `Status: <emoji+word>` first line in its body.

9. **Call `luplo_import_finalize`** with the assembled results.

10. **Display summary.** Show items_created and any warnings. If warnings mention stripped code blocks, surface that to the user as a violation note.

## Why the agent reads files (not the server)

`luplo_import_begin` accepts inline `sources` content rather than paths. This is intentional: when the MCP server runs on the multi-tenant cloud, it has no access to the user's working tree. Pushing the read to the agent side keeps the same code path working in both local and cloud modes. Dedup is keyed on the sorted set of content hashes, so the same bundle imported under different paths or from different working directories collapses to one work_unit.

## Failure handling

- Manifest validation error → show the validation error verbatim; do not retry blindly.
- Subagent extraction inconsistencies → re-prompt the same subagent once; if still inconsistent, ask the user.
- Finalize raises ValueError on cross-project guard or unknown bundle → show the error, do not auto-retry.
