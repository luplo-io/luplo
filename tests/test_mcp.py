"""Smoke tests for MCP server tool registration."""

from __future__ import annotations

from luplo.mcp import mcp


def test_mcp_server_has_name() -> None:
    assert mcp.name == "luplo"


def test_mcp_tools_registered() -> None:
    """Verify all expected tools are registered."""
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "luplo_work_open",
        "luplo_work_resume",
        "luplo_work_close",
        "luplo_item_upsert",
        "luplo_item_search",
        "luplo_brief",
        "luplo_page_sync",
        "luplo_history_query",
        "luplo_save_decisions",
        # Phase D — tasks
        "luplo_task_add",
        "luplo_task_list",
        "luplo_task_start",
        "luplo_task_done",
        "luplo_task_block",
        # Phase E — qa
        "luplo_qa_add",
        "luplo_qa_pass",
        "luplo_qa_fail",
        "luplo_qa_list_pending",
    }
    missing = expected - tool_names
    assert not missing, f"Missing MCP tools: {missing}"


def test_mcp_tool_count() -> None:
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 18
