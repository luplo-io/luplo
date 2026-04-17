# Philosophy

luplo is opinionated about what it will not become. This page collects
**five refusals** that shape every design choice, and the **three
operational commitments** that enforce them.

If you ever wonder "why doesn't luplo just…" the answer usually lives
here.

## The five refusals

These are the editorial moat. Each refusal is a feature that a
well-meaning proposal will try to add back; each has a standing answer
here so the discussion does not need to happen again from scratch.

### 1. Vectors do not lead search

> **Full-text first. Vectors only rerank. If it's not there, we say so.**

Retrieval is `tsquery` over `items.ts` with glossary expansion. A vector
backend — optional, off by default — may reorder the `tsquery` candidate
set by cosine similarity, but it **never generates a candidate of its
own.**

If `tsquery` returns nothing, that is the honest answer. A vector model
will always find something vaguely related, and "something vaguely
related" is worse than "nothing" when the reader is trying to trust the
system. See {doc}`search-pipeline` for the four-stage mechanics.

### 2. Five hops. No more.

> **Five hops. If your project needs more, you're modeling it wrong.**

Typed-edge traversal (`lp impact`, any future graph surface) stops at
depth five. This is enforced server-side: no config knob, no
`--unsafe-deep` flag, no enterprise override.

Postgres CTE traversal on typed edges could go deeper without breaking.
"We can't do it" is false. The limit exists because traversal depth is a
proxy for model hygiene, and the tool that encodes hygiene is the one
that protects the user from making their own mess. Raising the limit
later — even as an opt-in — reverses this stance.

### 3. Decisions are immutable

> **Decisions are immutable. They get superseded, never edited. Your
> mistakes are your most valuable data.**

An item that has been written is never rewritten. Edits create a new
row via `supersedes_id` and the old row stays, with `deleted_at` for
soft removal. The row history is the audit trail, and nothing is ever
physically removed.

The principle behind it: a wrong decision teaches more than a right
one. Six months after the fact, the reasoning that looked sound at the
time but turned out to be broken is the most valuable artefact the
system holds. Overwriting it destroys the lesson. See
{doc}`data-model` for the supersede mechanics.

### 4. Edges are typed and bounded

> **A graph on Postgres, not Neo4j.**

Links between items are typed (`depends`, `blocks`, `supersedes`,
`conflicts`, and a few more) and every edge is meant. luplo actively
pushes back against "just connect everything to everything" patterns:
impact analysis ignores untyped or non-traversable edges; the five-hop
ceiling caps spider-web growth by construction.

The goal is that a reader looking at a small neighbourhood can
understand it without a layout engine. If the graph needs a force-directed
renderer to be legible, the model is already lost.

### 5. Not a general-purpose memory

> **Engineering decisions only. Not chatbot user profiles.**

luplo is for decisions, knowledge, policies, documents, tasks, QA
checks, and research references — the artefacts of engineering work. It
is not a place to store user preferences, conversation history, or
arbitrary facts about the world.

Applications built **on top of** luplo (GM ticket systems, persona
research tools, compliance dashboards) are welcome. luplo itself stays
narrow. The moment it tries to also be a user-memory store, every
design choice above (immutability, typed edges, honesty over coverage)
starts making concessions, and the tool becomes a worse version of
several better tools.

## Three operational commitments

The refusals above are **what** luplo will not do. The commitments
below are **how** luplo stays that way day-to-day.

### A tool, not a framework

luplo does one thing — long-term memory for engineering decisions — and
it does it through a fixed surface: a CLI, an MCP server, and an HTTP
server sharing one core. It is not a platform you extend from the
inside.

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

### Augment human judgment, don't replace it

luplo records what a human decided, with the reasoning a human chose to
attach. It does not infer decisions. Two specific behaviors that look
like gaps are in fact the point:

- **luplo does not auto-extract decisions from conversation.** There is
  no watcher that scrapes a transcript and posts items on the user's
  behalf. Items exist because someone explicitly called
  `luplo_save_decisions`, `lp items add`, or equivalent.
- **luplo does not auto-inject a project brief.** No pre-prompt, no
  hidden preamble. An MCP client sees context only when it chooses to
  call `luplo_brief`.

Trigger awareness belongs to the person doing the work. If luplo
silently decided *this is the moment to save a decision*, it would be
answering a question only the human can answer honestly — and every
wrong answer would corrode trust in everything luplo records.

### Honesty over coverage

When luplo cannot find something, it says so. It does not fabricate
relevance to look more useful. This commitment is what the
vectors-do-not-lead-search refusal enforces technically, and it shows
up elsewhere too:

- Every search match carries an explicit reason — which aliases fired,
  which terms matched — so an auditor can reconstruct the query path.
- The glossary pipeline is strict-first: deterministic normalization →
  translation-grade LLM matching → human curation queue for unsure
  candidates. Aggressive clustering would raise recall at the cost of
  false positives, and a false grouping (`OTP` merged with `opt`,
  `Sentinel` merged with `guard`) destroys user trust in everything
  else the system says.

"None" is always a valid answer.

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

Before adding a feature, check it against this list. Any single "yes"
is enough reason to pause; two or more almost always means the feature
is wrong for luplo even if it is popular in adjacent products.

1. Does it let vectors retrieve candidates `tsquery` did not already
   find?
2. Does it make traversal deeper than five hops possible, even as an
   opt-in?
3. Does it overwrite or silently rewrite a prior item, instead of
   creating a supersede row?
4. Does it encourage untyped or "catch-all" edges, or make the graph
   require a layout engine to read?
5. Does it turn luplo into a store for non-engineering state
   (user preferences, conversation history, arbitrary facts)?
6. Does it require loading third-party Python code at runtime?
7. Does it act on the user's behalf without an explicit call?
8. Does it move the contract out of the database into a
   language-specific surface?

These are not rules to follow blindly — they are the shape of decisions
luplo has already made. New decisions can override them, but only
explicitly, as new items with stated rationale.

## Why nail this down

Identity decisions drift. Six months from now a contributor — or a
future maintainer, or a future version of the author — will propose a
plugin API, a transcript watcher, a "just reweight these results" patch,
or a helpful auto-linker that connects every item to every other. The
usefulness of this page is that each of those proposals already has a
recorded answer, with the reasoning intact.

luplo is small on purpose. The surface it exposes is the one it commits
to keeping.
