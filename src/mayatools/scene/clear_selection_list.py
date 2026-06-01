from typing import Any, Dict


def clear_selection_list() -> Dict[str, Any]:
    """Clear the user selection list of objects."""
    import maya.cmds as cmds

    cmds.select(clear=True)
    return {
        "success": True,
        "selected_count": len(cmds.ls(selection=True) or []),
    }
