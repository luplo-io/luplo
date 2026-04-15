"""Sphinx configuration for luplo documentation.

See https://www.sphinx-doc.org/en/master/usage/configuration.html for
the full list of options.
"""

from __future__ import annotations

# ── Project info ─────────────────────────────────────────────────

project = "luplo"
author = "hanyul99"
copyright = "2026, hanyul99"  # noqa: A001
release = "0.0.1"

# ── General config ───────────────────────────────────────────────

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "myst_parser",
    "autoapi.extension",
    "sphinx_design",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# ── Theme ────────────────────────────────────────────────────────

html_theme = "furo"
html_title = "luplo"

# ── Napoleon (Google-style docstrings, per CLAUDE.md convention) ─

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True

# ── AutoAPI (generate API reference from src/luplo) ──────────────

autoapi_type = "python"
autoapi_dirs = ["../src/luplo"]
autoapi_root = "api"
autoapi_add_toctree_entry = True
autoapi_keep_files = False
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
    "imported-members",
]

# ── MyST (Markdown) ──────────────────────────────────────────────

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

# ── Intersphinx ──────────────────────────────────────────────────

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
