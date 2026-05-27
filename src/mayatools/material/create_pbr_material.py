from typing import Dict, List, Any, Union


def create_pbr_material(
    name: str = None,
    preset: str = "generic",
    shader_type: str = "auto",
    base_color: List[float] = None,
    opacity: Union[float, List[float]] = None,
    metalness: float = None,
    roughness: float = None,
    specular: float = None,
    specular_color: List[float] = None,
    transmission: float = None,
    transmission_color: List[float] = None,
    ior: float = None,
    coat: float = None,
    coat_roughness: float = None,
    emission: float = None,
    emission_color: List[float] = None,
    thin_walled: bool = None,
    parameters: Dict[str, Any] = None,
    assign_to: Union[str, List[str]] = None,
) -> Dict[str, Any]:
    """Create a physically-oriented material and optionally assign it to objects.

    The tool prefers Arnold aiStandardSurface when available, falls back to
    Maya standardSurface, and finally uses phong for older scenes. Presets are
    generic material starting points; direct arguments override preset values.
    Supported presets: generic, glass, liquid, metal, plastic, rubber, ceramic.
    """
    import random
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_color(values, arg_name):
        if not isinstance(values, list) or len(values) != 3 or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of 3 numeric values.")
        return [float(values[0]), float(values[1]), float(values[2])]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_opacity(value):
        if isinstance(value, list):
            return _validate_color(value, "opacity")
        return [_validate_scalar(value, "opacity")] * 3

    preset_defaults = {
        "generic": {
            "base_color": [0.8, 0.8, 0.8],
            "opacity": [1.0, 1.0, 1.0],
            "metalness": 0.0,
            "roughness": 0.35,
            "specular": 0.5,
        },
        "glass": {
            "base_color": [0.75, 0.62, 0.45],
            "opacity": [0.28, 0.28, 0.28],
            "metalness": 0.0,
            "roughness": 0.02,
            "specular": 1.0,
            "specular_color": [1.0, 1.0, 1.0],
            "transmission": 0.85,
            "transmission_color": [0.75, 0.62, 0.45],
            "ior": 1.52,
            "coat": 0.15,
            "coat_roughness": 0.02,
            "thin_walled": False,
        },
        "liquid": {
            "base_color": [0.12, 0.045, 0.015],
            "opacity": [0.72, 0.72, 0.72],
            "metalness": 0.0,
            "roughness": 0.06,
            "specular": 0.65,
            "transmission": 0.35,
            "transmission_color": [0.18, 0.06, 0.015],
            "ior": 1.33,
            "thin_walled": False,
        },
        "metal": {
            "base_color": [0.8, 0.8, 0.8],
            "opacity": [1.0, 1.0, 1.0],
            "metalness": 1.0,
            "roughness": 0.18,
            "specular": 1.0,
        },
        "plastic": {
            "base_color": [0.8, 0.05, 0.05],
            "opacity": [1.0, 1.0, 1.0],
            "metalness": 0.0,
            "roughness": 0.32,
            "specular": 0.55,
            "coat": 0.25,
            "coat_roughness": 0.08,
        },
        "rubber": {
            "base_color": [0.02, 0.02, 0.02],
            "opacity": [1.0, 1.0, 1.0],
            "metalness": 0.0,
            "roughness": 0.78,
            "specular": 0.18,
        },
        "ceramic": {
            "base_color": [0.85, 0.82, 0.76],
            "opacity": [1.0, 1.0, 1.0],
            "metalness": 0.0,
            "roughness": 0.22,
            "specular": 0.65,
            "coat": 0.35,
            "coat_roughness": 0.04,
        },
    }

    preset = preset.lower()
    if preset not in preset_defaults:
        raise ValueError(f"Unsupported preset {preset}. Use one of {sorted(preset_defaults)}")

    settings = dict(preset_defaults[preset])
    overrides = {
        "base_color": _validate_color(base_color, "base_color") if base_color is not None else None,
        "opacity": _validate_opacity(opacity) if opacity is not None else None,
        "metalness": _validate_scalar(metalness, "metalness") if metalness is not None else None,
        "roughness": _validate_scalar(roughness, "roughness") if roughness is not None else None,
        "specular": _validate_scalar(specular, "specular") if specular is not None else None,
        "specular_color": _validate_color(specular_color, "specular_color") if specular_color is not None else None,
        "transmission": _validate_scalar(transmission, "transmission") if transmission is not None else None,
        "transmission_color": _validate_color(transmission_color, "transmission_color") if transmission_color is not None else None,
        "ior": _validate_scalar(ior, "ior") if ior is not None else None,
        "coat": _validate_scalar(coat, "coat") if coat is not None else None,
        "coat_roughness": _validate_scalar(coat_roughness, "coat_roughness") if coat_roughness is not None else None,
        "emission": _validate_scalar(emission, "emission") if emission is not None else None,
        "emission_color": _validate_color(emission_color, "emission_color") if emission_color is not None else None,
        "thin_walled": bool(thin_walled) if thin_walled is not None else None,
    }
    for key, value in overrides.items():
        if value is not None:
            settings[key] = value

    if parameters is None:
        parameters = {}
    if name is None:
        name = f"{preset}_pbr_mat_{int(random.random() * 1000)}"

    def _has_attr(node, attr):
        return cmds.attributeQuery(attr, node=node, exists=True)

    def _set_scalar(node, attr, value):
        if value is not None and _has_attr(node, attr):
            cmds.setAttr(f"{node}.{attr}", float(value))
            return True
        return False

    def _set_bool(node, attr, value):
        if value is not None and _has_attr(node, attr):
            cmds.setAttr(f"{node}.{attr}", bool(value))
            return True
        return False

    def _set_color(node, attr, value):
        if value is not None and _has_attr(node, attr):
            values = _validate_color(value, attr)
            cmds.setAttr(f"{node}.{attr}", values[0], values[1], values[2], type="double3")
            return True
        return False

    def _try_load_arnold():
        try:
            if not cmds.pluginInfo("mtoa", query=True, loaded=True):
                cmds.loadPlugin("mtoa", quiet=True)
            return cmds.pluginInfo("mtoa", query=True, loaded=True)
        except Exception:
            return False

    def _create_shader(node_type):
        shader = cmds.shadingNode(node_type, asShader=True, name=name)
        if node_type in {"aiStandardSurface", "standardSurface"} and not _has_attr(shader, "baseColor"):
            cmds.delete(shader)
            raise RuntimeError(f"{node_type} is not available in this Maya session.")
        if node_type == "phong" and not _has_attr(shader, "color"):
            cmds.delete(shader)
            raise RuntimeError("phong is not available in this Maya session.")
        return shader

    shader_type = shader_type.strip()
    if shader_type == "auto":
        candidates = []
        if _try_load_arnold():
            candidates.append("aiStandardSurface")
        candidates.extend(["standardSurface", "phong"])
    else:
        supported_shader_types = {"aiStandardSurface", "standardSurface", "phong"}
        if shader_type not in supported_shader_types:
            raise ValueError(f"Unsupported shader_type {shader_type}. Use auto, aiStandardSurface, standardSurface, or phong.")
        if shader_type == "aiStandardSurface":
            _try_load_arnold()
        candidates = [shader_type]

    shader = None
    created_shader_type = None
    errors = []
    for candidate in candidates:
        try:
            shader = _create_shader(candidate)
            created_shader_type = candidate
            break
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    if shader is None:
        raise RuntimeError("Unable to create a supported PBR shader. " + "; ".join(errors))

    applied_attributes = {}

    def _record(attr, applied):
        if applied:
            applied_attributes[attr] = True

    if created_shader_type in {"aiStandardSurface", "standardSurface"}:
        _record("base", _set_scalar(shader, "base", 1.0))
        _record("baseColor", _set_color(shader, "baseColor", settings.get("base_color")))
        _record("metalness", _set_scalar(shader, "metalness", settings.get("metalness")))
        _record("specular", _set_scalar(shader, "specular", settings.get("specular")))
        _record("specularColor", _set_color(shader, "specularColor", settings.get("specular_color", [1.0, 1.0, 1.0])))
        _record("specularRoughness", _set_scalar(shader, "specularRoughness", settings.get("roughness")))
        _record("specularIOR", _set_scalar(shader, "specularIOR", settings.get("ior")))
        _record("transmission", _set_scalar(shader, "transmission", settings.get("transmission")))
        _record("transmissionColor", _set_color(shader, "transmissionColor", settings.get("transmission_color")))
        _record("opacity", _set_color(shader, "opacity", settings.get("opacity")))
        _record("thinWalled", _set_bool(shader, "thinWalled", settings.get("thin_walled")))
        _record("coat", _set_scalar(shader, "coat", settings.get("coat")))
        _record("coatRoughness", _set_scalar(shader, "coatRoughness", settings.get("coat_roughness")))
        _record("emission", _set_scalar(shader, "emission", settings.get("emission")))
        _record("emissionColor", _set_color(shader, "emissionColor", settings.get("emission_color")))
    else:
        opacity_values = settings.get("opacity", [1.0, 1.0, 1.0])
        transparency = [1.0 - max(0.0, min(1.0, value)) for value in opacity_values]
        _record("color", _set_color(shader, "color", settings.get("base_color")))
        _record("specularColor", _set_color(shader, "specularColor", settings.get("specular_color", [1.0, 1.0, 1.0])))
        _record("transparency", _set_color(shader, "transparency", transparency))
        _record("reflectivity", _set_scalar(shader, "reflectivity", settings.get("specular")))
        _record("eccentricity", _set_scalar(shader, "eccentricity", settings.get("roughness")))

    for attr, value in parameters.items():
        if not _has_attr(shader, attr):
            continue
        if isinstance(value, list) and len(value) == 3:
            _set_color(shader, attr, value)
        elif isinstance(value, bool):
            cmds.setAttr(f"{shader}.{attr}", value)
        elif _is_number(value):
            cmds.setAttr(f"{shader}.{attr}", float(value))
        elif isinstance(value, str):
            cmds.setAttr(f"{shader}.{attr}", value, type="string")
        applied_attributes[attr] = True

    shading_group = cmds.sets(name=f"{name}SG", empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)

    assigned_to = []
    if assign_to:
        objects = assign_to if isinstance(assign_to, list) else [assign_to]
        for obj in objects:
            if not cmds.objExists(obj):
                raise ValueError(f"Object does not exist: {obj}")
        cmds.sets(objects, edit=True, forceElement=shading_group)
        assigned_to = objects

    return {
        "success": True,
        "name": name,
        "preset": preset,
        "requested_shader_type": shader_type,
        "shader_type": created_shader_type,
        "shader": shader,
        "shading_group": shading_group,
        "settings": settings,
        "applied_attributes": applied_attributes,
        "assigned_to": assigned_to,
    }
