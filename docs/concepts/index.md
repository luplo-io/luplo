# Concepts

Explanation-oriented pages. Read these before the guides if you want to
understand *why* luplo behaves the way it does.

- {doc}`philosophy` — the five refusals (vectors-don't-lead, five-hop,
  decisions-immutable, typed-and-bounded edges, not-a-general-memory)
  and the three operational commitments that enforce them.
- {doc}`positioning` — how luplo differs from generic AI-memory tools
  on eight axes, and when it is (or isn't) the right tool.
- {doc}`architecture` — the three interfaces (CLI / MCP / HTTP) sharing
  one core, the Backend protocol, and the worker.
- {doc}`data-model` — the twelve tables, `items` as substrate, and the
  `item_types` registry.
- {doc}`search-pipeline` — the four-stage retrieval pipeline, strict-first
  glossary, and the role of vector reranking.

```{toctree}
:hidden:
:maxdepth: 1

philosophy
positioning
architecture
data-model
search-pipeline
```
