"""
tests/config/test_permissions.py

Testing a list of declarative rules, not an enforcement engine (that's
inside deepagents, out of scope). Assert on the shape and ordering of
PERMISSIONS directly.
"""

import pytest

from config.permissions import PERMISSIONS

pytestmark = pytest.mark.unit


def _index_of_rule_matching(paths_subset):
    """Return the index of the first rule whose `paths` list contains
    every path in paths_subset."""
    for i, rule in enumerate(PERMISSIONS):
        if all(p in rule.paths for p in paths_subset):
            return i
    return None


def test_permissions_is_a_list():
    assert isinstance(PERMISSIONS, list)
    assert len(PERMISSIONS) > 0


def test_each_rule_has_required_shape():
    for rule in PERMISSIONS:
        assert hasattr(rule, "paths")
        assert hasattr(rule, "operations")
        assert hasattr(rule, "mode")
        assert isinstance(rule.paths, list) and len(rule.paths) > 0
        assert isinstance(rule.operations, list) and len(rule.operations) > 0
        assert rule.mode in ("allow", "deny")


def test_gates_and_scripts_write_deny_rule_before_catchall_read_allow():
    """First-match-wins order matters: the gates/**  /  scripts/** write-
    deny rule must appear before the catch-all /** read-allow rule, so a
    future edit that reorders the list is caught."""
    gates_scripts_idx = _index_of_rule_matching(["/gates/**", "/scripts/**"])
    assert (
        gates_scripts_idx is not None
    ), "no rule found covering /gates/** and /scripts/**"

    catchall_read_idx = None
    for i, rule in enumerate(PERMISSIONS):
        if rule.paths == ["/**"] and rule.mode == "allow" and "read" in rule.operations:
            catchall_read_idx = i
            break
    assert catchall_read_idx is not None, "no catch-all /** read-allow rule found"

    assert gates_scripts_idx < catchall_read_idx


def test_project_source_of_truth_write_deny_rule_exists():
    """There is at least one write-deny rule covering config.yaml,
    target_repo/**, and framework_docs/** together (guards the 'agent
    cannot widen its own doc sources' invariant)."""
    required_paths = {
        "/projects/*/config.yaml",
        "/projects/*/target_repo/**",
        "/projects/*/framework_docs/**",
    }
    found = False
    for rule in PERMISSIONS:
        if (
            required_paths.issubset(set(rule.paths))
            and rule.mode == "deny"
            and "write" in rule.operations
        ):
            found = True
            break
    assert (
        found
    ), "no write-deny rule covers config.yaml + target_repo/** + framework_docs/** together"


def test_final_catchall_write_deny_rule_exists():
    """There is a final catch-all write-deny on /** -- the specific gap-
    closer for 'unmatched operations default to allowed.' If it's
    missing, this test should fail loudly, not silently pass."""
    found = any(
        rule.paths == ["/**"] and rule.mode == "deny" and "write" in rule.operations
        for rule in PERMISSIONS
    )
    assert found, "no catch-all /** write-deny rule found"


def test_gates_scripts_rule_before_source_of_truth_deny_is_not_required_but_source_of_truth_deny_before_catchall_write_deny():
    """The project source-of-truth write-deny rule should appear before
    the final catch-all write-deny rule (both deny writes, but the more
    specific rule existing separately documents intent; ordering across
    deny rules of the same mode doesn't change behavior, but the
    catch-all must still come after in list position per the module's
    own comment about being the 'gap-closer')."""
    required_paths = {
        "/projects/*/config.yaml",
        "/projects/*/target_repo/**",
        "/projects/*/framework_docs/**",
    }
    source_idx = None
    catchall_write_idx = None
    for i, rule in enumerate(PERMISSIONS):
        if (
            required_paths.issubset(set(rule.paths))
            and rule.mode == "deny"
            and "write" in rule.operations
        ):
            source_idx = i
        if rule.paths == ["/**"] and rule.mode == "deny" and "write" in rule.operations:
            catchall_write_idx = i
    assert source_idx is not None and catchall_write_idx is not None
    assert source_idx < catchall_write_idx


def test_workspace_is_read_write_allowed():
    found = any(
        rule.paths == ["/projects/*/workspace/**"]
        and rule.mode == "allow"
        and set(rule.operations) >= {"read", "write"}
        for rule in PERMISSIONS
    )
    assert found, "no read/write-allow rule found for /projects/*/workspace/**"


def test_import_without_deepagents_installed(monkeypatch):
    """If deepagents.FilesystemPermission isn't importable in the test
    environment, config.permissions should still be exercisable -- mock
    it as a simple dataclass with paths/operations/mode fields rather
    than skipping this test file on ImportError."""
    import sys
    import types
    import importlib
    import dataclasses

    fake_deepagents = types.ModuleType("deepagents")

    @dataclasses.dataclass
    class FakeFilesystemPermission:
        paths: list
        operations: list
        mode: str = "allow"

    fake_deepagents.FilesystemPermission = FakeFilesystemPermission
    monkeypatch.setitem(sys.modules, "deepagents", fake_deepagents)

    # Force a fresh import of config.permissions against the faked module.
    monkeypatch.delitem(sys.modules, "config.permissions", raising=False)
    fresh_permissions = importlib.import_module("config.permissions")
    importlib.reload(fresh_permissions)

    assert isinstance(fresh_permissions.PERMISSIONS, list)
    assert len(fresh_permissions.PERMISSIONS) == len(PERMISSIONS)

    # Clean up: remove the faked module and reload the real one so later
    # tests in the same session see the real deepagents-backed PERMISSIONS.
    monkeypatch.delitem(sys.modules, "config.permissions", raising=False)
    monkeypatch.delitem(sys.modules, "deepagents", raising=False)
    importlib.import_module("config.permissions")
