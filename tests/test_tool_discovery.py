from __future__ import annotations

import inspect

from maya_mcp.server import OperationsManager
from maya_mcp.tool_contracts import collect_tool_contracts
from mayatools.scene.clear_selection_list import clear_selection_list


def test_find_tools_discovers_current_toolset() -> None:
    manager = OperationsManager()
    manager.find_tools()

    tools = {tool.name for tool in manager.get_tools()}
    assert len(tools) >= 100
    assert "audit_scene_strings" in tools
    assert "setup_turntable_preview_scene" in tools
    assert "select_mesh_by_region" in tools
    assert "split_mesh_edges" in tools
    assert "results" not in tools


def test_select_mesh_silhouette_schema_includes_width_filter() -> None:
    manager = OperationsManager()
    manager.find_tools()

    tool = next(tool for tool in manager.get_tools() if tool.name == "select_mesh_silhouette_components")
    properties = tool.inputSchema["properties"]

    assert "min_projected_width" in properties


def test_compare_image_silhouettes_schema_includes_row_sample_filters() -> None:
    manager = OperationsManager()
    manager.find_tools()

    tool = next(tool for tool in manager.get_tools() if tool.name == "compare_image_silhouettes")
    properties = tool.inputSchema["properties"]

    assert "row_sample_sort" in properties
    assert "row_sample_min_abs_error" in properties
    assert "max_row_samples" in properties


def test_clear_selection_list_has_standard_return_contract() -> None:
    manager = OperationsManager()
    manager.find_tools()

    tool = next(tool for tool in manager.get_tools() if tool.name == "clear_selection_list")

    assert "Clear the user selection list" in tool.description
    assert inspect.signature(clear_selection_list).return_annotation not in {
        inspect.Signature.empty,
        None,
    }


def test_tool_contracts_are_clean_for_current_sources() -> None:
    report = collect_tool_contracts()

    assert report["tool_count"] >= 100
    assert report["success"], report["issues"]
    assert report["issue_count"] == 0
