
import os
from typing import Dict, Any, Optional

def scene_open(filename: str, namespace: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Load a scene into Maya.

    If namespace is specified, the scene will be loaded into the current scene as
    a reference in the given namespace name. Use force to discard unsaved scene
    changes when opening a normal scene file.
    """
    import maya.cmds as cmds
    file_type = None
    _, ext = os.path.splitext(filename)
    if ext == ".mb":
        file_type = "mayaBinary"
    elif ext == ".ma":
        file_type = "mayaAscii"
    elif not ext:
        # no extension
        raise ValueError(f"Error: Unable to open a scene without knowning the file format from the file extension")
    else:
        # future to support FBX, USD
        raise ValueError(f"Error: Unable to open a scene in the file format {ext}")

    if file_type:
        if namespace:
            cmds.file(filename, open=True, reference=True, namespace=namespace)
        else:
            cmds.file(filename, open=True, force=force)
        results = { "success": True }
            
    return results

