# Positioning

Readers show up asking "is this like X?" — where X is usually a chatbot
memory layer, a vector database, or a wiki-plus-AI. This page answers
that directly, so nobody has to infer the category from feature names.

luplo is **not** in the same category as any of those. It overlaps on
surface (there is a store; there are embeddings; there is a query API),
and the overlap is where the confusion lives. The axes below are where
the difference is.

## Eight axes

| Axis | A generic AI-memory tool | luplo |
|---|---|---|
| **Unit of storage** | A fact about a user | A decision + its reasoning, made by a team |
| **Retrieval** | Vector-first (semantic search) | `tsquery` + glossary expansion first; vectors only rerank |
| **Mutation** | Facts are updated or deleted in place | Items are immutable; changes create a new row via `supersedes_id` |
| **Relationships** | Flat store; at most parent/child | Typed edges — `depends`, `blocks`, `supersedes`, `conflicts` |
| **Graph traversal** | None, or single-hop | Five-hop CTE traversal on Postgres (`lp impact`) |
| **Contradiction detection** | Current fact vs new fact only | Full decision history vs new decision |
| **Write trigger** | AI runtime writes implicitly ("I'll remember that") | Human writes explicitly via CLI or MCP tool call; AI reads |
| **Time dimension** | Current state only | Change history is the asset; `items_history` + `audit_log` |

## One-sentence contrast

> A generic AI-memory tool remembers "this user owns a cat."
> luplo remembers "on March 2nd we chose Postgres, because X, over
> alternative Y, and three decisions depend on this one."

Both are valid storage shapes. They solve different problems. Mixing
them into one tool produces a worse version of each.

## Why the axes fall where they do

Every row in the table is an expression of the
{doc}`five refusals <philosophy>`. The short version:

- **Vector-first refusal** pins retrieval on `tsquery`. Vectors can
  still help — but only to reorder candidates retrieval already found,
  never to invent new ones.
- **Decision immutability refusal** pins mutation on supersede-not-edit.
  The history is the audit trail; overwriting destroys the lesson.
- **Typed-and-bounded-edges refusal** pins relationships on named
  types, and graph traversal on a five-hop ceiling. A graph that
  needs a layout engine to read is a model that has already lost.
- **Not-a-general-memory refusal** pins the unit of storage on
  engineering decisions. User preferences, conversation history, and
  arbitrary facts belong in other tools.
- **Honesty-over-coverage** (operational commitment) pins the contradiction
  check on "full history vs new write", because a new decision that
  contradicts an old one is information the user must see before they
  commit it.

## When luplo is the wrong tool

Three categories luplo is **not** trying to serve:

- **User preferences / personalization.** If the thing you want to
  remember is "this user prefers dark mode" or "this user dismissed the
  tutorial", a chatbot memory layer or a plain key-value store is the
  right shape. luplo's immutability will fight you.
- **Document drafting / collaborative editing.** A wiki or Google Docs
  is the right shape for "we are editing this paragraph together". luplo
  stores the *decisions* that come out of that process, not the prose
  you iterated on to produce them.
- **Ticket queue.** Linear, Jira, or GitHub Issues is the right shape
  for "here is a bug with a priority and an assignee". luplo's `task`
  item type exists for task *lineage* (who decided this should be done,
  why, what it connects to) — not for weekly sprint management.

Using luplo for these will work, but badly. The feedback loop will feel
wrong: you will want to edit items it forbids you to edit, the five-hop
ceiling will feel arbitrary, and the "decision + rationale" shape will
feel like overhead.

## When luplo is the right tool

The short version: when six months later somebody will ask "why is X
like that?" and "what else depends on it?" — luplo is the place that
answers both.

Specifically:

- Small to medium engineering teams that make irreversible technical
  calls (framework choice, data shape, auth scheme) and need the
  *reasoning* to outlive the person who made it.
- Solo developers building something durable enough that they will
  forget their own reasoning inside a month.
- OSS projects that want a public, append-only log of why the codebase
  looks the way it does.

## See also

- {doc}`philosophy` — the five refusals that shape the axes above.
- {doc}`search-pipeline` — why tsquery leads and vectors rerank.
- {doc}`data-model` — how immutability and typed edges are stored.
