from __future__ import annotations

from luplo.core.import_pipeline.codeblock_strip import strip_fenced_blocks


def test_no_code_blocks_passthrough():
    text = "just prose with `inline code` and **emphasis**"
    assert strip_fenced_blocks(text) == text


def test_backtick_block_replaced_with_placeholder():
    text = "Before\n```python\nprint('hi')\n```\nAfter"
    out = strip_fenced_blocks(text)
    assert "print" not in out
    assert "[code:" in out  # placeholder marker present
    assert out.startswith("Before")
    assert out.endswith("After")


def test_tilde_block_also_stripped():
    text = "X\n~~~\nrust code\n~~~\nY"
    out = strip_fenced_blocks(text)
    assert "rust code" not in out
    assert "[code:" in out


def test_multiple_blocks_all_stripped():
    text = "p1\n```\na\n```\np2\n```\nb\n```\np3"
    out = strip_fenced_blocks(text)
    assert "a" not in out and "b" not in out
    assert out.count("[code:") == 2


def test_indented_inside_block_kept_inside_placeholder():
    text = "```\n    nested indent\n```"
    out = strip_fenced_blocks(text)
    assert "nested indent" not in out
    assert "[code:" in out


def test_unclosed_block_treated_as_block_to_eof():
    text = "Before\n```python\nno close fence to end of doc"
    out = strip_fenced_blocks(text)
    # graceful degrade: strip from fence to end and leave a placeholder
    assert "no close fence" not in out
    assert "[code:" in out


def test_inline_backtick_not_treated_as_block():
    text = "use `func()` for X"
    assert strip_fenced_blocks(text) == text
