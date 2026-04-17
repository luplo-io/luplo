# Rule pack (`lp check`)

The rule pack is a set of deterministic, read-only checks that run
over the item graph and report findings. Rules are SQL+Python only —
no LLM, no external network. Hallucinated compliance judgements are
a liability, not a feature.

The set is fixed per release: there is no plugin runtime. Adding a
rule is a code change, a PR, and a doc update — by design.

## Severity levels

- `error` — blocks `lp check` exit code (non-zero if any finding has
  severity error).
- `warn` — surfaced but does not block.
- `info` — advisory, hidden below the default severity threshold.

All rules operate only on **current heads** of supersede chains —
historical rows that have been superseded are considered retired and
are skipped.

## Rules shipped in v0.6

### `missing_rationale` — severity `error`

Flags `decision` items whose rationale is either NULL or under 20
characters after trimming. A decision with no reasoning attached is a
future self asking "why?" with no answer.

Tune the minimum length by editing
`src/luplo/core/checks/rules/missing_rationale.py:MIN_LENGTH` (not
configurable from `.luplo` — a team that wants a different floor is
making a durable choice, not a per-project tweak).

### `undated_retention` — severity `warn`

Flags `policy` items whose title or body mentions `PII`, `retention`,
`personal data`, or `personally identifiable`, and which have neither
an `expires_at` timestamp nor a `retention_days` tag.

The keyword list is small on purpose — growing it is a rule change,
not a config change. A false positive is fixable by adding a
`retention_days` tag to the policy. A false negative (a real
retention concern the keyword list missed) should prompt adding
the keyword, in code.

### `dangling_edge` — severity `warn`

Flags every link whose target item has been soft-deleted. Soft-deleted
items stay in the database for audit, but an active edge pointing at
one is almost always stale: either the caller should remove the edge,
or the delete should be reversed.

### `unresolved_conflict` — severity `warn`

Flags pairs connected by a `conflicts` edge where the edge is older
than 30 days and neither side has been superseded. A conflict older
than 30 days that nobody resolved means the team is living with two
rules in force, and someone will eventually guess which one wins.

The 30-day threshold is a constant in
`src/luplo/core/checks/rules/unresolved_conflict.py`.

### `unlinked_policy` — severity `info`

Flags `policy` items that no `decision` references (via any link
type, either direction). Orphan policies are either dead weight or
lore the team applies implicitly but has not recorded. Either way,
the audit trail is missing.

## Disabling a rule per project

Some rules are not useful in every project. Add the rule's name to
`[checks] disabled_rules` in `.luplo`:

```toml
[checks]
disabled_rules = ["undated_retention", "unlinked_policy"]
```

A rule listed here is skipped even when the caller explicitly asks
for it via `lp check --rule NAME`. The project-level disable is
the stronger signal.

## Invoking

### CLI

```bash
# Run every enabled rule, default threshold is warn.
lp check

# Run only specific rules.
lp check --rule missing_rationale --rule dangling_edge

# Include info-level findings.
lp check --severity info

# Only show errors (what CI should do).
lp check --severity error

# List all registered rules and exit.
lp check --list
```

Exit code is non-zero if any finding has severity `error`, regardless
of the display threshold.

### MCP

```python
luplo_check(project_id="myproj", rule="missing_rationale", severity="warn")
```

Returns markdown. The model may cite 8-character item id prefixes
from the output.

### HTTP

```
GET /checks?project_id=myproj&rule=missing_rationale
```

Returns `{findings: [...], count: int}`. Each finding has
`rule_name`, `severity`, `message`, `item_id` (nullable), and
`details` (rule-specific).

## What the rule pack is not

- **Not a compliance certification.** `lp check` reports signals the
  human can act on. It does not produce SOC 2 / ISO 27001 evidence.
- **Not an LLM "AI auditor".** Rules are deterministic SQL and a tiny
  bit of Python. Adding an LLM would swap clarity for hallucination.
- **Not a plugin runtime.** New rules land as code changes to this
  repository, with tests and docs alongside.
