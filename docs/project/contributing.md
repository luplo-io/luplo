# Contributing

luplo is AGPL-3.0-or-later with a CLA (not yet live for external
contributors). This page summarises the working agreement; the
canonical source is
[CONTRIBUTING.md](https://github.com/luplo-io/luplo/blob/main/CONTRIBUTING.md)
in the repo.

## Prerequisites

- Python 3.12+ (development runs on 3.14 via uv).
- [uv](https://docs.astral.sh/uv/) for package management.
- PostgreSQL 15+ — local install or Docker container.

## Setup

```bash
git clone https://github.com/luplo-io/luplo.git
cd luplo
uv sync --extra dev

# Database
createdb luplo
export LUPLO_DB_URL="postgresql://postgres@localhost/luplo"
uv run alembic upgrade head

# Smoke
uv run pytest
uv run lp --help
```

The `dev` extra pulls in `pytest`, `pytest-asyncio`, `ruff`, `pyright`,
and the test utilities.

## Running checks

All four must pass before submitting a PR:

```bash
uv run ruff check src tests          # lint
uv run ruff format --check src tests # formatting
uv run pyright src                   # strict type check
uv run pytest                        # tests
```

Auto-fix lint and formatting:

```bash
uv run ruff check --fix src tests
uv run ruff format src tests
```

## Code standards

Full list in
[CLAUDE.md](https://github.com/luplo-io/luplo/blob/main/CLAUDE.md)
under *Code standards (OSS grade)*. Short version:

- **English** everywhere — code, comments, docstrings, commit messages.
- **Google-style docstrings** on every public function and class.
- **pyright strict** — no `# type: ignore` in `src/`. Test files may
  use it sparingly for fixture typing.
- **ruff** — zero warnings. Line length 99.
- **Tests** — new core modules must have integration tests against a
  real PostgreSQL. Mock-only tests aren't enough.
- **No inline `TODO`** without a linked issue.
- **Imports** — isort-compatible ordering enforced by ruff.

## Commit format

[Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add glossary merge command
fix: handle NULL arrays in item listing
docs: update CLAUDE.md with search architecture
refactor: extract tsquery builder into separate module
test: add supersedes chain edge cases
chore: bump ruff to 0.8
```

## Pull requests

1. Fork and branch from `main`.
2. One logical change per PR. Stacked PRs are fine; monster PRs are not.
3. All four checks pass.
4. A PR description that explains *why* — the *what* is visible in the
   diff.

## Testing against a real database

The test suite runs against PostgreSQL. `tests/conftest.py` creates a
`luplo_test` database on session start and drops it on teardown. To
override the target DB:

```bash
export LUPLO_TEST_DB_URL="postgresql://user:pass@localhost/my_test_db"
```

We do not accept PRs whose coverage is entirely mocked — see the
rationale in the project decision log for why mocked database tests have
burned us before.

## Proposing design changes

luplo has a small, opinionated core (see {doc}`../concepts/philosophy`).
Before opening a PR that:

- adds a plugin / extension API,
- introduces auto-extraction or auto-injection,
- changes search to be vector-first,

…open an issue or discussion first. The answer is often "we explicitly
rejected this — here is the recorded rationale". If the situation has
changed, say so in the issue and we can supersede the decision.

## License and CLA

By contributing you agree your contributions are licensed under
[AGPL-3.0-or-later](license.md). A CLA will be required for external
contributions; it is not yet wired up.

## Related

- {doc}`../concepts/philosophy` — the commitments a proposal has to
  survive.
- {doc}`changelog` — what each release changed.
