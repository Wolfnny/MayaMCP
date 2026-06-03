from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from .paths import get_artifact_directory, get_log_path, get_tools_directory
from .server import (
    DEFAULT_COMMAND_PORT,
    LOCAL_HOST,
    MayaConnection,
    build_operation_manager,
    command_port_mel,
    configure_logging,
    run,
)
from .tool_contracts import collect_tool_contracts


VALID_TOOL_CATEGORIES = ["material", "object", "scene", "thirdparty"]


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _dependency_status() -> Dict[str, Any]:
    dependencies = {}
    success = True
    for module_name in ["mcp"]:
        try:
            module = importlib.import_module(module_name)
            dependencies[module_name] = {
                "success": True,
                "version": getattr(module, "__version__", None),
            }
        except Exception as exc:
            success = False
            dependencies[module_name] = {"success": False, "message": str(exc)}
    return {"success": success, "dependencies": dependencies}


def build_fix_script() -> Dict[str, Any]:
    env = {
        "MAYA_MCP_COMMAND_PORT": "50009",
        "MAYA_MCP_COMMAND_SOURCE_TYPE": "python",
    }
    return {
        "maya_script_editor": command_port_mel(50009, "python"),
        "mcp_client_env": env,
        "powershell": [
            '$env:MAYA_MCP_COMMAND_PORT="50009"',
            '$env:MAYA_MCP_COMMAND_SOURCE_TYPE="python"',
        ],
    }


def build_doctor_report(live: bool = False) -> Dict[str, Any]:
    configure_logging()
    python_ok = sys.version_info >= (3, 10)
    dependency_report = _dependency_status()
    tools_directory = get_tools_directory()
    manager = build_operation_manager(tools_directory)
    contract_report = collect_tool_contracts(tools_directory)
    connection = None
    connection_error = None
    try:
        connection = MayaConnection()
    except Exception as exc:
        connection_error = str(exc)

    report: Dict[str, Any] = {
        "success": bool(
            python_ok and dependency_report["success"] and contract_report["success"] and connection_error is None
        ),
        "python": {
            "success": python_ok,
            "version": platform.python_version(),
            "executable": sys.executable,
            "requires": ">=3.10",
        },
        "dependencies": dependency_report["dependencies"],
        "tools": {
            "success": len(manager.get_tools()) > 0 and contract_report["success"],
            "tools_directory": str(tools_directory),
            "discovered_count": len(manager.get_tools()),
            "contract_issue_count": contract_report["issue_count"],
            "categories": contract_report["categories"],
        },
        "connection": {
            "success": connection_error is None,
            "host": connection.host if connection else os.environ.get("MAYA_MCP_COMMAND_HOST", LOCAL_HOST),
            "port": connection.port if connection else os.environ.get("MAYA_MCP_COMMAND_PORT", str(DEFAULT_COMMAND_PORT)),
            "source_type": connection.source_type if connection else os.environ.get("MAYA_MCP_COMMAND_SOURCE_TYPE", "mel"),
            "message": connection_error,
            "matching_command_port_mel": connection.matching_command_port_mel() if connection else None,
            "recommended_python_command_port_mel": command_port_mel(50009, "python"),
            "env": {
                "MAYA_MCP_COMMAND_HOST": os.environ.get("MAYA_MCP_COMMAND_HOST", LOCAL_HOST),
                "MAYA_MCP_COMMAND_PORT": os.environ.get("MAYA_MCP_COMMAND_PORT", str(DEFAULT_COMMAND_PORT)),
                "MAYA_MCP_COMMAND_SOURCE_TYPE": os.environ.get("MAYA_MCP_COMMAND_SOURCE_TYPE", "mel"),
            },
        },
        "artifacts": {
            "artifact_directory": str(get_artifact_directory()),
            "log_path": str(get_log_path()),
        },
        "fix_script": build_fix_script(),
        "live": {
            "requested": live,
            "success": None,
            "skipped": not live,
        },
    }

    if live:
        if connection is None:
            report["live"] = {
                "requested": True,
                "success": False,
                "skipped": False,
                "message": connection_error,
                "recommended_python_command_port_mel": command_port_mel(50009, "python"),
            }
            report["success"] = False
            return report
        try:
            live_probe = connection.run_live_probe()
            resident_probe = connection.run_resident_probe()
            cache_probe = connection.run_cache_probe()
            report["live"] = {
                "requested": True,
                "success": bool(
                    live_probe.get("success")
                    and resident_probe.get("success")
                    and cache_probe.get("success")
                ),
                "skipped": False,
                "probe": live_probe,
                "resident_probe": resident_probe,
                "cache_probe": cache_probe,
                "command_port_executable": bool(live_probe.get("success")),
                "resident_executor": bool(resident_probe.get("success")),
                "resident_version": resident_probe.get("version"),
                "resident_expected_version": resident_probe.get("expected_version"),
                "cache_writable": bool(cache_probe.get("success") and cache_probe.get("cache_writable")),
                "effective_source_type": connection.source_type,
                "recommended_source_type": "python",
            }
            report["success"] = bool(
                report["success"]
                and live_probe.get("success")
                and resident_probe.get("success")
                and cache_probe.get("success")
            )
        except Exception as exc:
            report["live"] = {
                "requested": True,
                "success": False,
                "skipped": False,
                "message": str(exc),
                "matching_command_port_mel": connection.matching_command_port_mel(),
                "recommended_python_command_port_mel": command_port_mel(50009, "python"),
            }
            report["success"] = False

    return report


def _print_doctor_human(report: Dict[str, Any]) -> None:
    print("MayaMCP doctor")
    print(f"  Python: {report['python']['version']} ({'ok' if report['python']['success'] else 'fail'})")
    print(f"  Tools: {report['tools']['discovered_count']} discovered")
    print(f"  Contract issues: {report['tools']['contract_issue_count']}")
    print(
        "  CommandPort: "
        f"{report['connection']['host']}:{report['connection']['port']} "
        f"source_type={report['connection']['source_type']}"
    )
    print(f"  Matching Maya command: {report['connection']['matching_command_port_mel']}")
    print(f"  Recommended Python port: {report['connection']['recommended_python_command_port_mel']}")
    print(f"  Artifact directory: {report['artifacts']['artifact_directory']}")
    print(f"  Log path: {report['artifacts']['log_path']}")
    if report["live"]["requested"]:
        print(f"  Live probe: {'ok' if report['live']['success'] else 'fail'}")
        print(
            "  Live commandPort executable: "
            f"{'ok' if report['live'].get('command_port_executable') else 'fail'}"
        )
        resident_status = "ok" if report["live"].get("resident_executor") else "fail"
        resident_version = report["live"].get("resident_version")
        if resident_version:
            print(f"  Live resident executor: {resident_status} ({resident_version})")
        else:
            print(f"  Live resident executor: {resident_status}")
        print(f"  Live cache writable: {'ok' if report['live'].get('cache_writable') else 'fail'}")
        print(
            "  Effective source type: "
            f"{report['live'].get('effective_source_type')} "
            f"(recommended: {report['live'].get('recommended_source_type', 'python')})"
        )
        if not report["live"]["success"]:
            print(f"  Live message: {report['live'].get('message', '')}")
    else:
        print("  Live probe: skipped")


def _print_fix_script(report: Dict[str, Any]) -> None:
    print("Maya Script Editor:")
    print(report["fix_script"]["maya_script_editor"])
    print("")
    print("MCP client env:")
    print(json.dumps(report["fix_script"]["mcp_client_env"], indent=2, sort_keys=True))
    print("")
    print("PowerShell:")
    for line in report["fix_script"]["powershell"]:
        print(line)


def command_doctor(args: argparse.Namespace) -> int:
    report = build_doctor_report(live=args.live)
    if args.json:
        _print_json(report)
    elif args.fix_script:
        _print_fix_script(report)
    else:
        _print_doctor_human(report)
    if args.fix_script:
        return 0
    return 0 if report["success"] else 2


def _description_summary(description: str) -> str:
    for line in (description or "").splitlines():
        clean = line.strip()
        if clean:
            return clean
    return ""


def _tool_parameter_names(tool: Any) -> List[str]:
    schema = getattr(tool, "inputSchema", {}) or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return sorted(properties.keys())


def build_tools_report(categories: List[str] | None = None) -> Dict[str, Any]:
    configure_logging()
    manager = build_operation_manager()
    contract_report = collect_tool_contracts(categories=categories)
    contract_by_name = {report["name"]: report for report in contract_report["tools"]}
    category_filter = {category.lower() for category in categories or []}

    tools = []
    for record in manager.get_tool_records():
        if category_filter and record["category"].lower() not in category_filter:
            continue
        tool = record["tool"]
        contract = contract_by_name.get(record["name"], {})
        tools.append(
            {
                "name": record["name"],
                "category": record["category"],
                "path": record["path"],
                "description": tool.description,
                "summary": _description_summary(tool.description),
                "parameters": _tool_parameter_names(tool),
                "schema_ok": bool(contract.get("schema_ok", True)),
                "contract_issues": contract.get("issues", []),
            }
        )

    issue_count = sum(len(tool["contract_issues"]) for tool in tools)
    return {
        "success": issue_count == 0,
        "tool_count": len(tools),
        "issue_count": issue_count,
        "categories": sorted({tool["category"] for tool in tools}),
        "tools": tools,
    }


def _print_tools_human(report: Dict[str, Any], *, brief: bool = False) -> None:
    print(f"MayaMCP tools: {report['tool_count']} discovered")
    print(f"Contract issues: {report['issue_count']}")
    for tool in report["tools"]:
        issue_marker = " !" if tool["contract_issues"] else ""
        if brief:
            print(f"  [{tool['category']}] {tool['name']}{issue_marker} - {tool['summary']}")
            continue
        print(f"  [{tool['category']}] {tool['name']}{issue_marker}")
        for issue in tool["contract_issues"]:
            print(f"      - {issue}")


def build_tools_search_report(query: str, categories: List[str] | None = None) -> Dict[str, Any]:
    report = build_tools_report(categories=categories)
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_]+", query or "")]
    matches = []
    for tool in report["tools"]:
        haystack = " ".join(
            [
                tool["name"],
                tool["category"],
                tool["description"],
                " ".join(tool["parameters"]),
            ]
        ).lower()
        if all(term in haystack for term in terms):
            score = sum(haystack.count(term) for term in terms)
            item = dict(tool)
            item["score"] = score
            matches.append(item)
    matches.sort(key=lambda item: (-item["score"], item["category"], item["name"]))
    return {
        "success": True,
        "query": query,
        "match_count": len(matches),
        "matches": matches,
    }


def _print_tool_search_human(report: Dict[str, Any]) -> None:
    print(f"MayaMCP tool search: {report['match_count']} matches for {report['query']!r}")
    for tool in report["matches"]:
        params = ", ".join(tool["parameters"][:8])
        if len(tool["parameters"]) > 8:
            params += ", ..."
        print(f"  [{tool['category']}] {tool['name']} - {tool['summary']}")
        if params:
            print(f"      params: {params}")


def command_tools(args: argparse.Namespace) -> int:
    if getattr(args, "tools_command", None) == "search":
        report = build_tools_search_report(args.query, categories=args.category)
        if args.json:
            _print_json(report)
        else:
            _print_tool_search_human(report)
        return 0

    report = build_tools_report(categories=args.category)
    if args.json:
        _print_json(report)
    else:
        _print_tools_human(report, brief=args.brief)
    if args.fail_on_contract and not report["success"]:
        return 2
    return 0


def generate_tools_markdown(categories: List[str] | None = None) -> str:
    report = build_tools_report(categories=categories)
    lines = [
        "# MayaMCP Tools",
        "",
        "Generated from local tool signatures and docstrings.",
        "",
    ]
    for category in sorted(report["categories"]):
        lines.append(f"## {category}")
        lines.append("")
        category_tools = [tool for tool in report["tools"] if tool["category"] == category]
        for tool in sorted(category_tools, key=lambda item: item["name"]):
            params = ", ".join(f"`{param}`" for param in tool["parameters"])
            lines.append(f"- `{tool['name']}` - {tool['summary']}")
            if params:
                lines.append(f"  Parameters: {params}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def command_docs(args: argparse.Namespace) -> int:
    if args.docs_command != "tools":
        return 2
    content = generate_tools_markdown(categories=args.category)
    output_path = Path(args.output).resolve()
    if args.check:
        if not output_path.exists():
            print(f"{output_path} does not exist.")
            return 2
        existing = output_path.read_text(encoding="utf-8")
        if existing != content:
            print(f"{output_path} is out of date. Run maya-mcp docs tools.")
            return 2
        print(f"{output_path} is up to date.")
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


def _parse_new_tool_target(target: str) -> tuple[str, str]:
    parts = target.replace("\\", "/").split("/")
    if len(parts) != 2:
        raise ValueError("new-tool target must be category/name, for example object/my_tool.")
    category, name = parts[0].strip(), parts[1].strip()
    if category not in VALID_TOOL_CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(VALID_TOOL_CATEGORIES)}.")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("tool name must be snake_case and start with a lowercase letter.")
    return category, name


def _new_tool_source(name: str) -> str:
    return f'''from typing import Any, Dict


def {name}(
    example: str = "",
) -> Dict[str, Any]:
    """Describe what this Maya tool does in one clear sentence."""
    # Import Maya modules inside the tool so standalone schema discovery works.
    import maya.cmds as cmds

    return {{
        "success": True,
        "message": "Tool {name} ran.",
        "example": example,
        "scene": cmds.file(query=True, sceneName=True) or "",
    }}
'''


def _new_tool_test_source(category: str, name: str) -> str:
    return f'''from __future__ import annotations

from maya_mcp.tool_contracts import inspect_tool_contract
from maya_mcp.paths import get_tools_directory


def test_{name}_contract() -> None:
    path = get_tools_directory() / "{category}" / "{name}.py"
    report = inspect_tool_contract(path)
    assert report["issues"] == []
'''


def build_new_tool_preview(target: str) -> Dict[str, Any]:
    category, name = _parse_new_tool_target(target)
    tool_path = get_tools_directory() / category / f"{name}.py"
    test_path = Path.cwd() / "tests" / f"test_{name}.py"
    return {
        "success": True,
        "category": category,
        "name": name,
        "tool_path": str(tool_path),
        "test_path": str(test_path),
        "tool_source": _new_tool_source(name),
        "test_source": _new_tool_test_source(category, name),
    }


def command_new_tool(args: argparse.Namespace) -> int:
    try:
        preview = build_new_tool_preview(args.target)
    except ValueError as exc:
        print(str(exc))
        return 2
    if args.json:
        _print_json(preview)
        return 0
    print(f"Tool: {preview['tool_path']}")
    print(f"Test: {preview['test_path']}")
    if args.dry_run:
        print("Dry run only; no files written.")
        return 0

    tool_path = Path(preview["tool_path"])
    test_path = Path(preview["test_path"])
    if tool_path.exists() or test_path.exists():
        print("Refusing to overwrite existing tool or test file.")
        return 2
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(preview["tool_source"], encoding="utf-8")
    test_path.write_text(preview["test_source"], encoding="utf-8")
    print("Created tool and test template.")
    return 0


def command_serve(args: argparse.Namespace) -> int:
    asyncio.run(run())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maya-mcp", description="Maya MCP development and server CLI.")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the stdio MCP server.")
    serve_parser.set_defaults(func=command_serve)

    doctor_parser = subparsers.add_parser("doctor", help="Inspect local MayaMCP configuration.")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    doctor_parser.add_argument("--live", action="store_true", help="Probe the configured Maya commandPort.")
    doctor_parser.add_argument("--fix-script", action="store_true", help="Print recommended Maya and MCP env setup.")
    doctor_parser.set_defaults(func=command_doctor)

    tools_parser = subparsers.add_parser("tools", help="List discovered tools and contract status.")
    tools_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    tools_parser.add_argument("--brief", action="store_true", help="Print one-line tool summaries.")
    tools_parser.add_argument(
        "--category",
        action="append",
        choices=[*VALID_TOOL_CATEGORIES, "root", "external"],
        help="Filter by tool category. May be repeated.",
    )
    tools_parser.add_argument("--fail-on-contract", action="store_true", help="Exit non-zero on contract issues.")
    tools_parser.set_defaults(func=command_tools)
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command")
    search_parser = tools_subparsers.add_parser("search", help="Search tools by name, description, and parameters.")
    search_parser.add_argument("query", help="Search query.")
    search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    search_parser.add_argument(
        "--category",
        action="append",
        choices=[*VALID_TOOL_CATEGORIES, "root", "external"],
        help="Filter by tool category. May be repeated.",
    )
    search_parser.set_defaults(func=command_tools)

    new_tool_parser = subparsers.add_parser("new-tool", help="Create a new MayaMCP tool and test template.")
    new_tool_parser.add_argument("target", help="Tool target in category/name form, for example object/my_tool.")
    new_tool_parser.add_argument("--dry-run", action="store_true", help="Preview paths without writing files.")
    new_tool_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    new_tool_parser.set_defaults(func=command_new_tool)

    docs_parser = subparsers.add_parser("docs", help="Generate repository documentation.")
    docs_subparsers = docs_parser.add_subparsers(dest="docs_command")
    docs_tools_parser = docs_subparsers.add_parser("tools", help="Generate docs/tools.md.")
    docs_tools_parser.add_argument("--check", action="store_true", help="Exit non-zero if docs/tools.md is stale.")
    docs_tools_parser.add_argument("--output", default="docs/tools.md", help="Documentation output path.")
    docs_tools_parser.add_argument(
        "--category",
        action="append",
        choices=[*VALID_TOOL_CATEGORIES, "root", "external"],
        help="Filter by tool category. May be repeated.",
    )
    docs_tools_parser.set_defaults(func=command_docs)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
