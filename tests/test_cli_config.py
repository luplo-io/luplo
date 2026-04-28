"""Tests for CLI config helpers (``_cfg_*``)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_cfg_language_returns_value_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".luplo").write_text(
        """
[backend]
type = "local"
db_url = "postgresql://localhost/luplo"

[project]
id = "test"
name = "test"
language = "ko"

[actor]
id = "00000000-0000-0000-0000-000000000000"
name = "x"
email = "x@example.com"
"""
    )
    from luplo.cli import _cfg_language

    assert _cfg_language() == "ko"


def test_cfg_language_returns_none_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".luplo").write_text(
        """
[backend]
type = "local"
db_url = "postgresql://localhost/luplo"

[project]
id = "test"
name = "test"

[actor]
id = "00000000-0000-0000-0000-000000000000"
name = "x"
email = "x@example.com"
"""
    )
    from luplo.cli import _cfg_language

    assert _cfg_language() is None


def test_cfg_language_flag_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".luplo").write_text(
        """
[backend]
type = "local"
db_url = "postgresql://localhost/luplo"

[project]
id = "test"
name = "test"
language = "ko"

[actor]
id = "00000000-0000-0000-0000-000000000000"
name = "x"
email = "x@example.com"
"""
    )
    from luplo.cli import _cfg_language

    assert _cfg_language("en") == "en"
