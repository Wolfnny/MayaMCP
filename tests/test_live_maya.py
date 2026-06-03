from __future__ import annotations

import os
from pathlib import Path

import pytest

from maya_mcp.server import MayaConnection
from maya_mcp.paths import get_tools_directory


pytestmark = pytest.mark.live_maya


def _requires_live_maya() -> None:
    if os.environ.get("MAYA_MCP_LIVE") != "1":
        pytest.skip("Set MAYA_MCP_LIVE=1 to run Maya commandPort tests.")


def test_live_audit_scene_strings_detects_problem_strings() -> None:
    _requires_live_maya()
    connection = MayaConnection()
    state_script = r'''
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "success": True,
    "scene": cmds.file(query=True, sceneName=True) or "",
    "modified": bool(cmds.file(query=True, modified=True)),
})
'''
    state = connection.run_python_script(state_script)
    if state.get("modified"):
        pytest.skip("Current Maya scene has unsaved changes; live test will not replace it.")
    original_scene = state.get("scene") or ""
    setup_script = r'''
import json
import os
import tempfile
import maya.cmds as cmds
cmds.file(new=True, force=True)
cjk = "\u4e2d\u6587"
cjk_node_names = True
try:
    transform = cmds.polyCube(name="Coca" + cjk + "_transform")[0]
except Exception:
    cjk_node_names = False
    transform = cmds.polyCube(name="Coca_ascii_transform")[0]
if cjk_node_names:
    shape = (cmds.listRelatives(transform, shapes=True) or [""])[0]
    if shape:
        try:
            cmds.rename(shape, cjk + "_shape")
        except Exception:
            pass
material_name = cjk + "_material" if cjk_node_names else "ascii_material"
sg_name = cjk + "_sg" if cjk_node_names else "ascii_sg"
material = cmds.shadingNode("lambert", asShader=True, name=material_name)
shading_group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sg_name)
cmds.connectAttr(material + ".outColor", shading_group + ".surfaceShader", force=True)
cmds.sets(transform, edit=True, forceElement=shading_group)
file_node_name = cjk + "_file_texture" if cjk_node_names else "ascii_file_texture"
file_node = cmds.shadingNode("file", asTexture=True, name=file_node_name)
cmds.setAttr(file_node + ".fileTextureName", "C:/missing/" + cjk + "_texture.png", type="string")
scene_path = os.path.join(tempfile.gettempdir(), cjk + "_scene.ma").replace("\\", "/")
cmds.file(rename=scene_path)
if cjk_node_names:
    try:
        cmds.createDisplayLayer(name=cjk + "_display_layer", empty=True)
        cmds.sets(name=cjk + "_object_set")
        cmds.namespace(add=cjk + "namespace")
    except Exception:
        pass
_mcp_maya_results = json.dumps({"success": True, "cjk_node_names": cjk_node_names})
'''
    tool_path = Path(get_tools_directory()) / "scene" / "audit_scene_strings.py"
    try:
        setup_result = connection.run_python_script(setup_script)
        assert setup_result["success"] is True

        cjk_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "cjk", "max_results": 2000},
        )
        mid_cache = connection.run_cache_probe()
        second_cjk_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "cjk", "max_results": 2000},
        )
        after_cache = connection.run_cache_probe()

        assert cjk_result["success"] is False
        assert cjk_result["match_count"] > 0
        assert second_cjk_result["match_count"] == cjk_result["match_count"]
        assert after_cache["stats"]["loads"] == mid_cache["stats"]["loads"]
        assert after_cache["stats"]["hits"] > mid_cache["stats"]["hits"]
        assert any(match["category"] == "file_textures" for match in cjk_result["matches"])
        assert any(match["category"] == "scene" for match in cjk_result["matches"])
        assert any(match["path_exists"] is False for match in cjk_result["matches"])

        non_ascii_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "non_ascii", "max_results": 2000},
        )
        assert non_ascii_result["match_count"] >= cjk_result["match_count"]

        custom_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "custom", "pattern": "texture", "max_results": 2000},
        )
        assert custom_result["match_count"] >= 1
    finally:
        if original_scene:
            cleanup_script = f'''
import json
import maya.cmds as cmds
cmds.file({original_scene!r}, open=True, force=True)
_mcp_maya_results = json.dumps({{"success": True}})
'''
        else:
            cleanup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
_mcp_maya_results = json.dumps({"success": True})
'''
        connection.run_python_script(cleanup_script)


def test_live_tool_cache_reloads_when_source_hash_changes(tmp_path: Path) -> None:
    _requires_live_maya()
    connection = MayaConnection()
    tool_path = tmp_path / "cache_probe_tool.py"
    source_one = '''from typing import Any, Dict


def cache_probe_tool(value: int = 1) -> Dict[str, Any]:
    """Return a cache probe result."""
    return {"success": True, "value": value, "version": 1}
'''
    source_two = source_one.replace('"version": 1', '"version": 2')

    tool_path.write_text(source_one, encoding="utf-8")
    first = connection.call_tool("cache_probe_tool", str(tool_path), {"value": 5})
    first_cache = connection.run_cache_probe()

    tool_path.write_text(source_two, encoding="utf-8")
    second = connection.call_tool("cache_probe_tool", str(tool_path), {"value": 5})
    second_cache = connection.run_cache_probe()

    assert first["version"] == 1
    assert second["version"] == 2
    assert second_cache["stats"]["loads"] > first_cache["stats"]["loads"]


def test_live_tool_cache_invalidates_when_scene_opens(tmp_path: Path) -> None:
    _requires_live_maya()
    connection = MayaConnection()
    state_script = r'''
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "scene": cmds.file(query=True, sceneName=True) or "",
    "modified": bool(cmds.file(query=True, modified=True)),
})
'''
    state = connection.run_python_script(state_script)
    if state.get("modified"):
        pytest.skip("Current Maya scene has unsaved changes; live test will not replace it.")
    original_scene = state.get("scene") or ""
    tool_path = tmp_path / "scene_cache_probe_tool.py"
    tool_path.write_text(
        '''from typing import Any, Dict


def scene_cache_probe_tool(value: int = 1) -> Dict[str, Any]:
    """Return a cache scene invalidation probe result."""
    return {"success": True, "value": value}
''',
        encoding="utf-8",
    )
    try:
        first = connection.call_tool("scene_cache_probe_tool", str(tool_path), {"value": 7})
        before_open_cache = connection.run_cache_probe()
        open_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
_mcp_maya_results = json.dumps({"success": True})
'''
        opened = connection.run_python_script(open_script)
        assert opened["success"] is True
        after_open_cache = connection.run_cache_probe()
        second = connection.call_tool("scene_cache_probe_tool", str(tool_path), {"value": 9})
        after_second_cache = connection.run_cache_probe()

        assert first["value"] == 7
        assert second["value"] == 9
        assert after_open_cache["stats"]["scene_invalidations"] > before_open_cache["stats"].get(
            "scene_invalidations",
            0,
        )
        assert after_second_cache["stats"]["loads"] > after_open_cache["stats"]["loads"]
        assert after_second_cache["stats"]["misses"] > after_open_cache["stats"]["misses"]
    finally:
        if original_scene:
            cleanup_script = f'''
import json
import maya.cmds as cmds
cmds.file({original_scene!r}, open=True, force=True)
cmds.file(modified=False)
_mcp_maya_results = json.dumps({{"success": True}})
'''
        else:
            cleanup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
cmds.file(modified=False)
_mcp_maya_results = json.dumps({"success": True})
'''
        connection.run_python_script(cleanup_script)


def test_live_playblast_object_silhouette_preserves_clean_scene_modified_flag(tmp_path: Path) -> None:
    _requires_live_maya()
    connection = MayaConnection()
    state_script = r'''
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "scene": cmds.file(query=True, sceneName=True) or "",
    "modified": bool(cmds.file(query=True, modified=True)),
})
'''
    state = connection.run_python_script(state_script)
    if state.get("modified"):
        pytest.skip("Current Maya scene has unsaved changes; live test will not replace it.")
    original_scene = state.get("scene") or ""
    setup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
mesh = cmds.polyCube(name="mcp_silhouette_live_tmp", width=1.0, height=2.0, depth=0.75)[0]
cmds.file(modified=False)
_mcp_maya_results = json.dumps({
    "success": True,
    "mesh": mesh,
    "modified": bool(cmds.file(query=True, modified=True)),
})
'''
    query_modified_script = r'''
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "modified": bool(cmds.file(query=True, modified=True)),
    "selection": cmds.ls(selection=True, flatten=True) or [],
})
'''
    tool_path = Path(get_tools_directory()) / "scene" / "playblast_object_silhouette.py"
    output_path = tmp_path / "mcp_silhouette_live_tmp.png"
    try:
        setup = connection.run_python_script(setup_script)
        assert setup["success"] is True
        assert setup["modified"] is False

        result = connection.call_tool(
            "playblast_object_silhouette",
            str(tool_path),
            {
                "name": "mcp_silhouette_live_tmp",
                "target_objects": [setup["mesh"]],
                "output_path": str(output_path),
                "view_direction": [0.0, 0.0, -1.0],
                "up_axis": [0.0, 1.0, 0.0],
                "image_width": 128,
                "image_height": 192,
                "padding_fraction": 0.08,
            },
        )
        after = connection.run_python_script(query_modified_script)

        assert result["success"] is True
        assert Path(result["output_path"]).exists()
        assert after["modified"] is False
    finally:
        if original_scene:
            cleanup_script = f'''
import json
import maya.cmds as cmds
cmds.file({original_scene!r}, open=True, force=True)
cmds.file(modified=False)
_mcp_maya_results = json.dumps({{"success": True}})
'''
        else:
            cleanup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
cmds.file(modified=False)
_mcp_maya_results = json.dumps({"success": True})
'''
        connection.run_python_script(cleanup_script)


def test_live_map_silhouette_errors_reports_asymmetric_side_corrections() -> None:
    _requires_live_maya()
    connection = MayaConnection()
    state_script = r'''
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "scene": cmds.file(query=True, sceneName=True) or "",
    "modified": bool(cmds.file(query=True, modified=True)),
})
'''
    state = connection.run_python_script(state_script)
    if state.get("modified"):
        pytest.skip("Current Maya scene has unsaved changes; live test will not replace it.")
    original_scene = state.get("scene") or ""
    setup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
mesh = cmds.polyCube(name="mcp_map_silhouette_live_tmp", width=1.0, height=1.0, depth=1.0)[0]
cmds.file(modified=False)
_mcp_maya_results = json.dumps({"success": True, "mesh": mesh})
'''
    tool_path = Path(get_tools_directory()) / "scene" / "map_silhouette_errors_to_components.py"
    try:
        setup = connection.run_python_script(setup_script)
        assert setup["success"] is True

        result = connection.call_tool(
            "map_silhouette_errors_to_components",
            str(tool_path),
            {
                "target_objects": [setup["mesh"]],
                "row_width_samples": [
                    {
                        "row_normalized": 0.5,
                        "reference_width": 0.5,
                        "candidate_width": 0.51171875,
                        "signed_error": 0.01171875,
                        "abs_error": 0.01171875,
                        "left_error_pixels": 2,
                        "right_error_pixels": -1,
                        "center_error_pixels": 0.5,
                    }
                ],
                "candidate_canvas_bbox_pixels": [0, 0, 255, 511],
                "candidate_crop_bbox_pixels": [0, 0, 127, 191],
                "candidate_foreground_bbox_pixels": [0, 0, 127, 191],
                "view_direction": [0.0, 0.0, -1.0],
                "up_axis": [0.0, 1.0, 0.0],
                "camera_center": [0.0, 0.0, 0.0],
                "orthographic_width": 4.0,
                "image_width": 128,
                "image_height": 192,
                "compare_width": 256,
                "compare_height": 512,
                "min_abs_error": 0.001,
                "max_rows": 1,
                "row_band_pixels": 8.0,
                "component_detail": "all",
                "side_component_band_world": 0.25,
                "select_components": False,
            },
        )

        assert result["success"] is True
        assert result["mapped_row_count"] == 1
        row = result["rows"][0]
        assert row["left_error_pixels"] == pytest.approx(2.0)
        assert row["right_error_pixels"] == pytest.approx(-1.0)
        assert row["left_side_error_world"] > 0.0
        assert row["right_side_error_world"] < 0.0
        assert row["suggested_left_side_correction_vector_world"][0] < 0.0
        assert row["suggested_right_side_correction_vector_world"][0] > 0.0
    finally:
        if original_scene:
            cleanup_script = f'''
import json
import maya.cmds as cmds
cmds.file({original_scene!r}, open=True, force=True)
cmds.file(modified=False)
_mcp_maya_results = json.dumps({{"success": True}})
'''
        else:
            cleanup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
cmds.file(modified=False)
_mcp_maya_results = json.dumps({"success": True})
'''
        connection.run_python_script(cleanup_script)


def test_live_split_mesh_edges_places_ratio_vertex() -> None:
    _requires_live_maya()
    connection = MayaConnection()
    setup_script = r'''
import json
import re
import maya.cmds as cmds
try:
    cmds.delete("mcp_split_live_tmp")
except Exception:
    pass
mesh = cmds.polyCreateFacet(
    name="mcp_split_live_tmp",
    point=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
)[0]
line = (cmds.polyInfo(mesh + ".e[0]", edgeToVertex=True) or [""])[0]
ids = [int(value) for value in re.findall(r"\d+", line)][1:]
points = [cmds.xform(mesh + ".vtx[%d]" % index, query=True, worldSpace=True, translation=True) for index in ids]
expected = [points[0][i] + (points[1][i] - points[0][i]) * 0.25 for i in range(3)]
_mcp_maya_results = json.dumps({"success": True, "mesh": mesh, "expected": expected})
'''
    cleanup_script = r'''
import json
import maya.cmds as cmds
try:
    cmds.delete("mcp_split_live_tmp")
except Exception:
    pass
_mcp_maya_results = json.dumps({"success": True})
'''
    tool_path = Path(get_tools_directory()) / "object" / "split_mesh_edges.py"
    try:
        setup = connection.run_python_script(setup_script)
        assert setup["success"] is True

        result = connection.call_tool(
            "split_mesh_edges",
            str(tool_path),
            {
                "object_name": setup["mesh"],
                "indices": [0],
                "position_mode": "ratio",
                "ratio": 0.25,
                "select_result": True,
            },
        )

        assert result["success"] is True
        assert result["new_vertex_count"] == 1
        assert result["ngon_count_after"] >= result["ngon_count_before"]
        assert result["new_ngon_count_delta"] == 1
        edited = result["edited_vertices_preview"][0]
        for actual, expected in zip(edited["after"], setup["expected"]):
            assert actual == pytest.approx(expected, abs=1.0e-6)
    finally:
        connection.run_python_script(cleanup_script)


def test_live_inspect_mesh_rings_reports_matched_targets() -> None:
    _requires_live_maya()
    connection = MayaConnection()
    setup_script = r'''
import json
import maya.cmds as cmds
was_modified = bool(cmds.file(query=True, modified=True))
try:
    cmds.delete("mcp_ring_live_tmp")
except Exception:
    pass
mesh = cmds.polyCube(name="mcp_ring_live_tmp", width=1.0, height=1.0, depth=1.0)[0]
_mcp_maya_results = json.dumps({"success": True, "mesh": mesh, "was_modified": was_modified})
'''
    cleanup_template = r'''
import json
import maya.cmds as cmds
try:
    cmds.delete("mcp_ring_live_tmp")
except Exception:
    pass
if not {was_modified!r}:
    try:
        cmds.file(modified=False)
    except Exception:
        pass
_mcp_maya_results = json.dumps({{"success": True}})
'''
    tool_path = Path(get_tools_directory()) / "object" / "inspect_mesh_rings_by_axis.py"
    setup = connection.run_python_script(setup_script)
    try:
        assert setup["success"] is True
        result = connection.call_tool(
            "inspect_mesh_rings_by_axis",
            str(tool_path),
            {
                "object_name": setup["mesh"],
                "axis": "y",
                "mode": "nearest",
                "targets": [-0.49, 0.49],
                "group_tolerance": 0.001,
                "min_components_per_group": 4,
                "include_components": False,
                "max_preview": 0,
            },
        )

        assert result["success"] is True
        assert result["returned_group_count"] == 2
        for group in result["groups"]:
            assert group["matched_targets"]
            assert group["target_distances"]
            assert group["target_distances"][0]["distance"] == pytest.approx(0.01, abs=1.0e-6)
    finally:
        connection.run_python_script(cleanup_template.format(was_modified=setup.get("was_modified", True)))
