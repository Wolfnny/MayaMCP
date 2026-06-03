from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import importlib.util
import json
import logging
import os
import pprint
import socket
import tempfile
import uuid
from enum import Enum
from itertools import chain
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, get_origin

import mcp.server.stdio
import pydantic_core
from mcp.server.fastmcp.server import Context
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from mcp.server.fastmcp.utilities.types import Image
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from .paths import get_log_path, get_tools_directory
from mayatools.common.results import compact_result


__version__ = "0.2.0"

LoggingLevel = logging.DEBUG

LOCAL_HOST = "127.0.0.1"

# Default MEL command port that Maya listens on.
DEFAULT_COMMAND_PORT = 50007

logger = logging.getLogger("MayaMCP")
logger.addHandler(logging.NullHandler())

_operation_manager: "OperationsManager | None" = None
_KNOWN_MAYA_TOOL_CACHE_KEYS: set[tuple[str, int, str, str, str]] = set()
_KNOWN_MAYA_RESIDENT_EXECUTOR_KEYS: set[tuple[str, int, str, str]] = set()
RESIDENT_EXECUTOR_VERSION = "2026-06-03.1"


def configure_logging(level: int = LoggingLevel) -> Path:
    """Configure file logging without writing into the source tree."""
    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path:
            logger.setLevel(level)
            return log_path

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
        )
    )
    logger.addHandler(file_handler)
    logger.setLevel(level)
    return log_path


class MayaConnection:
    """Connection to the Maya commandPort."""

    def __init__(self, host: str = None, port: int = None, source_type: str = None):
        if host is None:
            host = os.environ.get("MAYA_MCP_COMMAND_HOST", LOCAL_HOST)
        if port is None:
            raw_port = os.environ.get("MAYA_MCP_COMMAND_PORT", DEFAULT_COMMAND_PORT)
            try:
                port = int(raw_port)
            except (TypeError, ValueError) as exc:
                raise ValueError("MAYA_MCP_COMMAND_PORT must be an integer.") from exc
        if source_type is None:
            source_type = os.environ.get("MAYA_MCP_COMMAND_SOURCE_TYPE", "mel")
        source_type = source_type.lower().strip()
        if source_type not in {"mel", "python"}:
            raise ValueError("MAYA_MCP_COMMAND_SOURCE_TYPE must be mel or python.")
        self.host = host
        try:
            self.port = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError("Maya commandPort must be an integer.") from exc
        self.source_type = source_type

    @property
    def config(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "source_type": self.source_type,
        }

    def matching_command_port_mel(self) -> str:
        return command_port_mel(self.port, self.source_type)

    @staticmethod
    def _encode_python_to_mel_python(python_code: str) -> str:
        mel = python_code.replace("\\", "\\\\")
        mel = mel.replace('"', '\\"')
        mel = mel.replace("\n", "\\n")
        return f'python("{mel}")'

    @staticmethod
    def _update_script_to_capture_stdout(python_script: str) -> str:
        spaced_python_script = "    " + python_script.replace("\n", "\n    ")
        return f"""
import io
import contextlib
_mcp_io_buf = io.StringIO()
with contextlib.redirect_stdout(_mcp_io_buf):
{spaced_python_script}
_mcp_maya_results = _mcp_io_buf.getvalue()
"""

    @staticmethod
    def _clean_command_result(result: Optional[str]) -> str:
        if result is None:
            return ""
        return result.replace(chr(0), "").replace(chr(10), "")

    @staticmethod
    def _write_python_script_to_temp_file(python_script: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="maya_mcp_",
            encoding="utf-8",
            delete=False,
        ) as temp_file:
            temp_file.write(python_script)
            return temp_file.name

    @staticmethod
    def _temp_file_loader_script(filename: str) -> str:
        return f"""
_mcp_script_path = {filename!r}
with open(_mcp_script_path, "r", encoding="utf-8") as _mcp_script_file:
    _mcp_script_source = _mcp_script_file.read()
try:
    exec(compile(_mcp_script_source, _mcp_script_path, "exec"), globals(), globals())
finally:
    try:
        import os as _mcp_os
        _mcp_os.remove(_mcp_script_path)
    except Exception:
        pass
"""

    def _connection_error(self, exc: BaseException) -> ConnectionError:
        return ConnectionError(
            "Unable to connect to Maya commandPort "
            f"(host={self.host}, port={self.port}, source_type={self.source_type}). "
            f"Matching Maya command: {self.matching_command_port_mel()}. "
            f"Recommended Python port: {command_port_mel(50009, 'python')}. "
            f"Original error: {exc}"
        )

    def _send_python_command(self, python_script: str, *, wrap_python_exec: bool = False) -> Optional[str]:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client.connect((self.host, self.port))
        except OSError as exc:
            client.close()
            raise self._connection_error(exc) from exc

        if wrap_python_exec:
            # Maya's Python commandPort can resolve function globals from an older
            # interpreter scope unless the whole tool script is executed explicitly.
            python_script = f"exec({python_script!r}, globals(), globals())"

        if self.source_type == "python":
            command = python_script
        else:
            command = MayaConnection._encode_python_to_mel_python(python_script)

        max_inline_bytes = int(os.environ.get("MAYA_MCP_INLINE_COMMAND_MAX_BYTES", "6000"))
        if len(command.encode("utf-8")) > max_inline_bytes:
            temp_filename = MayaConnection._write_python_script_to_temp_file(python_script)
            python_script = MayaConnection._temp_file_loader_script(temp_filename)
            if self.source_type == "python":
                command = python_script
            else:
                command = MayaConnection._encode_python_to_mel_python(python_script)

        try:
            client.sendall(command.encode("utf-8"))
            client.shutdown(socket.SHUT_WR)

            result = data = client.recv(1024)
            while len(data) == 1024:
                data = client.recv(1024)
                result += data
        finally:
            client.close()

        if result:
            return result.decode("utf-8")
        return None

    class ScriptReturn(Enum):
        STDOUT = "stdout"
        JSON = "json"
        NONE = "none"

    def run_python_script(
        self,
        python_script: str,
        *,
        returns: "MayaConnection.ScriptReturn" = ScriptReturn.JSON,
    ):
        request_id = uuid.uuid4().hex
        if returns == MayaConnection.ScriptReturn.STDOUT:
            python_script = MayaConnection._update_script_to_capture_stdout(python_script)
        else:
            python_script = "_mcp_maya_results = None\n" + python_script
        python_script = (
            f"_mcp_maya_result_request_id = {request_id!r}\n"
            f"{python_script}\n"
            f"_mcp_maya_result_request_id = {request_id!r}\n"
        )

        initial_result = self._send_python_command(python_script, wrap_python_exec=True)
        initial_result = MayaConnection._clean_command_result(initial_result)

        if returns == MayaConnection.ScriptReturn.NONE:
            return None

        fetch_expression = (
            "__import__('json').dumps({"
            "'request_id': globals().get('_mcp_maya_result_request_id'), "
            "'result': globals().get('_mcp_maya_results')"
            "})"
        )
        result = self._send_python_command(fetch_expression)
        result = MayaConnection._clean_command_result(result)

        try:
            envelope = json.loads(result) if result else {}
        except Exception:
            envelope = {}

        if isinstance(envelope, dict) and envelope.get("request_id") == request_id:
            result = envelope.get("result")
            if not isinstance(result, str):
                return result
        else:
            result = initial_result

        output_var_tokens = {"_mcp_maya_results", "'_mcp_maya_results'", '"_mcp_maya_results"'}
        if not result or result == "\n" or result in output_var_tokens:
            result = initial_result

        try:
            result = json.loads(result)
        except Exception:
            pass

        return result

    def call_tool(self, tool_name: str, source_path: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Call a Maya tool, using the Maya-side resident executor when enabled."""
        if arguments is None:
            arguments = {}
        if tool_cache_disabled():
            python_script = load_maya_tool_source(tool_name, source_path, arguments)
            return self.run_python_script(python_script)

        source = Path(source_path).read_text(encoding="utf-8")
        source_hash = tool_source_hash(source)
        cache_key = (self.host, self.port, self.source_type, tool_name, source_hash)
        resident_key = (self.host, self.port, self.source_type, RESIDENT_EXECUTOR_VERSION)
        self.ensure_resident_executor()
        should_register = cache_key not in _KNOWN_MAYA_TOOL_CACHE_KEYS
        python_script = build_resident_tool_call_script(
            tool_name=tool_name,
            source=source,
            source_hash=source_hash,
            arguments=arguments,
            include_source=should_register,
        )
        result = self.run_python_script(python_script)
        if isinstance(result, dict) and result.get("_mcp_resident_missing"):
            _KNOWN_MAYA_RESIDENT_EXECUTOR_KEYS.discard(resident_key)
            self.ensure_resident_executor()
            result = self.run_python_script(
                build_resident_tool_call_script(
                    tool_name=tool_name,
                    source=source,
                    source_hash=source_hash,
                    arguments=arguments,
                    include_source=True,
                )
            )
        if isinstance(result, dict) and result.get("_mcp_cache_miss"):
            python_script = build_resident_tool_call_script(
                tool_name=tool_name,
                source=source,
                source_hash=source_hash,
                arguments=arguments,
                include_source=True,
            )
            result = self.run_python_script(python_script)
        if not (isinstance(result, dict) and result.get("_mcp_cache_miss")):
            _KNOWN_MAYA_TOOL_CACHE_KEYS.add(cache_key)
        return result

    def ensure_resident_executor(self) -> Dict[str, Any]:
        """Install the resident Maya executor once per commandPort session."""
        key = (self.host, self.port, self.source_type, RESIDENT_EXECUTOR_VERSION)
        if key in _KNOWN_MAYA_RESIDENT_EXECUTOR_KEYS:
            return {"success": True, "resident_cached_client_side": True}
        result = self.run_python_script(build_resident_executor_install_script())
        if not isinstance(result, dict) or not result.get("success"):
            raise RuntimeError(f"Failed to install MayaMCP resident executor: {result}")
        if result.get("version") != RESIDENT_EXECUTOR_VERSION:
            raise RuntimeError(
                "MayaMCP resident executor version mismatch: "
                f"expected {RESIDENT_EXECUTOR_VERSION}, got {result.get('version')}"
            )
        _KNOWN_MAYA_RESIDENT_EXECUTOR_KEYS.add(key)
        return result

    def run_cache_probe(self) -> Dict[str, Any]:
        """Probe whether the Maya-side cache registry is writable."""
        try:
            self.ensure_resident_executor()
        except Exception as exc:
            return {"success": False, "cache_writable": False, "message": str(exc)}
        script = """
import json
try:
    _mcp_tool_registry = globals().setdefault("_mcp_tool_registry", {})
    _mcp_tool_cache_stats = globals().setdefault(
        "_mcp_tool_cache_stats",
        {"loads": 0, "hits": 0, "misses": 0, "errors": 0, "scene_invalidations": 0},
    )
    _mcp_tool_registry["__probe__"] = {"tool_name": "__probe__", "source_hash": "probe"}
    del _mcp_tool_registry["__probe__"]
    _mcp_maya_results = json.dumps({
        "success": True,
        "cache_writable": True,
        "registry_size": len(_mcp_tool_registry),
        "stats": dict(_mcp_tool_cache_stats),
        "resident_version": globals().get("_mcp_resident_executor_version"),
    })
except Exception as exc:
    _mcp_maya_results = json.dumps({
        "success": False,
        "cache_writable": False,
        "message": str(exc),
    })
"""
        result = self.run_python_script(script)
        if isinstance(result, dict):
            return result
        return {"success": False, "message": str(result)}

    def run_live_probe(self) -> Dict[str, Any]:
        """Execute a read-only probe in Maya."""
        script = """
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "success": True,
    "maya_version": cmds.about(version=True),
    "api_version": cmds.about(apiVersion=True),
    "scene": cmds.file(query=True, sceneName=True) or "",
})
"""
        result = self.run_python_script(script)
        if isinstance(result, dict):
            return result
        return {"success": False, "message": str(result)}


def command_port_mel(port: int = 50009, source_type: str = "python") -> str:
    """Return a commandPort command suitable for Maya's Script Editor."""
    clean_source_type = source_type.lower().strip()
    return (
        f'commandPort -name ":{int(port)}" -sourceType "{clean_source_type}" '
        '-bufferSize 4096 -outputVar "_mcp_maya_results";'
    )


class OperationsManager:
    """Manage MCP tools discovered in the mayatools directory."""

    def __init__(self, tools_directory: str | os.PathLike[str] | None = None):
        self.tools_directory = get_tools_directory(tools_directory)
        self._paths: Dict[str, str] = {}
        self._tools: Dict[str, Tool] = {}

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_tool(self, name: str) -> Tool:
        return self._tools.get(name)

    def get_file_path(self, name: str) -> str:
        return self._paths.get(name)

    def get_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tool_records(self) -> List[Dict[str, Any]]:
        records = []
        for name in sorted(self._tools):
            path = Path(self._paths[name])
            try:
                rel = path.relative_to(self.tools_directory)
                category = rel.parts[0] if len(rel.parts) > 1 else "root"
            except ValueError:
                category = "external"
            records.append(
                {
                    "name": name,
                    "path": str(path),
                    "category": category,
                    "tool": self._tools[name],
                }
            )
        return records

    def find_tools(self):
        """Find all MCP tools in the mayatools directory."""
        self._paths.clear()
        self._tools.clear()
        for root, dirs, files in os.walk(self.tools_directory):
            dirs[:] = [directory for directory in dirs if directory not in {"__pycache__", "common"}]
            for file in files:
                if not file.endswith(".py") or file == "__init__.py":
                    continue
                name, _ = os.path.splitext(file)
                path = os.path.join(root, file)
                tool = OperationsManager._get_function_tool(name, path)

                if tool:
                    self._paths[name] = path
                    self._tools[name] = tool

    @staticmethod
    def _get_function_tool(maya_tool_name: str, filename: str) -> Tool:
        """Load a Python file as an MCP Tool and read function metadata."""
        try:
            spec = importlib.util.spec_from_file_location(maya_tool_name, filename)
            if spec is None or spec.loader is None:
                raise ImportError(f"Unable to create import spec for {filename}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, maya_tool_name)
        except Exception as exc:
            logger.error("Unable to pre-load %s because: %s", maya_tool_name, exc)
            return None

        func_doc = fn.__doc__ or ""

        sig = inspect.signature(fn)
        context_kwarg = None
        for param_name, param in sig.parameters.items():
            if get_origin(param.annotation) is not None:
                continue
            try:
                if inspect.isclass(param.annotation) and issubclass(param.annotation, Context):
                    context_kwarg = param_name
                    break
            except TypeError:
                continue

        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        return Tool(
            name=maya_tool_name,
            description=func_doc,
            inputSchema=parameters,
        )


def wrap_script_in_scoped_function(python_script: str, maya_tool_name: str, args: List[str]) -> str:
    spaced_python_script = "    " + python_script.replace("\n", "\n    ")
    return f"""
def _mcp_maya_scope({','.join(args)}):
    import json
    import traceback
    from pprint import pprint
{spaced_python_script}
    try:
        results = {maya_tool_name}({','.join([a + '=' + a for a in args])})
    except Exception as e:
        # print exception to the Maya console
        traceback.print_exc()
        results = dict([('success', False), ('message', 'Error: Maya tool failed with the follow message: ' + str(e))])

    if results and not isinstance(results, str):
        try:
            results = json.dumps(results)
        except Exception as e:
            print("MayaMCP: Error attempting to return results from tool {maya_tool_name} as JSON")
            pprint(results)
            return str(results)

    return results
"""


def load_maya_tool_source(
    maya_tool_name: str,
    filename: str,
    vars: Optional[Dict[str, Any]] = None,
    *,
    log: bool = False,
) -> str:
    """Load a Python source file and wrap it for execution in Maya."""
    if vars is None:
        vars = {}
    with open(filename, "r", encoding="utf-8") as file_obj:
        script = file_obj.read()

    results = wrap_script_in_scoped_function(script, maya_tool_name, list(vars.keys()))
    results += "\n_mcp_maya_results = _mcp_maya_scope("
    params = []
    for key, value in vars.items():
        params.append(f"{key}={repr(value)}")
    results += ",".join(params)
    results += ")\n\n"

    if log:
        logger.debug(results)

    return results


def tool_cache_disabled() -> bool:
    return os.environ.get("MAYA_MCP_DISABLE_TOOL_CACHE", "").lower().strip() in {"1", "true", "yes", "on"}


def tool_source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_resident_executor_install_script() -> str:
    """Build a script that installs the Maya-side resident tool executor."""
    return f"""
import base64
import json
import traceback
from pprint import pprint

_mcp_resident_executor_version = {RESIDENT_EXECUTOR_VERSION!r}
_mcp_tool_registry = globals().setdefault("_mcp_tool_registry", {{}})
_mcp_tool_cache_stats = globals().setdefault(
    "_mcp_tool_cache_stats",
    {{"loads": 0, "hits": 0, "misses": 0, "errors": 0, "scene_invalidations": 0}},
)

def _mcp_invalidate_tool_cache_for_scene_change(*args):
    registry = globals().setdefault("_mcp_tool_registry", {{}})
    registry.clear()
    stats = globals().setdefault(
        "_mcp_tool_cache_stats",
        {{"loads": 0, "hits": 0, "misses": 0, "errors": 0, "scene_invalidations": 0}},
    )
    stats["scene_invalidations"] = stats.get("scene_invalidations", 0) + 1

def _mcp_ensure_scene_cache_invalidation_jobs():
    callbacks = globals().get("_mcp_tool_cache_scene_callbacks")
    if not callbacks:
        try:
            import maya.api.OpenMaya as om

            callback_ids = []
            for message in (
                om.MSceneMessage.kBeforeOpen,
                om.MSceneMessage.kAfterOpen,
                om.MSceneMessage.kBeforeNew,
                om.MSceneMessage.kAfterNew,
            ):
                try:
                    callback_ids.append(
                        om.MSceneMessage.addCallback(
                            message,
                            _mcp_invalidate_tool_cache_for_scene_change,
                        )
                    )
                except Exception:
                    pass
            globals()["_mcp_tool_cache_scene_callbacks"] = callback_ids
        except Exception:
            globals()["_mcp_tool_cache_scene_callbacks"] = []

    jobs = globals().get("_mcp_tool_cache_scene_jobs")
    if jobs:
        return
    try:
        import maya.cmds as cmds
    except Exception:
        globals()["_mcp_tool_cache_scene_jobs"] = []
        return
    created_jobs = []
    for event_name in ("SceneOpened", "NewSceneOpened"):
        try:
            job_id = cmds.scriptJob(
                event=[event_name, _mcp_invalidate_tool_cache_for_scene_change],
                protected=True,
            )
            created_jobs.append(job_id)
        except Exception:
            pass
    globals()["_mcp_tool_cache_scene_jobs"] = created_jobs

def _mcp_tool_cache_key(tool_name, source_hash):
    return tool_name + ":" + source_hash

def _mcp_register_tool(tool_name, source_hash, source_b64):
    source = base64.b64decode(source_b64.encode("ascii")).decode("utf-8")
    namespace = {{}}
    exec(compile(source, "<MayaMCP:" + tool_name + ":" + source_hash + ">", "exec"), namespace, namespace)
    fn = namespace.get(tool_name)
    if not callable(fn):
        raise RuntimeError("Tool source did not define callable " + tool_name)
    _mcp_tool_registry[_mcp_tool_cache_key(tool_name, source_hash)] = {{
        "function": fn,
        "tool_name": tool_name,
        "source_hash": source_hash,
    }}
    _mcp_tool_cache_stats["loads"] = _mcp_tool_cache_stats.get("loads", 0) + 1

def _mcp_call_cached_tool(tool_name, source_hash, args):
    key = _mcp_tool_cache_key(tool_name, source_hash)
    entry = _mcp_tool_registry.get(key)
    if not entry:
        _mcp_tool_cache_stats["misses"] = _mcp_tool_cache_stats.get("misses", 0) + 1
        return json.dumps({{
            "success": False,
            "message": "MayaMCP tool cache miss.",
            "_mcp_cache_miss": True,
            "tool": tool_name,
            "source_hash": source_hash,
        }})
    _mcp_tool_cache_stats["hits"] = _mcp_tool_cache_stats.get("hits", 0) + 1
    try:
        results = entry["function"](**args)
    except Exception as exc:
        traceback.print_exc()
        _mcp_tool_cache_stats["errors"] = _mcp_tool_cache_stats.get("errors", 0) + 1
        results = {{
            "success": False,
            "message": "Error: Maya tool failed with the follow message: " + str(exc),
        }}
    if results and not isinstance(results, str):
        try:
            return json.dumps(results)
        except Exception:
            print("MayaMCP: Error attempting to return resident tool results as JSON")
            pprint(results)
            return str(results)
    return results

def _mcp_call_resident_tool(tool_name, source_hash, source_b64, args_json):
    _mcp_ensure_scene_cache_invalidation_jobs()
    args = json.loads(args_json)
    if source_b64:
        _mcp_register_tool(tool_name, source_hash, source_b64)
    return _mcp_call_cached_tool(tool_name, source_hash, args)

_mcp_ensure_scene_cache_invalidation_jobs()
_mcp_maya_results = json.dumps({{
    "success": True,
    "resident_executor": True,
    "version": _mcp_resident_executor_version,
    "registry_size": len(_mcp_tool_registry),
    "stats": dict(_mcp_tool_cache_stats),
}})
"""


def build_resident_tool_call_script(
    tool_name: str,
    source: str,
    source_hash: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    include_source: bool = False,
) -> str:
    """Build a lightweight script that calls the resident Maya executor."""
    if arguments is None:
        arguments = {}
    source_b64 = base64.b64encode(source.encode("utf-8")).decode("ascii") if include_source else ""
    arguments_json = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
    return f"""
import json
import traceback

_mcp_tool_name = {tool_name!r}
_mcp_tool_source_hash = {source_hash!r}
_mcp_tool_source_b64 = {source_b64!r}
_mcp_tool_args_json = {arguments_json!r}

try:
    _mcp_maya_results = _mcp_call_resident_tool(
        _mcp_tool_name,
        _mcp_tool_source_hash,
        _mcp_tool_source_b64,
        _mcp_tool_args_json,
    )
except NameError as exc:
    _mcp_maya_results = json.dumps({{
        "success": False,
        "message": "MayaMCP resident executor is not installed.",
        "_mcp_resident_missing": True,
        "tool": _mcp_tool_name,
        "source_hash": _mcp_tool_source_hash,
    }})
except Exception as exc:
    traceback.print_exc()
    _mcp_maya_results = json.dumps({{
        "success": False,
        "message": "Error: MayaMCP resident executor failed: " + str(exc),
        "tool": _mcp_tool_name,
        "source_hash": _mcp_tool_source_hash,
    }})
"""


def build_cached_tool_call_script(
    tool_name: str,
    source: str,
    source_hash: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    include_source: bool = False,
) -> str:
    """Build a Maya script that calls a cached tool function."""
    if arguments is None:
        arguments = {}
    source_b64 = base64.b64encode(source.encode("utf-8")).decode("ascii") if include_source else ""
    arguments_json = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
    return f"""
import base64
import json
import traceback
from pprint import pprint

_mcp_tool_name = {tool_name!r}
_mcp_tool_source_hash = {source_hash!r}
_mcp_tool_source_b64 = {source_b64!r}
_mcp_tool_args = json.loads({arguments_json!r})

_mcp_tool_registry = globals().setdefault("_mcp_tool_registry", {{}})
_mcp_tool_cache_stats = globals().setdefault(
    "_mcp_tool_cache_stats",
    {{"loads": 0, "hits": 0, "misses": 0, "errors": 0, "scene_invalidations": 0}},
)

def _mcp_invalidate_tool_cache_for_scene_change(*args):
    registry = globals().setdefault("_mcp_tool_registry", {{}})
    registry.clear()
    stats = globals().setdefault(
        "_mcp_tool_cache_stats",
        {{"loads": 0, "hits": 0, "misses": 0, "errors": 0, "scene_invalidations": 0}},
    )
    stats["scene_invalidations"] = stats.get("scene_invalidations", 0) + 1

def _mcp_ensure_scene_cache_invalidation_jobs():
    callbacks = globals().get("_mcp_tool_cache_scene_callbacks")
    if not callbacks:
        try:
            import maya.api.OpenMaya as om

            callback_ids = []
            for message in (
                om.MSceneMessage.kBeforeOpen,
                om.MSceneMessage.kAfterOpen,
                om.MSceneMessage.kBeforeNew,
                om.MSceneMessage.kAfterNew,
            ):
                try:
                    callback_ids.append(
                        om.MSceneMessage.addCallback(
                            message,
                            _mcp_invalidate_tool_cache_for_scene_change,
                        )
                    )
                except Exception:
                    pass
            globals()["_mcp_tool_cache_scene_callbacks"] = callback_ids
        except Exception:
            globals()["_mcp_tool_cache_scene_callbacks"] = []

    jobs = globals().get("_mcp_tool_cache_scene_jobs")
    if jobs:
        return
    try:
        import maya.cmds as cmds
    except Exception:
        globals()["_mcp_tool_cache_scene_jobs"] = []
        return
    created_jobs = []
    for event_name in ("SceneOpened", "NewSceneOpened"):
        try:
            job_id = cmds.scriptJob(
                event=[event_name, _mcp_invalidate_tool_cache_for_scene_change],
                protected=True,
            )
            created_jobs.append(job_id)
        except Exception:
            pass
    globals()["_mcp_tool_cache_scene_jobs"] = created_jobs

_mcp_ensure_scene_cache_invalidation_jobs()

def _mcp_tool_cache_key(tool_name, source_hash):
    return tool_name + ":" + source_hash

def _mcp_register_tool(tool_name, source_hash, source_b64):
    source = base64.b64decode(source_b64.encode("ascii")).decode("utf-8")
    namespace = {{}}
    exec(compile(source, "<MayaMCP:" + tool_name + ":" + source_hash + ">", "exec"), namespace, namespace)
    fn = namespace.get(tool_name)
    if not callable(fn):
        raise RuntimeError("Tool source did not define callable " + tool_name)
    _mcp_tool_registry[_mcp_tool_cache_key(tool_name, source_hash)] = {{
        "function": fn,
        "tool_name": tool_name,
        "source_hash": source_hash,
    }}
    _mcp_tool_cache_stats["loads"] = _mcp_tool_cache_stats.get("loads", 0) + 1

def _mcp_call_cached_tool(tool_name, source_hash, args):
    key = _mcp_tool_cache_key(tool_name, source_hash)
    entry = _mcp_tool_registry.get(key)
    if not entry:
        _mcp_tool_cache_stats["misses"] = _mcp_tool_cache_stats.get("misses", 0) + 1
        return json.dumps({{
            "success": False,
            "message": "MayaMCP tool cache miss.",
            "_mcp_cache_miss": True,
            "tool": tool_name,
            "source_hash": source_hash,
        }})
    _mcp_tool_cache_stats["hits"] = _mcp_tool_cache_stats.get("hits", 0) + 1
    try:
        results = entry["function"](**args)
    except Exception as exc:
        traceback.print_exc()
        _mcp_tool_cache_stats["errors"] = _mcp_tool_cache_stats.get("errors", 0) + 1
        results = {{
            "success": False,
            "message": "Error: Maya tool failed with the follow message: " + str(exc),
        }}
    if results and not isinstance(results, str):
        try:
            return json.dumps(results)
        except Exception:
            print("MayaMCP: Error attempting to return cached tool results as JSON")
            pprint(results)
            return str(results)
    return results

try:
    if _mcp_tool_source_b64:
        _mcp_register_tool(_mcp_tool_name, _mcp_tool_source_hash, _mcp_tool_source_b64)
    _mcp_maya_results = _mcp_call_cached_tool(_mcp_tool_name, _mcp_tool_source_hash, _mcp_tool_args)
except Exception as exc:
    traceback.print_exc()
    _mcp_tool_cache_stats["errors"] = _mcp_tool_cache_stats.get("errors", 0) + 1
    _mcp_maya_results = json.dumps({{
        "success": False,
        "message": "Error: MayaMCP cached tool runtime failed: " + str(exc),
    }})
"""


def convert_to_content(
    result: Any,
) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Convert a result to a sequence of MCP content objects."""
    if result is None:
        return []

    if isinstance(result, TextContent | ImageContent | EmbeddedResource):
        return [result]

    if isinstance(result, Image):
        return [result.to_image_content()]

    if isinstance(result, list | tuple):
        return list(chain.from_iterable(convert_to_content(item) for item in result))  # type: ignore[reportUnknownVariableType]

    if not isinstance(result, str):
        try:
            result = json.dumps(pydantic_core.to_jsonable_python(result))
        except Exception:
            result = str(result)

    return [TextContent(type="text", text=result)]


server = Server("MayaMCP")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Handle requests from MCP clients to list available tools."""
    logger.info("Requesting a list of tools.")
    return _operation_manager.get_tools()


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict | None,
) -> list[TextContent | ImageContent | EmbeddedResource]:
    """Handle requests from MCP clients to call a Maya tool."""
    logger.info("Calling tool %s with arguments: %s", name, pprint.pformat(arguments))

    path = _operation_manager.get_file_path(name)
    if not path:
        error_msg = f"Tool {name} not found."
        logger.error(error_msg)
        return convert_to_content({"success": False, "message": error_msg})

    try:
        maya_conn = MayaConnection()
        results = maya_conn.call_tool(name, path, arguments or {})
        results = compact_result(results, prefix=name)
        converted_results = convert_to_content(results)
    except Exception as exc:
        logger.critical(exc, exc_info=True)
        error_msg = f"Error: tool {name} failed to run. Reason {exc}"
        logger.error(error_msg)
        return convert_to_content({"success": False, "message": error_msg})

    if converted_results:
        return converted_results

    return convert_to_content({"success": True})


def build_operation_manager(tools_directory: str | os.PathLike[str] | None = None) -> OperationsManager:
    manager = OperationsManager(tools_directory)
    manager.find_tools()
    return manager


async def run(tools_directory: str | os.PathLike[str] | None = None):
    global _operation_manager
    configure_logging()
    _operation_manager = build_operation_manager(tools_directory)
    logger.info("MayaMCP v%s server starting up", __version__)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="MayaMCP",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(run())
