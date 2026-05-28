from typing import Dict, List, Any, Union


def refresh_file_textures(
    file_nodes: Union[str, List[str]] = None,
    validate_paths: bool = True,
    normalize_paths: bool = True,
    force_reload: bool = True,
    reset_viewport: bool = True,
) -> Dict[str, Any]:
    """Refresh Maya file texture nodes and viewport texture display.

    This is a generic utility for scenes reopened from disk, imported assets,
    swapped texture files, or stale VP2 previews. It can re-enable file loading,
    optionally normalize texture paths, touch fileTextureName to force node
    dirtiness, and reset/refresh the viewport so textured materials show in
    playblasts.
    """
    import os
    import maya.cmds as cmds
    import maya.mel as mel

    def _normalize_nodes(nodes):
        if nodes is None:
            return cmds.ls(type="file") or []
        if isinstance(nodes, str):
            nodes = [nodes]
        if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
            raise ValueError("file_nodes must be a string, a list of strings, or None.")
        for node in nodes:
            if not cmds.objExists(node):
                raise ValueError(f"File texture node does not exist: {node}")
            if cmds.objectType(node) != "file":
                raise ValueError(f"Node is not a Maya file texture node: {node}")
        return nodes

    def _normalize_maya_path(path):
        return os.path.normpath(path).replace("\\", "/")

    nodes = _normalize_nodes(file_nodes)
    refreshed = []
    missing = []
    errors = []
    viewport_reset = {"panels": []}

    def _reload_viewport_textures():
        actions = []
        try:
            mel.eval("ogs -reloadTextures;")
            actions.append({"action": "ogs_reloadTextures"})
        except Exception as exc:
            actions.append({"action": "ogs_reloadTextures", "error": str(exc)})
        return actions

    if reset_viewport:
        try:
            mel.eval("ogs -reset;")
            viewport_reset["actions"] = [{"action": "ogs_reset"}]
        except Exception as exc:
            viewport_reset["error"] = str(exc)

    for node in nodes:
        try:
            path = cmds.getAttr(f"{node}.fileTextureName") or ""
            clean_path = _normalize_maya_path(path) if path and normalize_paths else path
            exists = bool(clean_path and os.path.exists(clean_path))
            if validate_paths and not exists:
                missing.append({"node": node, "path": clean_path})

            if cmds.attributeQuery("disableFileLoad", node=node, exists=True):
                cmds.setAttr(f"{node}.disableFileLoad", 0)

            if clean_path:
                if normalize_paths and clean_path != path:
                    cmds.setAttr(f"{node}.fileTextureName", clean_path, type="string")
                if force_reload:
                    cmds.setAttr(f"{node}.fileTextureName", clean_path, type="string")
                    reload_actions = [{"action": "fileTextureName_touch"}]
                else:
                    reload_actions = []
            else:
                reload_actions = []

            try:
                cmds.dgdirty(node)
            except Exception:
                pass

            refreshed.append({
                "node": node,
                "path": clean_path,
                "exists": exists,
                "reload_actions": reload_actions,
            })
        except Exception as exc:
            errors.append({"node": node, "message": str(exc)})

    viewport_reload_actions = _reload_viewport_textures() if force_reload or reset_viewport else []
    for item in refreshed:
        item["viewport_reload_actions"] = viewport_reload_actions

    if reset_viewport:
        try:
            cmds.refresh(force=True)
        except Exception:
            pass

    return {
        "success": len(errors) == 0 and (not validate_paths or len(missing) == 0),
        "file_nodes": nodes,
        "refreshed": refreshed,
        "missing": missing,
        "errors": errors,
        "validate_paths": bool(validate_paths),
        "normalize_paths": bool(normalize_paths),
        "force_reload": bool(force_reload),
        "reset_viewport": bool(reset_viewport),
        "viewport_reset": viewport_reset,
        "viewport_reload_actions": viewport_reload_actions,
    }
