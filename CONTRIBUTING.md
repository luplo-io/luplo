# Contributing to luplo

Thanks for your interest in contributing to luplo. This guide covers everything
you need to get started.

## Prerequisites

- **Python 3.12+** (dev on 3.14)
- **[uv](https://docs.astral.sh/uv/)** for package management
- **PostgreSQL 15+** running locally or in Docker

## Setup

```bash
git clone https://github.com/luplo-io/cli.git luplo
cd luplo
uv sync --extra dev

# Database
createdb luplo       # or use your existing PG
export LUPLO_DB_URL="postgresql://postgres:localdb@localhost/luplo"
alembic upgrade head

# Verify
uv run pytest
uv run lp --help
```

## Running checks

All four must pass before submitting a PR:

```bash
uv run ruff check src tests        # lint
uv run ruff format --check src tests   # format
uv run pyright src                 # type check
uv run pytest                      # tests
```

Auto-fix lint and format issues:

```bash
uv run ruff check --fix src tests
uv run ruff format src tests
```

## Code standards

See the full list in [CLAUDE.md](CLAUDE.md) under "Code standards (OSS grade)".

Summary:

- **English** for all code, comments, docstrings, and commit messages
- **Google-style docstrings** on all public functions
- **pyright strict** — no `# type: ignore` (except test files for fixture typing)
- **ruff** — zero warnings
- **pytest** — new core modules must include integration tests

## Commit format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add glossary merge command
fix: handle NULL arrays in item listing
docs: update CLAUDE.md with search architecture
refactor: extract tsquery builder into separate module
test: add supersedes chain edge cases
```

## Pull requests

1. Fork the repo and create a feature branch from `main`
2. One logical change per PR
3. All checks must pass (lint, format, type check, tests)
4. Write a clear description of what changed and why
5. Link related issues if applicable

## Testing

Tests run against a real PostgreSQL database. The test infrastructure
(`tests/conftest.py`) creates a `luplo_test` database automatically and
drops it after the session.

Override the test database URL:

```bash
export LUPLO_TEST_DB_URL="postgresql://user:pass@localhost/my_test_db"
```

## License

By contributing, you agree that your contributions will be licensed under the
[AGPL-3.0-or-later](LICENSE) license. A CLA will be required for external
contributions (not yet set up).
