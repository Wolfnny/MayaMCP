from typing import Dict, Any


def generate_scene(
    scene_type: str,
    name: str = None,
    parameters: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Generate a complete 3D scene with multiple objects arranged according to a theme.

    Available scene types are city, forest, living_room, office, and park.
    Parameters is a dictionary containing scene-specific settings.
    """
    import math
    import random
    import maya.cmds as cmds

    if parameters is None:
        parameters = {}

    scene_type = scene_type.lower()
    if name is None:
        name = f"{scene_type}_scene_{int(random.random() * 1000)}"

    scene_group = cmds.group(empty=True, name=name)
    created = []

    def _mat(mat_name, color):
        shader = cmds.shadingNode("lambert", asShader=True, name=mat_name)
        cmds.setAttr(f"{shader}.color", color[0], color[1], color[2], type="double3")
        sg = cmds.sets(empty=True, renderable=True, noSurfaceShader=True, name=f"{shader}SG")
        cmds.connectAttr(f"{shader}.outColor", f"{sg}.surfaceShader", force=True)
        return sg

    def _assign(obj, sg):
        if obj:
            cmds.sets(obj, edit=True, forceElement=sg)

    def _cube(obj_name, width, height, depth, pos, color):
        obj = cmds.polyCube(name=obj_name, width=width, height=height, depth=depth)[0]
        cmds.move(pos[0], pos[1], pos[2], obj)
        obj = cmds.parent(obj, scene_group)[0]
        _assign(obj, _mat(f"{obj_name}_mat", color))
        created.append(obj)
        return obj

    def _cylinder(obj_name, radius, height, pos, color, subdivisions=24):
        obj = cmds.polyCylinder(name=obj_name, radius=radius, height=height, subdivisionsAxis=subdivisions)[0]
        cmds.move(pos[0], pos[1], pos[2], obj)
        obj = cmds.parent(obj, scene_group)[0]
        _assign(obj, _mat(f"{obj_name}_mat", color))
        created.append(obj)
        return obj

    def _cone(obj_name, radius, height, pos, color, subdivisions=20):
        obj = cmds.polyCone(name=obj_name, radius=radius, height=height, subdivisionsAxis=subdivisions)[0]
        cmds.move(pos[0], pos[1], pos[2], obj)
        obj = cmds.parent(obj, scene_group)[0]
        _assign(obj, _mat(f"{obj_name}_mat", color))
        created.append(obj)
        return obj

    if scene_type == "city":
        blocks = int(parameters.get("blocks", 2))
        include_cars = bool(parameters.get("include_cars", True))
        block_size = float(parameters.get("block_size", 20.0))
        street_width = float(parameters.get("street_width", 8.0))
        city_size = blocks * block_size + (blocks + 1) * street_width

        ground = cmds.polyPlane(name=f"{name}_ground", width=city_size, height=city_size)[0]
        ground = cmds.parent(ground, scene_group)[0]
        _assign(ground, _mat(f"{name}_asphalt_mat", [0.18, 0.18, 0.18]))
        created.append(ground)

        building_count = 0
        for bx in range(blocks):
            for bz in range(blocks):
                base_x = -city_size / 2 + street_width + bx * (block_size + street_width)
                base_z = -city_size / 2 + street_width + bz * (block_size + street_width)
                for i in range(3):
                    width = random.uniform(4.0, 7.0)
                    depth = random.uniform(4.0, 7.0)
                    height = random.uniform(8.0, 28.0)
                    x = base_x + random.uniform(0, block_size)
                    z = base_z + random.uniform(0, block_size)
                    _cube(f"{name}_building_{building_count}", width, height, depth, [x, height / 2, z], [0.35, 0.38, 0.42])
                    building_count += 1

        car_count = 0
        if include_cars:
            for i in range(max(1, blocks * blocks)):
                x = random.uniform(-city_size / 2, city_size / 2)
                z = random.choice([-city_size / 4, 0.0, city_size / 4])
                car = _cube(f"{name}_car_{i}", 2.4, 0.7, 4.0, [x, 0.35, z], [0.8, 0.1 + random.random() * 0.4, 0.1])
                cmds.rotate(0, random.choice([0, 90]), 0, car)
                car_count += 1

        stats = {"buildings_count": building_count, "cars_count": car_count}

    elif scene_type == "forest":
        tree_count = int(parameters.get("tree_count", 12))
        forest_size = float(parameters.get("forest_size", 40.0))

        ground = cmds.polyPlane(name=f"{name}_ground", width=forest_size, height=forest_size, subdivisionsX=12, subdivisionsY=12)[0]
        ground = cmds.parent(ground, scene_group)[0]
        _assign(ground, _mat(f"{name}_ground_mat", [0.22, 0.38, 0.18]))
        created.append(ground)

        for i in range(tree_count):
            x = random.uniform(-forest_size / 2, forest_size / 2)
            z = random.uniform(-forest_size / 2, forest_size / 2)
            trunk_h = random.uniform(3.0, 6.0)
            _cylinder(f"{name}_tree_{i}_trunk", 0.22, trunk_h, [x, trunk_h / 2, z], [0.32, 0.18, 0.08], 12)
            _cone(f"{name}_tree_{i}_crown", random.uniform(1.1, 1.8), random.uniform(2.5, 4.0), [x, trunk_h + 1.4, z], [0.05, 0.32, 0.12], 16)

        stats = {"trees_count": tree_count}

    elif scene_type == "living_room":
        room_size = float(parameters.get("room_size", 18.0))
        _cube(f"{name}_floor", room_size, 0.15, room_size, [0, 0, 0], [0.55, 0.38, 0.22])
        _cube(f"{name}_sofa", 6.0, 1.4, 2.2, [0, 0.75, 4.0], [0.18, 0.28, 0.55])
        _cube(f"{name}_coffee_table", 4.0, 0.7, 2.0, [0, 0.45, 1.0], [0.45, 0.26, 0.13])
        _cube(f"{name}_tv_stand", 5.0, 1.0, 1.0, [0, 0.55, -5.5], [0.2, 0.16, 0.14])
        _cube(f"{name}_tv", 5.4, 3.0, 0.2, [0, 2.4, -6.1], [0.02, 0.02, 0.025])
        stats = {"furniture_count": 4}

    elif scene_type == "office":
        desks_count = int(parameters.get("desks_count", 4))
        office_size = float(parameters.get("office_size", 24.0))
        _cube(f"{name}_floor", office_size, 0.12, office_size, [0, 0, 0], [0.48, 0.48, 0.5])
        grid = int(math.ceil(math.sqrt(desks_count)))
        spacing = office_size * 0.65 / max(1, grid)
        for i in range(desks_count):
            row = i // grid
            col = i % grid
            x = (col - (grid - 1) / 2) * spacing
            z = (row - (grid - 1) / 2) * spacing
            _cube(f"{name}_desk_{i}", 4.0, 0.7, 2.0, [x, 0.45, z], [0.74, 0.74, 0.7])
            _cube(f"{name}_monitor_{i}", 1.6, 0.9, 0.15, [x, 1.25, z - 0.55], [0.02, 0.02, 0.025])
            _cube(f"{name}_chair_{i}", 1.2, 1.2, 1.2, [x, 0.65, z + 1.6], [0.12, 0.15, 0.18])
        stats = {"desks_count": desks_count}

    elif scene_type == "park":
        park_size = float(parameters.get("park_size", 36.0))
        tree_count = int(parameters.get("tree_count", 8))
        ground = cmds.polyPlane(name=f"{name}_grass", width=park_size, height=park_size)[0]
        ground = cmds.parent(ground, scene_group)[0]
        _assign(ground, _mat(f"{name}_grass_mat", [0.18, 0.52, 0.18]))
        created.append(ground)
        _cylinder(f"{name}_fountain", 2.2, 0.8, [0, 0.4, 0], [0.6, 0.62, 0.64], 32)
        for i in range(tree_count):
            angle = 2 * math.pi * i / tree_count
            x = math.cos(angle) * park_size * 0.35
            z = math.sin(angle) * park_size * 0.35
            _cylinder(f"{name}_tree_{i}_trunk", 0.18, 3.0, [x, 1.5, z], [0.3, 0.18, 0.08], 10)
            _cone(f"{name}_tree_{i}_crown", 1.2, 2.5, [x, 3.4, z], [0.05, 0.34, 0.13], 16)
        stats = {"trees_count": tree_count, "has_fountain": True}

    else:
        raise ValueError("Unknown scene type. Use city, forest, living_room, office, or park")

    return {
        "success": True,
        "name": scene_group,
        "scene_type": scene_type,
        "objects_count": len(created),
        **stats,
    }
