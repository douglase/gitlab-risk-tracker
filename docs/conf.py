# Sphinx configuration for gitlab-risk-tracker docs.
# SPDX-License-Identifier: GPL-3.0-or-later

project = "gitlab-risk-tracker"
author = "Ewan Douglas and contributors"
copyright = "2026, Ewan Douglas and contributors"
release = "0.1"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
]

# Markdown support so we can include README-style content as .md too.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_show_sourcelink = False
