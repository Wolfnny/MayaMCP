from typing import Any, Dict, List


def get_node_connections(
    node_name: str,
    attribute_name: str = None,
    source: bool = True,
    destination: bool = True,
    plugs: bool = True,
    connections: bool = True,
    skip_conversion_nodes: bool = False,
) -> Dict[str, Any]:
    """Inspect dependency-graph connections for a Maya node or attribute.

    This is a generic debugging utility for materials, textures, deformers,
    constraints, utility nodes, and other Maya dependency-graph networks. When
    attribute_name is provided, only that plug is inspected; otherwise all
    visible connections on the node are returned.
    """
    import maya.cmds as cmds

    if not node_name:
        raise ValueError("node_name is required.")
    if not cmds.objExists(node_name):
        raise ValueError(f"Node does not exist: {node_name}")

    target = node_name
    if attribute_name:
        if not cmds.attributeQuery(attribute_name, node=node_name, exists=True):
            raise ValueError(f"Attribute {attribute_name} does not exist on {node_name}")
        target = f"{node_name}.{attribute_name}"

    raw = cmds.listConnections(
        target,
        source=bool(source),
        destination=bool(destination),
        plugs=bool(plugs),
        connections=bool(connections),
        skipConversionNodes=bool(skip_conversion_nodes),
    ) or []

    pairs: List[Dict[str, Any]] = []
    if connections:
        for index in range(0, len(raw), 2):
            local_plug = raw[index]
            connected_plug = raw[index + 1] if index + 1 < len(raw) else None
            connected_node = connected_plug.split(".", 1)[0] if isinstance(connected_plug, str) else None
            pairs.append(
                {
                    "plug": local_plug,
                    "connected_plug": connected_plug,
                    "connected_node": connected_node,
                }
            )
    else:
        for item in raw:
            connected_node = item.split(".", 1)[0] if isinstance(item, str) else item
            pairs.append(
                {
                    "connected_plug": item,
                    "connected_node": connected_node,
                }
            )

    return {
        "success": True,
        "node_name": node_name,
        "attribute_name": attribute_name,
        "target": target,
        "source": bool(source),
        "destination": bool(destination),
        "plugs": bool(plugs),
        "connections": bool(connections),
        "skip_conversion_nodes": bool(skip_conversion_nodes),
        "connection_count": len(pairs),
        "connections_list": pairs,
    }
