from typing import Any, Dict, List, Union


def delete_objects(
    object_names: Union[str, List[str]],
    ignore_missing: bool = True,
    include_default_nodes: bool = False,
    skip_referenced: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Delete scene nodes by name with explicit reporting and safety guards.

    This is a generic scene cleanup tool for removing temporary meshes, helper
    cameras, construction tests, imported junk nodes, or other named objects.
    By default it skips common Maya default nodes and referenced nodes, reports
    missing names, and supports dry-run checks before editing the scene.
    """
    import maya.cmds as cmds

    if isinstance(object_names, str):
        requested = [object_names]
    elif isinstance(object_names, list) and object_names and all(isinstance(item, str) for item in object_names):
        requested = object_names[:]
    else:
        raise ValueError("object_names must be a string or a non-empty list of strings.")

    default_nodes = {
        "persp",
        "top",
        "front",
        "side",
        "perspShape",
        "topShape",
        "frontShape",
        "sideShape",
        "defaultLightSet",
        "defaultObjectSet",
        "initialParticleSE",
        "initialShadingGroup",
        "lambert1",
        "particleCloud1",
    }

    def _short_name(node: str) -> str:
        return node.split("|")[-1].split(":")[-1]

    def _is_component(name: str) -> bool:
        return "." in name and any(token in name for token in (".vtx", ".e", ".f", ".map", ".uv", ".cv"))

    def _is_referenced(node: str) -> bool:
        try:
            return bool(cmds.referenceQuery(node, isNodeReferenced=True))
        except Exception:
            return False

    resolved = []
    missing = []
    ambiguous = []
    skipped_default = []
    skipped_referenced = []
    skipped_components = []

    for name in requested:
        if _is_component(name):
            skipped_components.append(name)
            continue

        matches = cmds.ls(name, long=True) or []
        if not matches:
            if ignore_missing:
                missing.append(name)
                continue
            raise ValueError(f"Object does not exist: {name}")

        # Short DAG names can match multiple objects. Require a long path in
        # that case so a cleanup command cannot delete unrelated duplicates.
        if len(matches) > 1 and not name.startswith("|"):
            ambiguous.append({"requested": name, "matches": matches})
            continue

        for node in matches:
            short = _short_name(node)
            if not include_default_nodes and short in default_nodes:
                skipped_default.append(node)
                continue
            if skip_referenced and _is_referenced(node):
                skipped_referenced.append(node)
                continue
            if node not in resolved:
                resolved.append(node)

    if ambiguous:
        return {
            "success": False,
            "message": "Ambiguous short names were not deleted. Use long DAG paths for duplicates.",
            "requested": requested,
            "resolved": resolved,
            "missing": missing,
            "ambiguous": ambiguous,
            "skipped_default": skipped_default,
            "skipped_referenced": skipped_referenced,
            "skipped_components": skipped_components,
            "dry_run": bool(dry_run),
        }

    deleted = []
    failed = []
    if not dry_run and resolved:
        for node in resolved:
            if not cmds.objExists(node):
                continue
            try:
                cmds.delete(node)
                if not cmds.objExists(node):
                    deleted.append(node)
            except Exception as exc:
                failed.append({"node": node, "message": str(exc)})

    return {
        "success": not failed,
        "requested": requested,
        "resolved": resolved,
        "deleted": deleted,
        "delete_count": len(deleted) if not dry_run else 0,
        "missing": missing,
        "ambiguous": ambiguous,
        "skipped_default": skipped_default,
        "skipped_referenced": skipped_referenced,
        "skipped_components": skipped_components,
        "failed": failed,
        "dry_run": bool(dry_run),
    }
