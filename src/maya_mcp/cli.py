from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import platform
import sys
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
            report["live"] = {
                "requested": True,
                "success": bool(live_probe.get("success")),
                "skipped": False,
                "probe": live_probe,
            }
            report["success"] = bool(report["success"] and live_probe.get("success"))
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
        if not report["live"]["success"]:
            print(f"  Live message: {report['live'].get('message', '')}")
    else:
        print("  Live probe: skipped")


def command_doctor(args: argparse.Namespace) -> int:
    report = build_doctor_report(live=args.live)
    if args.json:
        _print_json(report)
    else:
        _print_doctor_human(report)
    return 0 if report["success"] else 2


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


def _print_tools_human(report: Dict[str, Any]) -> None:
    print(f"MayaMCP tools: {report['tool_count']} discovered")
    print(f"Contract issues: {report['issue_count']}")
    for tool in report["tools"]:
        issue_marker = " !" if tool["contract_issues"] else ""
        print(f"  [{tool['category']}] {tool['name']}{issue_marker}")
        for issue in tool["contract_issues"]:
            print(f"      - {issue}")


def command_tools(args: argparse.Namespace) -> int:
    report = build_tools_report(categories=args.category)
    if args.json:
        _print_json(report)
    else:
        _print_tools_human(report)
    if args.fail_on_contract and not report["success"]:
        return 2
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
    doctor_parser.set_defaults(func=command_doctor)

    tools_parser = subparsers.add_parser("tools", help="List discovered tools and contract status.")
    tools_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    tools_parser.add_argument(
        "--category",
        action="append",
        choices=["material", "object", "scene", "thirdparty", "root", "external"],
        help="Filter by tool category. May be repeated.",
    )
    tools_parser.add_argument("--fail-on-contract", action="store_true", help="Exit non-zero on contract issues.")
    tools_parser.set_defaults(func=command_tools)

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
