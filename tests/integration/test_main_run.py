"""
tests/integration/test_main_run.py

Only the deepagents/model/checkpointer boundary is mocked -- real gates
(structural_check, citation_validator, freshness_check) and real parsing
(parse_markdown_mapping/parse_mappings_from_text) run against on-disk
fixtures.
"""
from pathlib import Path
from unittest import mock

import pytest
import yaml

import main

pytestmark = pytest.mark.integration


def _make_project(tmp_path, project_slug="demo-project", fallback_enabled=False):
    project_dir = tmp_path / project_slug
    for sub in ("target_repo", "framework_docs", "workspace/mappings", "workspace/notes"):
        (project_dir / sub).mkdir(parents=True)
    cfg = {
        "project_name": project_slug,
        "framework_name": "Django",
        "target_repo": {"source": "local"},
        "framework_docs": {"source": "local"},
        "fallback": {"enabled": fallback_enabled, "allowed_domains": []},
        "external_reference_policy": "ignore",
    }
    (project_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    return project_dir, cfg


def _settled_result(messages=None):
    result = mock.MagicMock()
    result.interrupts = []
    result.value = {"messages": messages or []}
    return result


def test_passed_and_flagged_entries_are_persisted_correctly(
    project_dir, project_config, mocker
):
    # Arrange: a real target_repo file the structural gate can verify
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "target_repo" / "requirements.txt").write_text(
        "Django==5.1.4\n"
    )
    (project_dir / "framework_docs" / "topics").mkdir()
    (project_dir / "framework_docs" / "topics" / "models.txt").write_text(
        "A field is used to store data on a model."
    )

    good_entry = (
        "## app.py:1\n"
        "**Concept:** assignment\n"
        "**Doc source:** framework_docs/topics/models.txt\n"
        "**Doc source tier:** local\n"
        "**Doc snippet:** A field is used to store data\n"
    )
    bad_entry = (
        "## does_not_exist.py:1\n"
        "**Concept:** ghost\n"
        "**Doc source:** framework_docs/topics/models.txt\n"
        "**Doc source tier:** local\n"
        "**Doc snippet:** A field is used to store data\n"
    )
    (project_dir / "workspace" / "mappings" / "app_py.md").write_text(good_entry)
    (project_dir / "workspace" / "mappings" / "ghost.md").write_text(bad_entry)

    # Mock everything at the deepagents/model boundary
    mocker.patch("main.PROJECTS_DIR", project_dir.parent)
    mocker.patch("main.get_model", return_value=mocker.MagicMock())
    mocker.patch("main.scan_and_log")
    mocker.patch("main.get_checkpointer", return_value=mocker.MagicMock())
    fake_logger = mocker.MagicMock()
    fake_logger.calls = [
        {
            "name": "read_file",
            "inputs": {"file_path": "projects/demo-project/framework_docs/topics/models.txt"},
            "output": "A field is used to store data on a model.",
        }
    ]
    mocker.patch("main.ToolCallLogger", return_value=fake_logger)
    fake_agent = mocker.MagicMock()
    fake_agent.invoke.return_value = mocker.MagicMock(
        interrupts=[], value={"messages": []}
    )
    mocker.patch("main.create_deep_agent", return_value=fake_agent)

    main.run("demo-project", "investigate")

    assert (project_dir / "workspace" / "mappings" / "app_py.md").exists()
    assert not (project_dir / "workspace" / "mappings" / "ghost.md").exists()
    flagged = (project_dir / "workspace" / "notes" / "flagged.md").read_text()
    assert "does_not_exist.py" in flagged


def test_missing_target_repo_exits_before_agent_constructed(tmp_path, mocker):
    project_dir, _ = _make_project(tmp_path)
    # Remove target_repo/ entirely (empty framework_docs/ too by default,
    # but target_repo is checked first).
    import shutil
    shutil.rmtree(project_dir / "target_repo")

    mocker.patch("main.PROJECTS_DIR", tmp_path)
    mock_create = mocker.patch("main.create_deep_agent")

    with pytest.raises(SystemExit) as exc_info:
        main.run("demo-project", "investigate")

    assert exc_info.value.code == 1
    mock_create.assert_not_called()


def test_missing_framework_docs_exits_before_agent_constructed(tmp_path, mocker):
    project_dir, _ = _make_project(tmp_path)
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    # framework_docs/ exists but is empty -> also fails the check.

    mocker.patch("main.PROJECTS_DIR", tmp_path)
    mock_create = mocker.patch("main.create_deep_agent")

    with pytest.raises(SystemExit) as exc_info:
        main.run("demo-project", "investigate")

    assert exc_info.value.code == 1
    mock_create.assert_not_called()


def test_run_until_settled_loops_through_multiple_interrupts(tmp_path, mocker):
    project_dir, _ = _make_project(tmp_path)
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "framework_docs" / "x.txt").write_text("hi")

    mocker.patch("main.PROJECTS_DIR", tmp_path)
    mocker.patch("main.get_model", return_value=mocker.MagicMock())
    mocker.patch("main.scan_and_log")
    mocker.patch("main.get_checkpointer", return_value=mocker.MagicMock())
    mocker.patch("main.ToolCallLogger", return_value=mocker.MagicMock(calls=[]))
    mocker.patch("builtins.input", return_value="approve")

    fake_agent = mocker.MagicMock()
    interrupted_result = mocker.MagicMock()
    interrupted_result.interrupts = [mocker.MagicMock(value={
        "action_requests": [{"name": "write_file", "args": {}}],
        "review_configs": [],
    })]
    settled_result = _settled_result()
    fake_agent.invoke.side_effect = [interrupted_result, settled_result]
    mocker.patch("main.create_deep_agent", return_value=fake_agent)

    main.run("demo-project", "investigate")

    assert fake_agent.invoke.call_count == 2
    # second_call is a positional Command(resume=...) -- verify via args
    second_call_args = fake_agent.invoke.call_args_list[1][0]
    assert second_call_args[0].resume == {"decisions": [{"type": "approve"}]}


def test_resume_with_pending_interrupt_prompts_and_uses_command_resume(tmp_path, mocker):
    project_dir, _ = _make_project(tmp_path)
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "framework_docs" / "x.txt").write_text("hi")
    (project_dir / "workspace" / ".last_thread_id").write_text("existing-thread-id")

    mocker.patch("main.PROJECTS_DIR", tmp_path)
    mocker.patch("main.get_model", return_value=mocker.MagicMock())
    mocker.patch("main.scan_and_log")
    mocker.patch("main.get_checkpointer", return_value=mocker.MagicMock())
    mocker.patch("main.ToolCallLogger", return_value=mocker.MagicMock(calls=[]))
    mocker.patch("builtins.input", return_value="approve")

    fake_agent = mocker.MagicMock()
    fake_task = mocker.MagicMock()
    fake_task.interrupts = [mocker.MagicMock(value={
        "action_requests": [{"name": "write_file", "args": {}}],
        "review_configs": [],
    })]
    pending_state = mocker.MagicMock()
    pending_state.tasks = [fake_task]
    fake_agent.get_state.return_value = pending_state
    fake_agent.invoke.return_value = _settled_result()
    mocker.patch("main.create_deep_agent", return_value=fake_agent)

    main.run("demo-project", "investigate", resume=True)

    assert fake_agent.invoke.call_count == 1
    call_args = fake_agent.invoke.call_args[0]
    assert call_args[0].resume == {"decisions": [{"type": "approve"}]}


def test_resume_with_no_interrupt_but_pending_next_resumes_with_none_input(tmp_path, mocker):
    project_dir, _ = _make_project(tmp_path)
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "framework_docs" / "x.txt").write_text("hi")
    (project_dir / "workspace" / ".last_thread_id").write_text("existing-thread-id")

    mocker.patch("main.PROJECTS_DIR", tmp_path)
    mocker.patch("main.get_model", return_value=mocker.MagicMock())
    mocker.patch("main.scan_and_log")
    mocker.patch("main.get_checkpointer", return_value=mocker.MagicMock())
    mocker.patch("main.ToolCallLogger", return_value=mocker.MagicMock(calls=[]))

    fake_agent = mocker.MagicMock()
    pending_state = mocker.MagicMock()
    pending_state.tasks = []
    pending_state.next = ("some_node",)
    fake_agent.get_state.return_value = pending_state
    fake_agent.invoke.return_value = _settled_result()
    mocker.patch("main.create_deep_agent", return_value=fake_agent)

    main.run("demo-project", "investigate", resume=True)

    assert fake_agent.invoke.call_count == 1
    call_args = fake_agent.invoke.call_args[0]
    assert call_args[0] is None


def test_resume_with_no_pending_work_starts_fresh_task_on_same_thread(tmp_path, mocker):
    project_dir, _ = _make_project(tmp_path)
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "framework_docs" / "x.txt").write_text("hi")
    (project_dir / "workspace" / ".last_thread_id").write_text("existing-thread-id")

    mocker.patch("main.PROJECTS_DIR", tmp_path)
    mocker.patch("main.get_model", return_value=mocker.MagicMock())
    mocker.patch("main.scan_and_log")
    mocker.patch("main.get_checkpointer", return_value=mocker.MagicMock())
    mocker.patch("main.ToolCallLogger", return_value=mocker.MagicMock(calls=[]))

    fake_agent = mocker.MagicMock()
    pending_state = mocker.MagicMock()
    pending_state.tasks = []
    pending_state.next = ()
    fake_agent.get_state.return_value = pending_state
    fake_agent.invoke.return_value = _settled_result()
    mocker.patch("main.create_deep_agent", return_value=fake_agent)

    main.run("demo-project", "a fresh task description", resume=True)

    assert fake_agent.invoke.call_count == 1
    call_args = fake_agent.invoke.call_args[0]
    assert call_args[0] == {
        "messages": [{"role": "user", "content": "a fresh task description"}]
    }