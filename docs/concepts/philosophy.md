# Philosophy

luplo is opinionated about what it will not become. This page collects the
three commitments that shape every design choice in the project, and the
concrete list of features luplo refuses to build because of them.

If you ever wonder "why doesn't luplo just…" the answer usually lives
here.

## Three commitments

### 1. A tool, not a framework

luplo is a **tool**. It does one thing — long-term memory for
engineering decisions — and it does it through a fixed surface: a CLI, an
MCP server, and an HTTP server sharing one core. It is not a platform you
extend from the inside.

The following are **explicitly out of scope**, and will stay out of scope:

- Python plugin loader
- Entrypoint-based plugin discovery
- Lifecycle hook API (`on_item_created`, `before_search`, …)
- Plugin marketplace or registry
- Sandbox / permission system for third-party code

When luplo needs to interoperate with another system, the answer is a
**webhook, a sync worker, or an MCP client on the other side** — never
in-process Python extension points.

:::{admonition} Why this line, and why here
:class: note

Three instincts push projects like luplo toward becoming frameworks: the
SaaS instinct (capture every adjacent feature), the security instinct
(offer a "safe" sandbox so users don't fork), and the OSS-purity instinct
(let the community extend everything). All three are real — and all
three are wrong for a decision-memory tool whose value comes from the
integrity of a small, well-understood surface.

Plugin runtimes in particular carry well-known OSS failure modes: lock-in
on an unstable internal API, security boundary drift, dependency version
conflicts forced onto every user, support burden disproportionate to
adoption, and an "ecosystem" that becomes the product. luplo declines.
:::

### 2. Augment human judgment, don't replace it

luplo records what a human decided, with the reasoning a human chose to
attach. It does not infer decisions. Two specific behaviors that look like
gaps are in fact the point:

- **luplo does not auto-extract decisions from conversation.** There is
  no watcher that scrapes a Claude transcript and posts items on the
  user's behalf. Items exist because someone explicitly called
  `luplo_save_decisions`, `lp items add`, or equivalent.
- **luplo does not auto-inject a project brief.** No pre-prompt, no hidden
  preamble. An MCP client sees context only when it chooses to call
  `luplo_brief`.

The reason is simple: trigger awareness belongs to the person doing the
work. If luplo silently decided *this is the moment to save a decision*,
it would be answering a question that only the human can answer
honestly — and every wrong answer would corrode trust in everything
luplo records.

### 3. Honesty over coverage

When luplo cannot find something, it says so. It does not fabricate
relevance to look more useful.

This shows up most clearly in search:

- Retrieval is **tsquery-first** over `items.ts` with glossary expansion.
  If tsquery returns nothing, that is the honest answer.
- The vector backend (optional, off by default) **only reranks** the
  tsquery candidate set. It never generates a candidate of its own.
- Every match carries an explicit reason — which aliases fired, which
  terms matched — so an auditor can reconstruct the query path.

The same principle governs the glossary itself. luplo's glossary pipeline
is **strict-first**:

1. Deterministic normalization (case, whitespace, Korean morphemes).
2. Strict LLM matching — translation-grade synonyms only. "None" is a
   better answer than "wrong".
3. Human curation queue for candidates the pipeline is unsure about.

Aggressive clustering would raise recall at the cost of false positives,
and a false grouping ("HTK" pulled into the "height" cluster, "Nakama"
merged with "friend") is worse than no grouping. It destroys user trust
in everything else the system says.

See {doc}`search-pipeline` for the full four-stage mechanics.

## What this implies operationally

- **Items are immutable.** Edits create a new row via `supersedes_id`;
  the previous row stays, with `deleted_at` for soft removal. The row
  history is the audit trail, and nothing is physically removed.
- **Work units span sessions.** They model the human intent, not a tool
  session. `created_by ≠ closed_by` is a handoff record, not a bug.
- **The DB is the contract.** Item types live in an `item_types`
  registry in Postgres, not in a Python class. Any language, any
  client — including raw SQL — can add a new item type by inserting a
  row. No fork required.
- **No hidden automation.** Every write is traceable to a caller —
  CLI command, MCP tool call, or HTTP request — and lands in
  `audit_log` with the actor that issued it.

## How to recognise a proposal that violates these commitments

Before adding a feature, check it against this list. If two or more
apply, the feature is probably wrong for luplo even if it is popular in
adjacent products:

1. Does it require loading third-party Python code at runtime?
2. Does it act on the user's behalf without an explicit call?
3. Does it make search results appear where retrieval did not justify
   them?
4. Does it physically remove or silently rewrite a prior record?
5. Does it move the contract out of the database into a language-specific
   surface?

These are not rules to follow blindly — they are the shape of decisions
luplo has already made. New decisions can override them, but only
explicitly, as new items with stated rationale.

## Why nail this down

Identity decisions drift. Six months from now a contributor — or a
future maintainer, or a future version of the author — will propose a
plugin API, a transcript watcher, or a "just reweight these results"
patch. The usefulness of this page is that each of those proposals
already has a recorded answer, with the reasoning intact.

luplo is small on purpose. The surface it exposes is the one it commits
to keeping.
