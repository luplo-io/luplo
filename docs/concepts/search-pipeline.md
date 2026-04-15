# Search pipeline

luplo's search is deliberately unromantic. It is a four-stage pipeline
where Postgres `tsquery` does the retrieving, the glossary does the
rewriting, and vectors — when present — only re-order the candidates
that tsquery already found. If retrieval finds nothing, the answer is
**nothing** — not a synthesized guess.

## The four stages

```
   user query
        │
        ▼
┌───────────────────┐
│ 1. Context router │   project_id auto-filled from .luplo,
│                   │   optional system filter
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 2. Glossary       │   normalise → strict alias expansion:
│    expansion      │   "vendor" → (vendor | shop | NPC merchant)
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 3. tsquery        │   Postgres full-text search over
│    retrieval      │   items.ts  (GIN index scan)
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 4. Vector rerank  │   OPTIONAL. pgvector cosine similarity
│    (optional)     │   reorders the tsquery candidate set.
└────────┬──────────┘
         ▼
      results
(with explicit match reasons: which aliases matched which fields)
```

### 1. Context routing

Every search carries a `project_id`. In the CLI it comes from `.luplo`;
in MCP it comes from the tool argument. The router can also apply a
system filter so that "auth" queries do not drag in items from the
"rendering" system. Nothing magical — just scoped WHERE clauses.

### 2. Glossary expansion

The glossary is the mechanism that lets `"vendor"` find items indexed
under `"shop"` or `"NPC merchant"` without requiring the caller to know
every alias. The pipeline is **strict-first**, with three layers:

1. **Deterministic normalization.** Lowercase, whitespace collapse,
   Korean morpheme splitting. Zero false positives — this step is
   purely mechanical.
2. **Strict LLM matching.** Only translation-grade synonyms ("shop"
   ↔ "store") make it into a glossary group. The prompt is tuned so
   that **NONE** is a better answer than a wrong grouping.
3. **Human curation queue.** Candidates the LLM is unsure about go into
   `glossary_terms` with `status='pending'`, visible via
   `lp glossary pending` and `luplo_page_sync`.

The query is rewritten into a tsquery expression that ORs the aliases
within each matched group:

```text
"vendor budget"
  → (vendor | shop | "NPC merchant") & (budget | gold-pool | current_budget)
```

Every alias that fires is recorded with the result, so downstream
tooling can show **why** a match was returned.

#### `is_protected` — when clustering should stay away

The LLM flags terms as `is_protected=true` whenever they look like
identifiers that must never be pulled into a synonym cluster:

- Upper-case acronyms (`HTK`, `API`, `RPC`)
- Programming identifiers (`snake_case`, `camelCase`)
- Proper nouns not in the general dictionary (`Pyromancy`, `Nakama`)

Protected terms participate in exact match and deterministic
normalization, but the strict LLM step refuses to cluster them with
anything else. This is the guardrail that keeps `HTK` from becoming
an alias of `height`.

### 3. tsquery retrieval

Retrieval runs against the generated `items.ts` column — a concatenation
of title, body, rationale, alternatives, tags, and (when present) a few
`context` fields — indexed by GIN.

The result limit at this stage is intentionally generous (default:
fetch `limit × 4` candidates) so the vector reranker, when enabled, has
room to re-order.

### 4. Vector reranking (optional)

When the `vector-local` extra is installed and pgvector is available,
each candidate's `embedding` is compared to the query embedding via
cosine similarity. The top `limit` results after reranking are returned.

**Vector search never originates candidates.** If tsquery returns zero
rows, vector rerank has nothing to do, and the search returns empty.
This is the honesty rule — see {doc}`philosophy` — encoded in code.

#### Embedding backends

Three drop-in backends exist:

| Backend | Dimensions | When to use |
|---|---|---|
| `null` (default) | — | Don't want the ML dependency. Search is still glossary + tsquery, just no rerank. |
| `local` | 1024 | `uv sync --extra vector-local` — runs sentence-transformers locally (~500MB). |
| `remote` | 1024 | Call an external embedding service. For deployments where the worker can afford it but clients can't. |

Switching backends does not re-embed history automatically — new writes
get embeddings under the new backend; older rows keep whatever they had
(including NULL).

## Why this shape, not RAG

luplo's domain is **engineering decisions**: rationale, alternatives,
policy constraints. Semantic proximity is useful, but **traceable
retrieval** is the job. When a future maintainer asks "why did we
decide X?" the answer must come with a receipt:

- Exact terms that matched
- Glossary groups that fired
- Item ids and supersedes chain

A pure vector search fabricates relevance from embedding distance and
cannot produce that receipt. luplo keeps vectors in a ranking role so
retrieval always has a defensible reason to show you what it showed.

## How to tune it

- **Missing matches?** Add aliases via `lp glossary pending` → approve.
- **False positives in the glossary?** Reject them — they'll land in
  `glossary_rejections` and never be suggested again.
- **Need closer-to-semantic ranking?** Install `vector-local`. Existing
  writes will rerank from the next worker pass onward.
- **Want to restrict to a system?** `lp items search "foo" --system auth`
  (CLI) or `system_ids=['<uuid>']` (MCP).

## Next

- {doc}`../guides/mcp-client` — hooking MCP clients to these tools.
- {doc}`../reference/semantic-impact` — how item edits are categorised
  (related but distinct from search).
