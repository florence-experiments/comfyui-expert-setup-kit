"""Command line: chat, one-shot ask, run single tools, doctor, web UI, MCP server."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .config import load_config


def _p(s: str = "", end: str = "\n"):
    try:
        print(s, end=end, flush=True)
    except UnicodeEncodeError:  # old Windows consoles
        print(s.encode("ascii", "replace").decode(), end=end, flush=True)


def yes_no(question: str) -> bool:
    try:
        a = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return a in ("y", "yes")


def drive(agent, session, events, verbose: bool = False) -> None:
    """Print events; handle confirmations with a y/N prompt."""
    while True:
        streamed = False
        need = None
        for ev in events:
            t = ev["type"]
            if t == "delta":
                _p(ev["text"], end="")
                streamed = True
            elif t == "retract":
                if streamed:
                    _p("\n   [self-check: re-checking that answer...]")
                streamed = False
            elif t == "thinking":
                if verbose:
                    _p(f"\033[2m{ev['text']}\033[0m", end="")
            elif t == "status":
                _p(f"\n   [{ev['text']}]")
            elif t == "assistant":
                if not streamed:
                    _p(ev["text"])
                streamed = False
            elif t == "tool_call":
                if streamed:
                    _p()
                streamed = False
                _p(f"   -> {ev['name']}({json.dumps(ev['args'], ensure_ascii=False)[:200]})")
            elif t == "tool_result":
                _p(f"   <- {ev['name']}: {ev['short']}")
                if verbose:
                    _p(json.dumps(ev["result"], ensure_ascii=False, indent=1)[:3000])
            elif t == "confirm":
                need = ev
            elif t == "final":
                if not streamed:
                    _p(ev["text"])
                elif ev.get("unverified"):
                    _p("\n\n> Not verified by a tool: " + "; ".join(ev["unverified"][:15]))
                _p()
            elif t == "error":
                _p(f"\n[error] {ev['text']}")
        if not need:
            return
        _p(f"\n*** CONFIRM: {need['summary']}")
        _p("    args: " + json.dumps(need["args"], ensure_ascii=False)[:400])
        if need.get("preview"):
            _p("    dry run: " + json.dumps(need["preview"], ensure_ascii=False)[:600])
        events = agent.resume(session, yes_no("    Do it?"))


def cmd_chat(args):
    from .agent import Agent, Session, save_session
    agent = Agent()
    try:
        _p(f"ComfyUI Expert - model: {agent.model()}  (type /exit to quit, /new for a new chat)")
    except Exception as e:
        _p(str(e))
        return 1
    session = Session()
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q in ("/exit", "/quit"):
            break
        if q == "/new":
            session = Session()
            _p("(new chat)")
            continue
        _p("expert> ", end="")
        drive(agent, session, agent.chat(session, q), args.verbose)
        save_session(session)
    return 0


def cmd_ask(args):
    from .agent import Agent, Session
    agent = Agent()
    s = Session()
    drive(agent, s, agent.chat(s, " ".join(args.question)), args.verbose)
    return 0


def cmd_tools(args):
    from .tools import load_all
    for n, t in load_all().items():
        _p(f"{n:28s} {'[needs confirm] ' if t.gated else ''}{t.description[:110]}")
    return 0


def cmd_tool(args):
    from .tools import load_all, run_tool
    reg = load_all()
    t = reg.get(args.name)
    if not t:
        _p(f"Unknown tool. Try: {', '.join(reg)}")
        return 1
    a = json.loads(args.json or "{}")
    if t.gated and a.get("confirm") and not yes_no(f"Really run {args.name} for real?"):
        a["confirm"] = False
    _p(json.dumps(run_tool(args.name, a), ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_doctor(args):
    import requests
    cfg = load_config()
    ok = True
    _p("ComfyUI Expert - doctor")
    b = cfg["llm"]["base_url"].rstrip("/")
    try:
        r = requests.get(b + "/models", timeout=5).json()
        _p(f"[ok]  llama-server {b}: model {r['data'][0]['id']}")
        root = b[:-3] if b.endswith("/v1") else b
        try:
            props = requests.get(root + "/props", timeout=5).json()
            n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx") or props.get("n_ctx")
            tmpl = props.get("chat_template", "")
            _p(f"      context (-c) = {n_ctx}" + ("  <-- small! use -c 32768 or more" if n_ctx and int(n_ctx) < 24000 else ""))
            if tmpl and "tool" not in tmpl:
                _p("      chat template has no tool support - start llama-server with --jinja")
        except Exception:
            pass
    except Exception as e:
        ok = False
        _p(f"[!!]  llama-server not reachable at {b} ({type(e).__name__}). Start it with --jinja -c 32768")
    u = cfg["comfyui"]["url"]
    try:
        st = requests.get(u + "/system_stats", timeout=5).json()
        dev = (st.get("devices") or [{}])[0]
        _p(f"[ok]  ComfyUI {u}: v{st.get('system', {}).get('comfyui_version')} on {dev.get('name')}")
    except Exception:
        _p(f"[..]  ComfyUI not running at {u} (fine - the expert falls back to a bundled node list)")
    root = cfg.comfy_root
    _p(f"[{'ok' if root and root.exists() else '!!'}]  ComfyUI folder: {root}")
    for p in cfg.model_roots():
        _p(f"[{'ok' if p.exists() else '..'}]  model folder: {p}")
    for p in cfg.workflow_dirs():
        _p(f"[{'ok' if p.exists() else '..'}]  workflow folder: {p}")
    _p(f"      new workflows go to: {cfg.generated_dir()}")
    for k, env in (("civitai_api_key", "CIVITAI_API_KEY"), ("hf_token", "HF_TOKEN"), ("github_token", "GITHUB_TOKEN")):
        _p(f"[{'ok' if cfg.key(k) else '..'}]  {env} {'set' if cfg.key(k) else 'not set (optional)'}")
    return 0 if ok else 1


def cmd_web(args):
    from .web.server import main as web_main
    return web_main(host=args.host, port=args.port, open_browser=not args.no_browser)


def cmd_mcp(args):
    from .mcp_server import main as mcp_main
    return mcp_main(transport=args.transport, host=args.host, port=args.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="comfy_expert", description="ComfyUI Expert - local ComfyUI assistant for llama.cpp")
    ap.add_argument("--config", help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("chat", help="interactive chat in the terminal")
    c.add_argument("-v", "--verbose", action="store_true")
    a = sub.add_parser("ask", help="one question, then exit")
    a.add_argument("question", nargs="+")
    a.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("tools", help="list tools")
    t = sub.add_parser("tool", help="run one tool directly: tool <name> '<json args>'")
    t.add_argument("name")
    t.add_argument("json", nargs="?")
    sub.add_parser("doctor", help="check llama-server, ComfyUI and folders")
    w = sub.add_parser("web", help="start the browser chat UI")
    w.add_argument("--host")
    w.add_argument("--port", type=int)
    w.add_argument("--no-browser", action="store_true")
    m = sub.add_parser("mcp", help="run as an MCP server (for OpenHands, Claude Desktop, ...)")
    m.add_argument("--transport", choices=["stdio", "http", "streamable-http", "sse"], default="stdio")
    m.add_argument("--host")
    m.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    if args.config:
        os.environ["COMFY_EXPERT_CONFIG"] = args.config
    load_config(args.config, reload=True)
    fn = {"chat": cmd_chat, "ask": cmd_ask, "tools": cmd_tools, "tool": cmd_tool, "doctor": cmd_doctor,
          "web": cmd_web, "mcp": cmd_mcp}.get(args.cmd or "web")
    if args.cmd is None:
        args.host, args.port, args.no_browser = None, None, False
    return fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
