# Concepts

Explanation-oriented pages. Read these before the guides if you want to
understand *why* luplo behaves the way it does.

- {doc}`philosophy` — the three commitments (tool-not-framework,
  augment-not-replace, honesty-over-coverage) and the list of features
  luplo refuses to build.
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
architecture
data-model
search-pipeline
```
