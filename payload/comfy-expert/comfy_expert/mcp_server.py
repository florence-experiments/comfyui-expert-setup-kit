"""MCP server exposing the ComfyUI Expert tools + knowledge pack (official Python `mcp` SDK).

Transports:
  stdio            : python -m comfy_expert mcp
  streamable HTTP  : python -m comfy_expert mcp --transport http --host 0.0.0.0 --port 8765   -> http://<host>:8765/mcp
  SSE (legacy)     : python -m comfy_expert mcp --transport sse  --host 0.0.0.0 --port 8765   -> http://<host>:8765/sse
Gated tools (write_workflow, download_file, comfy_queue_test) are dry runs unless called with confirm=true.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
from typing import Annotated, Any, Optional

from pydantic import Field

from .config import load_config
from .tools import REGISTRY, load_all, run_tool

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
    MCP_V2 = True
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore
    MCP_V2 = False

PY_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list, "object": dict}

INSTRUCTIONS = (
    "ComfyUI Expert tools for a local ComfyUI install (Windows, AMD 16 GB). Rules: never state node types, model files or URLs "
    "you have not verified with these tools; use comfy_node_info / find_node_pack for nodes, civitai_* / hf_* / model_archive_search "
    "for models; change workflows only via edit_workflow (drafts), validate, then write_workflow (saves a NEW file). "
    "write_workflow, download_file and comfy_queue_test are dry runs unless confirm=true - ask the human first. "
    "Knowledge: kb_search / kb_read / get_playbook (also exposed as resources comfy-expert://kb/<topic>). "
    "NSFW allowed for the adult user, but characters must always be adults."
)


def _make_wrapper(t):
    props = t.parameters.get("properties", {})
    required = set(t.parameters.get("required", []))
    params = []
    for pname, spec in props.items():
        typ = PY_TYPES.get(spec.get("type"), Any)
        if spec.get("type") == "array" and isinstance(spec.get("items"), dict) and spec["items"].get("type") in PY_TYPES:
            typ = list[PY_TYPES[spec["items"]["type"]]]
        if spec.get("description"):
            typ = Annotated[typ, Field(description=spec["description"][:500])]
        if pname in required:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=typ))
        else:
            default = spec.get("default", None)
            ann = typ if default is not None else Optional[typ]
            if spec.get("enum"):
                pass
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=ann))

    def wrapper(**kwargs) -> str:
        args = {k: v for k, v in kwargs.items() if v is not None}
        res = run_tool(t.name, args)
        return json.dumps(res, ensure_ascii=False, default=str)

    wrapper.__name__ = t.name
    wrapper.__signature__ = inspect.Signature(params, return_annotation=str)
    wrapper.__annotations__ = {p.name: p.annotation for p in params} | {"return": str}
    wrapper.__doc__ = t.description
    return wrapper


def _describe(t) -> str:
    d = t.description
    props = t.parameters.get("properties", {})
    if t.gated:
        d += ("\nSAFETY: dry run by default. Only call with confirm=true after the human explicitly approved this exact action.")
    return d[:4000]


def build_server(host: str = "127.0.0.1", port: int = 8765):
    load_all()
    if MCP_V2:
        server = _Server(name="comfyui-expert", title="ComfyUI Expert", instructions=INSTRUCTIONS, version="1.0")
    else:  # pragma: no cover
        server = _Server("comfyui-expert", instructions=INSTRUCTIONS, host=host, port=port)
    for t in REGISTRY.values():
        kw = {}
        try:
            from mcp.types import ToolAnnotations
            kw["annotations"] = ToolAnnotations(readOnlyHint=not t.gated, destructiveHint=False if not t.gated else None,
                                                openWorldHint=t.category in ("web", "civitai", "hf"))
        except Exception:
            pass
        server.add_tool(_make_wrapper(t), name=t.name, description=_describe(t), **kw)

    from .tools.knowledge import playbooks, topics

    def _reader(path):
        def read() -> str:
            return path.read_text(encoding="utf-8")
        return read

    for name, p in topics().items():
        server.resource(f"comfy-expert://kb/{name}", name=name, description=f"Knowledge: {name}", mime_type="text/markdown")(_reader(p))
    for name, p in playbooks().items():
        server.resource(f"comfy-expert://playbook/{name}", name=f"playbook_{name}", description=f"Playbook: {name}",
                        mime_type="text/markdown")(_reader(p))
    return server


class _TokenAuth:
    """Optional bearer-token check for the HTTP transports (set mcp.token in config.yaml or MCP_TOKEN)."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token:
            hdrs = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            got = hdrs.get("authorization", "").removeprefix("Bearer ").strip() or hdrs.get("x-api-key", "")
            if got != self.token:
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


def main(transport: str = "stdio", host: str | None = None, port: int | None = None) -> int:
    cfg = load_config()
    mc = cfg.get("mcp", {})
    host = host or mc.get("host") or "127.0.0.1"
    port = int(port or mc.get("port") or 8765)
    server = build_server(host, port)
    if transport == "stdio":
        server.run("stdio")
        return 0
    if not MCP_V2:  # pragma: no cover
        server.run("streamable-http" if transport in ("http", "streamable-http") else "sse")
        return 0
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings
    extra = [h for h in (mc.get("allowed_hosts") or []) if h]
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "host.docker.internal:*"] + [f"{h}:*" if ":" not in h else h for h in extra]
    sec = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                    allowed_origins=["http://" + h for h in hosts])
    if transport in ("http", "streamable-http"):
        app = server.streamable_http_app(streamable_http_path="/mcp", transport_security=sec, host=host)
        path = "/mcp"
    else:
        app = server.sse_app(transport_security=sec, host=host)
        path = "/sse"
    token = os.environ.get("MCP_TOKEN") or mc.get("token") or ""
    if token:
        app = _TokenAuth(app, token)
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"ComfyUI Expert MCP server ({transport}) on http://{shown}:{port}{path}"
          + ("  - from Docker use http://host.docker.internal:%d%s" % (port, path) if host in ("0.0.0.0", "::") else "")
          + ("  [bearer token required]" if token else ""), file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2] or ["stdio"])))
