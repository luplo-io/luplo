# Roadmap

What we're building next, in order. This page is direction, not dates.

## What we're building next

### 1. Audit — impact analysis

The flagship feature of v0.6. Given an item, traverse typed edges
(`depends` / `blocks` / `supersedes` / `conflicts`) and report the
blast radius: every item reachable from the root within the five-hop
ceiling, each annotated with the edge type that first reached it.

Surfaces on all three interfaces: `lp impact <id>`, the `luplo_impact`
MCP tool, and `GET /items/{id}/impact`. Same structured answer in every
case, so an LLM can cite a decision graph the same way a human reads the
tree.

This is the feature that makes "what breaks if I change this?" a
queryable question. Without it, luplo is an aliasing search over a
decision log. With it, luplo is the only tool that answers the question
by construction rather than by vibe.

### 2. Slack `/archive`

Ingestion vertical one. A Slack slash command that pulls a thread into
a `sync_job`, which the worker structures into an item and hands back
to the user as a draft — never a silent write. This preserves the
{doc}`augment-not-replace <../concepts/philosophy>` commitment while
making decisions that happened in Slack actually findable later.

`/archive` ships after Audit, not before. A decision archiver without
impact analysis is a crowded category. The loop that creates lock-in
is archive-a-decision → six-months-later Audit shows you what depends
on it. Ship the loop, not half of it.

### 3. Notion webhook

Ingestion vertical two. A Notion Public Integration plus a webhook
receiver: page-updated events enqueue `sync_jobs`, the worker fetches
current content, diffs against the previous version in `items_history`,
and proposes an update — same draft-then-confirm pattern as `/archive`.

Shared infrastructure with `/archive` through a small `ExternalSource`
protocol, so adding Confluence, Linear, and similar ingestion sources
later is mechanical.

### 4. Rule pack

Declarative checks that run over the item graph. A rule is a function
that returns findings; luplo ships five starter rules with v0.6 (missing
rationale, undated retention, dangling edge, unresolved conflict,
unlinked policy). Surfaces as `lp check`, `luplo_check`, and
`GET /checks` — structured findings an LLM or a CI job can act on.

Rules are deterministic (SQL plus Python). There is no "LLM-powered
compliance checker" on this roadmap. Hallucination plus regulatory
context is not a product, it is a liability.

## What we're explicitly not building

See {doc}`../concepts/philosophy` for the five refusals in full. The
short list of proposals that will be declined regardless of how they
are framed:

- A plugin runtime that loads third-party Python into luplo.
- A vector-first search mode.
- A traversal depth knob that exceeds five hops.
- A `PATCH /items` that edits an existing row in place.
- A "general memory" surface for non-engineering state.

None of these are rejected because they are hard to build. They are
rejected because building them changes what luplo is.

## How to influence the roadmap

- **Open an issue** for a feature request or a bug report. Link to an
  existing decision in the repo if one already covers the ground.
- **Open a PR** for bug fixes and small, well-scoped improvements
  (typos, doc fixes, test coverage).
- **Open an issue first** for architectural PRs (new subsystems, new
  storage shapes, new surfaces). Large PRs without a prior discussion
  tend to be declined even when the code is good — the shape of luplo
  is a curated decision.

## Version policy

luplo follows [Semantic Versioning](https://semver.org/). While the
version is `0.x`, minor-version bumps (`0.x → 0.(x+1)`) may contain
breaking changes; patch bumps are bug fixes only. Once `1.0.0` is
tagged, the public CLI, MCP tool, and HTTP surface become a stability
commitment.

Until `1.0`, the roadmap above is the main source of intent. Changes
to that intent happen on this page, in git history, and nowhere else.
