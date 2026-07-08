"""
tests/conftest.py

Shared fixtures for the whole suite. Kept deliberately free of any
LangChain/deepagents mocking -- most of the suite (gates, config,
runtime, scripts) never imports those packages and shouldn't pay the
import cost. Anything specific to agents/ or main.py's integration test
lives in that tier's own conftest/fixtures instead.
"""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project_dir(tmp_path) -> Path:
    """A fake projects/<slug>/ tree with the real subdirectory shape."""
    root = tmp_path / "demo-project"
    for sub in (
        "target_repo",
        "framework_docs",
        "workspace/mappings",
        "workspace/notes",
    ):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def project_config(project_dir) -> dict:
    cfg = {
        "project_name": "demo-project",
        "framework_name": "Django",
        "target_repo": {"source": "local"},
        "framework_docs": {
            "source": "git",
            "git_url": "https://example.invalid/django/django.git",
            "ref": "stable/5.1.x",
            "subpath": "docs",
        },
        "fallback": {"enabled": True, "allowed_domains": ["docs.djangoproject.com"]},
        "external_reference_policy": "flag",
    }
    (project_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    return cfg


@pytest.fixture
def make_mapping_entry():
    """Factory for a well-formed mapping-entry dict (AGENTS.md house style)."""

    def _make(**overrides):
        entry = {
            "repo_reference": "app/models.py:10",
            "concept": "Django Model field",
            "doc_source": "framework_docs/topics/db/models.txt",
            "doc_source_tier": "local",
            "doc_snippet_claimed": "A field is used to store data",
        }
        entry.update(overrides)
        return entry

    return _make
