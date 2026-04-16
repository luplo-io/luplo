# Semantic impact categories

Every row in `items_history` carries a `semantic_impact` tag
classifying **why the edit matters**. The categories are filters for
downstream notification and review: changes that alter rules or numbers
are worth surfacing; typo fixes are not.

The seven categories below are the full vocabulary.

| Tag | Meaning | Example |
|---|---|---|
| `numeric_change` | A number in the rationale or rule changed. | Cache TTL `30m → 15m`; rate limit `100 → 200 req/min`. |
| `rule_addition` | A new constraint was appended. | "…and all public endpoints require CSRF tokens." |
| `rule_removal` | A constraint was deleted. | "…and requests must include an X-Client-Id header" removed. |
| `rule_edit` | An existing constraint was substantively rewritten. | "retry up to 3 times" → "retry up to 5 times with exponential backoff". |
| `scope_shift` | The scope the decision applies to changed. | "v1 API" → "v1 and v2 APIs". |
| `rationale_edit` | The reasoning changed but the rule did not. | New justification for the same constraint. |
| `clerical` | Typos, formatting, whitespace. | Spelling fix, markdown polish. |

## How the tag is assigned

The tag is computed by the extraction pipeline
(`luplo.core.extract.pipeline`) when an item is superseded. The pipeline
runs a Gemma-based diff analysis over the old and new chain heads and
picks the most specific category that fits. It is not free-form text;
any value outside the seven above is rejected at write time.

## How to use it

### Notifications and review queues

Downstream sync drivers (not yet shipped — see {doc}`../guides/local-worker`)
filter by `semantic_impact` to decide whether to push a change. A
reasonable default is **`numeric_change`, `rule_addition`, `rule_removal`,
`rule_edit`, `scope_shift`** — anything that changes what the rule
*says*. `rationale_edit` is optional; `clerical` should never notify.

### History queries

From the CLI:

```bash
uv run lp items show <item-id>
# history is printed alongside the current chain head
```

From an MCP client:

```json
{
  "tool": "luplo_history_query",
  "args": {
    "project_id": "myapp",
    "since": "2026-04-10T00:00:00Z",
    "semantic_impacts": ["numeric_change", "rule_addition"]
  }
}
```

## Why seven, why these

A larger taxonomy drifts — edges between "rule_edit" and "rationale_edit"
are already fuzzy, and adding more categories multiplies the
disagreements. A smaller one collapses everything interesting into one
bucket. The seven categories are the minimum that splits what we want
to notify on from what we do not. See the related decision item (`4b911143`)
for the thinking.

## Related

- {doc}`../concepts/data-model` — where `items_history` lives in the
  schema.
- {doc}`../guides/local-worker` — the consumer of these tags when sync
  drivers ship.
