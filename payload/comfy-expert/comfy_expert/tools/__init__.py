"""Tool registry. Each tool = python function + JSON schema + safety flag."""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]
    gated: bool = False          # writes / downloads / queues: needs human "yes"
    category: str = "general"

    def openai_schema(self) -> dict:
        params = json.loads(json.dumps(self.parameters))
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": params}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None,
         gated: bool = False, category: str = "general"):
    props = dict(properties or {})
    if gated:
        props["confirm"] = {"type": "boolean", "description": "Must be true to actually do it. false (default) = dry run that only shows what would happen.", "default": False}
    schema = {"type": "object", "properties": props, "required": list(required or [])}

    def deco(fn):
        REGISTRY[name] = Tool(name, description, schema, fn, gated, category)
        return fn
    return deco


class ToolError(Exception):
    pass


def run_tool(name: str, args: dict | None) -> dict:
    """Run a tool and always return a JSON-able dict (never raises)."""
    t = REGISTRY.get(name)
    if t is None:
        return {"ok": False, "error": f"Unknown tool '{name}'. Available: {', '.join(sorted(REGISTRY))}"}
    if args is not None and not isinstance(args, dict):
        return {"ok": False, "error": "Tool arguments must be a JSON object", "schema": t.parameters}
    args = dict(args or {})
    allowed = set(t.parameters.get("properties", {}))
    unknown = [k for k in args if k not in allowed]
    for k in unknown:
        args.pop(k)
    missing = [k for k in t.parameters.get("required", []) if k not in args]
    if missing:
        return {"ok": False, "error": f"Missing required argument(s): {missing}", "schema": t.parameters}
    try:
        res = t.func(**args)
        if not isinstance(res, dict):
            res = {"result": res}
        res.setdefault("ok", True)
        if unknown:
            res["ignored_arguments"] = unknown
        return res
    except ToolError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # pragma: no cover - safety net
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)[-1500:]}


def load_all() -> dict[str, Tool]:
    # import modules for their @tool side effects
    from . import knowledge, web, civitai, hf, comfy, workflow, downloads, imageprompt, lessons  # noqa: F401
    return REGISTRY


# ---------------------------------------------------------------- Stop button support
import contextvars as _cv
import threading as _th


class Stopped(Exception):
    """The user pressed Stop: abandon the current turn."""


class Turn:
    """Runtime state of one chat turn (never saved): the Stop flag, the open llama-server response
    and the ComfyUI prompts this turn queued, so Stop can cancel all of them."""

    def __init__(self):
        self.stop = _th.Event()
        self.resp = None
        self.comfy_prompts: list[str] = []
        self.comfy_url: str | None = None


TURN: "_cv.ContextVar[Turn | None]" = _cv.ContextVar("comfy_expert_turn", default=None)
