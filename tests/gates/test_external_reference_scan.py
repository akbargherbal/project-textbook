"""
tests/gates/test_external_reference_scan.py

Not a pass/fail gate -- a notifier. scan_file() and scan_and_log() are
tested separately.
"""

import pytest

from gates import external_reference_scan as ers

pytestmark = pytest.mark.unit


def _cfg(**overrides):
    cfg = {
        "external_reference_policy": "flag",
        "fallback": {"allowed_domains": ["docs.djangoproject.com"]},
    }
    cfg.update(overrides)
    return cfg


def test_extract_markdown_link_urls(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text("See [the docs](https://docs.djangoproject.com/topics/db/).")
    findings = ers.scan_file(doc, _cfg())
    assert len(findings) == 1
    assert findings[0]["url"] == "https://docs.djangoproject.com/topics/db/"


def test_extract_bare_angle_bracket_urls(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text("See <https://example.com/foo> for more.")
    findings = ers.scan_file(doc, _cfg())
    assert len(findings) == 1
    assert findings[0]["url"] == "https://example.com/foo"


def test_extract_rst_style_urls(project_dir):
    doc = project_dir / "framework_docs" / "a.rst"
    doc.write_text("See `the docs <https://example.com/rst-target>`_ for more.")
    findings = ers.scan_file(doc, _cfg())
    assert len(findings) == 1
    assert findings[0]["url"] == "https://example.com/rst-target"


def test_mixed_url_styles_in_single_file(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text(
        "See [markdown link](https://example.com/md).\n"
        "See <https://example.com/bare>.\n"
        "See `rst link <https://example.com/rst>`_.\n"
    )
    findings = ers.scan_file(doc, _cfg())
    urls = {f["url"] for f in findings}
    assert urls == {
        "https://example.com/md",
        "https://example.com/bare",
        "https://example.com/rst",
    }


def test_ignore_policy_returns_no_findings(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text("See [the docs](https://docs.djangoproject.com/topics/db/).")
    findings = ers.scan_file(doc, _cfg(external_reference_policy="ignore"))
    assert findings == []


def test_url_on_allowlist_is_flagged_may_fetch(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text("[docs](https://docs.djangoproject.com/topics/db/)")
    findings = ers.scan_file(doc, _cfg())
    assert findings[0]["in_fallback_allowlist"] is True
    assert "MAY fetch" in findings[0]["note"]


def test_url_not_on_allowlist_is_flagged_manual_review(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text("[blog](https://someblog.example.com/post)")
    findings = ers.scan_file(doc, _cfg())
    assert findings[0]["in_fallback_allowlist"] is False
    assert "Review manually" in findings[0]["note"]


def test_www_prefix_stripped_for_allowlist_match(project_dir):
    doc = project_dir / "framework_docs" / "a.md"
    doc.write_text("[docs](https://www.docs.djangoproject.com/topics/db/)")
    findings = ers.scan_file(doc, _cfg())
    assert findings[0]["in_fallback_allowlist"] is True


def test_scan_and_log_writes_file_with_one_section_per_source(
    project_dir, project_config
):
    project_config["fallback"]["allowed_domains"] = ["docs.djangoproject.com"]
    import yaml

    (project_dir / "config.yaml").write_text(yaml.safe_dump(project_config))

    (project_dir / "framework_docs" / "a.md").write_text(
        "[docs](https://docs.djangoproject.com/topics/db/)"
    )
    (project_dir / "framework_docs" / "b.md").write_text(
        "[other](https://someblog.example.com/post)"
    )

    findings = ers.scan_and_log(project_dir)
    assert len(findings) == 2

    log_path = project_dir / "workspace" / "notes" / "external_references.md"
    assert log_path.exists()
    content = log_path.read_text()
    assert content.count("## ") == 2
    assert str(project_dir / "framework_docs" / "a.md") in content
    assert str(project_dir / "framework_docs" / "b.md") in content


def test_scan_and_log_only_scans_md_rst_txt_mdx_files(project_dir, project_config):
    import yaml

    (project_dir / "config.yaml").write_text(yaml.safe_dump(project_config))

    (project_dir / "framework_docs" / "ignored.py").write_text(
        "# see https://docs.djangoproject.com/topics/db/\n"
        "URL = 'https://docs.djangoproject.com/topics/db/'\n"
    )
    findings = ers.scan_and_log(project_dir)
    assert findings == []
