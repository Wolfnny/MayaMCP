from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path
from typing import Any, Dict, Iterable, List

from mcp.server.fastmcp.utilities.func_metadata import func_metadata

from .paths import get_tools_directory


def iter_tool_files(tools_directory: str | Path | None = None) -> Iterable[Path]:
    root = get_tools_directory(tools_directory)
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py" or "__pycache__" in path.parts:
            continue
        yield path


def tool_category(path: str | Path, tools_directory: str | Path | None = None) -> str:
    root = get_tools_directory(tools_directory)
    tool_path = Path(path).resolve()
    try:
        relative = tool_path.relative_to(root)
    except ValueError:
        return "external"
    return relative.parts[0] if len(relative.parts) > 1 else "root"


def inspect_tool_contract(path: str | Path, tools_directory: str | Path | None = None) -> Dict[str, Any]:
    tool_path = Path(path).resolve()
    tool_name = tool_path.stem
    issues: List[str] = []
    schema_ok = False

    try:
        source = tool_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(tool_path))
    except Exception as exc:
        return {
            "name": tool_name,
            "path": str(tool_path),
            "category": tool_category(tool_path, tools_directory),
            "schema_ok": False,
            "issues": [f"parse_failed:{exc}"],
        }

    function_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == tool_name:
            function_node = node
            break
    if function_node is None:
        issues.append("missing_matching_function")
    else:
        if not ast.get_docstring(function_node):
            issues.append("missing_docstring")
        parameters = (
            list(function_node.args.posonlyargs)
            + list(function_node.args.args)
            + list(function_node.args.kwonlyargs)
        )
        for parameter in parameters:
            if parameter.arg in {"self", "cls"}:
                continue
            if parameter.annotation is None:
                issues.append(f"missing_parameter_annotation:{parameter.arg}")

    for node in tree.body:
        modules: List[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        for module in modules:
            if module == "maya" or module.startswith("maya."):
                issues.append(f"top_level_maya_import:{module}")

    try:
        spec = importlib.util.spec_from_file_location(tool_name, tool_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to create import spec for {tool_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, tool_name)
        if not callable(fn):
            issues.append("matching_symbol_not_callable")
        inspect.signature(fn)
        func_metadata(fn).arg_model.model_json_schema()
        schema_ok = True
    except Exception as exc:
        issues.append(f"standalone_import_or_schema_failed:{exc}")

    return {
        "name": tool_name,
        "path": str(tool_path),
        "category": tool_category(tool_path, tools_directory),
        "schema_ok": schema_ok,
        "issues": sorted(set(issues)),
    }


def collect_tool_contracts(
    tools_directory: str | Path | None = None,
    categories: List[str] | None = None,
) -> Dict[str, Any]:
    category_filter = {category.lower() for category in categories or []}
    reports = []
    for path in iter_tool_files(tools_directory):
        report = inspect_tool_contract(path, tools_directory)
        if category_filter and report["category"].lower() not in category_filter:
            continue
        reports.append(report)

    issue_reports = [report for report in reports if report["issues"]]
    categories_seen = sorted({report["category"] for report in reports})
    return {
        "success": len(issue_reports) == 0,
        "tool_count": len(reports),
        "issue_count": sum(len(report["issues"]) for report in issue_reports),
        "categories": categories_seen,
        "issues": issue_reports,
        "tools": reports,
    }
