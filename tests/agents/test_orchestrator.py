"""
tests/agents/test_orchestrator.py

Static contract (template string), not runtime behavior.
"""

import pytest

from agents.orchestrator import build_orchestrator_prompt, ORCHESTRATOR_PROMPT_TEMPLATE

pytestmark = pytest.mark.unit


def test_prompt_contains_substituted_values():
    prompt = build_orchestrator_prompt("demo-project", "Django")
    assert "demo-project" in prompt
    assert "Django" in prompt


def test_prompt_does_not_leak_placeholder_braces():
    """Catches a broken .format() silently leaving braces in."""
    prompt = build_orchestrator_prompt("demo-project", "Django")
    assert "{project_slug}" not in prompt
    assert "{framework_name}" not in prompt


def test_prompt_contains_gate_status_field_guidance():
    """A prompt edit that drops this instruction would desync the agent
    from main.py's parser without any other test catching it."""
    prompt = build_orchestrator_prompt("demo-project", "Django")
    assert "**Gate status:**" in prompt


def test_prompt_contains_house_style_header_guidance():
    prompt = build_orchestrator_prompt("demo-project", "Django")
    assert '"##"' in prompt or "## main.py" in prompt


def test_template_itself_has_format_placeholders():
    assert "{project_slug}" in ORCHESTRATOR_PROMPT_TEMPLATE
    assert "{framework_name}" in ORCHESTRATOR_PROMPT_TEMPLATE
