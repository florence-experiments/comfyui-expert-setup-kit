"""Workflow tools: find, read, summarise, validate, edit (as drafts), save NEW files, test-queue."""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from .net import human_size
from . import tool, ToolError
from .comfy import get_object_info, comfy_url, comfy_alive, cancel_prompts
from .net import session
from . import wfcore
from ..config import load_config, APP_DIR, PKG_DIR

TEMPLATES_DIR = PKG_DIR / "templates"
DRAFTS_DIR = APP_DIR / "drafts"
DRAFTS: dict[str, dict] = {}


def _resolve_path(path: str) -> Path:
    p = Path(path.strip().strip('"'))
    if p.is_file():
        return p
    cands = []
    for d in load_config().workflow_dirs():
        if (d / path).is_file():
            return d / path
        if d.is_dir():
            for f in d.rglob("*.json"):
                if f.name.lower() == p.name.lower() or f.stem.lower() == p.stem.lower():
                    cands.append(f)
    if len(cands) == 1:
        return cands[0]
    if cands:
        raise ToolError(f"Several workflows match '{path}': {[str(c) for c in cands[:10]]}")
    raise ToolError(f"Workflow '{path}' not found. Use list_workflows to see available files.")


def official_templates_dir() -> Path | None:
    """Official ComfyUI templates shipped inside ComfyUI's own Python (read-only use)."""
    cfg = load_config()
    root = cfg.comfy_root
    cands = []
    if root:
        for py in (root.parent / "python_embeded", root / "venv", root / ".venv", root.parent / "venv"):
            cands += [py / "Lib" / "site-packages", *(py / "lib").glob("python3*/site-packages")]
    extra = cfg.get("comfyui", {}).get("official_templates_dir")
    if extra:
        cands.insert(0, Path(extra))
    for c in cands:
        for sub in ("comfyui_workflow_templates_json/templates", "comfyui_workflow_templates/templates", ""):
            d = c / sub if sub else c
            if (d / "index.json").is_file():
                return d
    return None


def load_any(source: str) -> tuple[dict, str]:
    """source = draft id | template name | official:<name> | file path | file name in workflow dirs."""
    if source.startswith("official:"):
        d = official_templates_dir()
        name = source.split(":", 1)[1].removesuffix(".json")
        if not d or not (d / f"{name}.json").is_file():
            raise ToolError(f"Official template '{name}' not found. Use list_official_templates to see names.")
        return json.loads((d / f"{name}.json").read_text(encoding="utf-8")), f"official template {name}"
    if source in DRAFTS:
        return DRAFTS[source]["wf"], f"draft {source}"
    f = DRAFTS_DIR / f"{source}.json"
    if re.fullmatch(r"d_[0-9a-f]{6,}", source or "") and f.is_file():
        d = json.loads(f.read_text(encoding="utf-8"))
        DRAFTS[source] = d
        return d["wf"], f"draft {source}"
    t = TEMPLATES_DIR / (source if source.endswith(".json") else source + ".json")
    if t.is_file() and not Path(source).is_absolute():
        return json.loads(t.read_text(encoding="utf-8")), f"template {t.stem}"
    p = _resolve_path(source)
    try:
        return wfcore.parse_workflow_bytes(p.read_bytes(), p.name), str(p)
    except (ValueError, json.JSONDecodeError) as e:
        raise ToolError(f"Could not read {p}: {e}")


def _new_draft(wf: dict, origin: str, log: list[str]) -> str:
    did = "d_" + uuid.uuid4().hex[:8]
    DRAFTS[did] = {"wf": wf, "origin": origin, "log": log, "created": time.time()}
    try:
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        (DRAFTS_DIR / f"{did}.json").write_text(json.dumps(DRAFTS[did]), encoding="utf-8")
    except OSError:
        pass
    return did


@tool("list_workflows",
      "List the user's saved workflow files (.json) in the configured workflow folders, newest first.",
      {"match": {"type": "string", "default": ""}, "limit": {"type": "integer", "default": 60}}, [], category="workflow")
def list_workflows(match: str = "", limit: int = 60):
    rows = []
    for d in load_config().workflow_dirs():
        if not d.is_dir():
            continue
        for f in d.rglob("*.json"):
            if match and match.lower() not in str(f).lower():
                continue
            st = f.stat()
            rows.append({"file": str(f), "name": f.name, "folder": str(f.parent), "size_kb": round(st.st_size / 1024, 1),
                         "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"), "_t": st.st_mtime})
    rows.sort(key=lambda r: -r["_t"])
    for r in rows:
        r.pop("_t")
    return {"workflow_dirs": [str(d) for d in load_config().workflow_dirs()], "count": len(rows),
            "workflows": rows[: int(limit or 60)],
            "templates": [t.stem for t in sorted(TEMPLATES_DIR.glob("*.json"))]}


@tool("read_workflow",
      "Read a workflow (file path, file name from list_workflows, ComfyUI PNG with embedded workflow, template name or draft id) "
      "and return its raw JSON (trimmed). Usually prefer summarize_workflow.",
      {"source": {"type": "string"}, "max_chars": {"type": "integer", "default": 12000}}, ["source"], category="workflow")
def read_workflow(source: str, max_chars: int = 12000):
    wf, where = load_any(source)
    fmt, _ = wfcore.unwrap(wf)
    txt = json.dumps(wf, separators=(",", ":"))
    m = max(1000, min(int(max_chars or 12000), 40000))
    return {"source": where, "format": fmt, "chars": len(txt), "json": txt[:m], "truncated": len(txt) > m}


@tool("summarize_workflow",
      "Explain a workflow: model family, every model/LoRA file (and whether it exists locally), prompts, sampler settings, "
      "image size, groups, node list with named widget values, pipeline order, missing node types and anime-style signals.",
      {"source": {"type": "string", "description": "path / file name / template / draft id"}}, ["source"], category="workflow")
def summarize_workflow(source: str):
    wf, where = load_any(source)
    oi, src = get_object_info()
    try:
        s = wfcore.summarize(wf, oi)
    except ValueError as e:
        raise ToolError(str(e))
    s["source"] = where
    s["node_types_from"] = src
    return s


@tool("validate_workflow",
      "Check a workflow before saving/using it: all node types installed, links consistent and type-correct, required inputs "
      "connected, widget values valid, model files exist locally (missing ones are listed as to-download).",
      {"source": {"type": "string", "description": "draft id, path, file name or template"}}, ["source"], category="workflow")
def validate_workflow(source: str):
    wf, where = load_any(source)
    oi, src = get_object_info()
    res = wfcore.validate(wf, oi, src)
    res["source"] = where
    return res


EDIT_OPS_DOC = (
    "List of operations applied in order to a COPY (the original file is never changed). Ops: "
    "{op:'set_widget', node:<id>, widget:'<name>' or index, value:<v>} | "
    "{op:'remove_node', node:<id>, reconnect:true} (reconnect passes MODEL/CLIP through, ideal for removing a LoRA) | "
    "{op:'add_node', type:'<NodeType>', widgets:{name:value}, pos:[x,y], ref:'name'} (later ops can use node:'$name') | "
    "{op:'connect', from:<id>, from_slot:<index or output name/type>, to:<id>, to_input:'<input name>'} | "
    "{op:'disconnect', node:<id>, input:'<name>'} | {op:'replace_node', node:<id>, type:'<NewType>', widgets:{...}} | "
    "{op:'set_mode', node:<id>, mode:'active'|'bypass'|'mute'} | {op:'set_title', node:<id>, title:'..'} | "
    "{op:'add_note', text:'..', pos:[x,y]} | {op:'add_group', title:'..', bounding:[x,y,w,h]}")


@tool("edit_workflow",
      "Make a modified copy of a workflow as a DRAFT (nothing is written to disk in the user's folders). "
      "Start from a file, template or an earlier draft id. Returns a new draft id plus an automatic validation report. "
      "Prefer small edits (swap model names, prompts, settings; remove/add a few nodes) over rebuilding.",
      {"source": {"type": "string"}, "ops": {"type": "array", "items": {"type": "object"}, "description": EDIT_OPS_DOC}},
      ["source", "ops"], category="workflow")
def edit_workflow(source: str, ops: list):
    wf, where = load_any(source)
    if isinstance(ops, str):
        try:
            ops = json.loads(ops)
        except ValueError:
            raise ToolError("ops must be a JSON list of operation objects")
    if isinstance(ops, dict):
        ops = [ops]
    oi, src = get_object_info()
    try:
        new, log = wfcore.apply_ops(wf, ops, oi)
    except wfcore.EditError as e:
        raise ToolError(f"{e}. Nothing was changed; fix this op and send the whole list again.")
    did = _new_draft(new, where, log)
    v = wfcore.validate(new, oi, src)
    return {"draft_id": did, "based_on": where, "changes": log,
            "validation": {k: v[k] for k in ("ok", "verdict", "errors", "warnings", "issues", "missing_models")},
            "next": "Fix any errors with another edit_workflow on this draft id, then write_workflow(draft_id, filename)."}


@tool("list_templates",
      "Ready-made, validated starter workflows (built only from core/common nodes) to copy and edit instead of inventing JSON.",
      {}, [], category="workflow")
def list_templates():
    out = []
    for t in sorted(TEMPLATES_DIR.glob("*.json")):
        wf = json.loads(t.read_text(encoding="utf-8"))
        desc = (wf.get("extra") or {}).get("comfy_expert", {})
        out.append({"name": t.stem, "title": desc.get("title"), "use_for": desc.get("use_for"),
                    "needs": desc.get("needs"), "edit_hints": desc.get("edit_hints")})
    return {"templates": out, "how": "summarize_workflow('<name>') to see node ids, then edit_workflow('<name>', ops) to customise."}


@tool("list_official_templates",
      "Search the OFFICIAL ComfyUI workflow templates that ship with the user's ComfyUI (the same as the "
      "Templates menu). They are verified, current, and include model download links. Load one with "
      "summarize_workflow('official:<name>') or edit_workflow('official:<name>', ops).",
      {"match": {"type": "string", "default": "", "description": "words to match in name/title/description/models, e.g. 'qwen edit', 'wan 2.2 i2v', 'flux'"},
       "include_api_nodes": {"type": "boolean", "default": False, "description": "include paid cloud-API templates"},
       "limit": {"type": "integer", "default": 25}}, [], category="workflow")
def list_official_templates(match: str = "", include_api_nodes: bool = False, limit: int = 25):
    d = official_templates_dir()
    if not d:
        return {"ok": False, "error": "Official templates package not found next to ComfyUI (python_embeded/Lib/site-packages/"
                                      "comfyui_workflow_templates_json). Update ComfyUI or set comfyui.official_templates_dir."}
    idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
    words = [w for w in re.split(r"[\s,]+", match.lower()) if w]
    rows = []
    for cat in idx:
        for t in cat.get("templates") or []:
            api = not t.get("openSource", True) or str(t.get("name", "")).startswith("api_")
            if api and not include_api_nodes:
                continue
            hay = " ".join([t.get("name", ""), t.get("title", ""), t.get("description", ""), " ".join(t.get("models") or []),
                            " ".join(t.get("tags") or []), cat.get("title", "")]).lower().replace("-", " ").replace("_", " ")
            if words and not all(w.replace("-", " ").replace("_", " ") in hay for w in words):
                continue
            if not (d / f"{t.get('name')}.json").is_file():
                continue
            rows.append({"name": f"official:{t['name']}", "title": t.get("title"), "category": cat.get("title"),
                         "description": (t.get("description") or "")[:220], "models": t.get("models"),
                         "total_model_size": human_size(t["size"]) if t.get("size") else None,
                         "tutorial": t.get("tutorialUrl"), "date": t.get("date")})
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return {"folder": str(d), "count": len(rows), "templates": rows[:limit],
            "tip": "Official templates often use subgraphs; summarize_workflow shows the nodes inside them."}


@tool("show_draft", "Show a draft's change log, origin and summary.", {"draft_id": {"type": "string"}}, ["draft_id"], category="workflow")
def show_draft(draft_id: str):
    wf, where = load_any(draft_id)
    d = DRAFTS.get(draft_id, {})
    return {"draft_id": draft_id, "origin": d.get("origin"), "changes": d.get("log"), "summary": wfcore.summarize(wf)}


def _safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip()).strip(". ")
    if not name:
        name = "workflow"
    if not name.lower().endswith(".json"):
        name += ".json"
    return name[:120]


@tool("write_workflow",
      "Save a draft as a NEW workflow file in the 'generated' subfolder of the user's workflow folder (never overwrites, never "
      "touches existing files). Validates first. format 'ui' (open in ComfyUI) or 'api' (for scripts).",
      {"draft_id": {"type": "string"}, "filename": {"type": "string"},
       "format": {"type": "string", "enum": ["ui", "api"], "default": "ui"},
       "allow_missing_models": {"type": "boolean", "default": True,
                                "description": "Save even if some model files still need downloading"}},
      ["draft_id", "filename"], gated=True, category="workflow")
def write_workflow(draft_id: str, filename: str, format: str = "ui", allow_missing_models: bool = True, confirm: bool = False):
    wf, where = load_any(draft_id)
    oi, src = get_object_info()
    v = wfcore.validate(wf, oi, src)
    if v["errors"]:
        raise ToolError(f"Not saved: validation found {v['errors']} error(s). Fix them first: "
                        + json.dumps([i for i in v['issues'] if i['level'] == 'error'][:10]))
    if v["missing_models"] and not allow_missing_models:
        raise ToolError("Not saved: models missing - " + ", ".join(m["file"] for m in v["missing_models"]))
    out_dir = load_config().generated_dir()
    target = out_dir / _safe_name(filename)
    if target.exists():
        stem, i = target.stem, 2
        while (out_dir / f"{stem}_{i}.json").exists():
            i += 1
        target = out_dir / f"{stem}_{i}.json"
    data = wfcore.ui_to_api(wf, oi) if format == "api" else wf
    preview = {"would_write": str(target), "format": format, "nodes": len(data.get("nodes", data)),
               "missing_models": [m["file"] for m in v["missing_models"]], "warnings": v["warnings"]}
    if not confirm:
        return {"dry_run": True, **preview, "message": "Ask the user to approve, then call again with confirm=true."}
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(target, "x", encoding="utf-8") as fh:  # 'x' = fail if exists -> never overwrite
        json.dump(data, fh, indent=2)
    return {"written": str(target), **preview,
            "how_to_open": "In ComfyUI: Workflow menu > Open, or drag the file onto the ComfyUI window."}


@tool("comfy_queue_test",
      "Send a workflow (draft/file) to the RUNNING ComfyUI to generate once (converted to API format). Waits up to wait_seconds "
      "and reports success, errors or output files. Uses GPU time.",
      {"source": {"type": "string"}, "wait_seconds": {"type": "integer", "default": 120}},
      ["source"], gated=True, category="workflow")
def comfy_queue_test(source: str, wait_seconds: int = 120, confirm: bool = False):
    wf, where = load_any(source)
    oi, src = get_object_info()
    if not comfy_alive():
        raise ToolError(f"ComfyUI is not running at {comfy_url()}")
    try:
        api = wfcore.ui_to_api(wf, oi)
    except ValueError as e:
        raise ToolError(str(e))
    if not confirm:
        return {"dry_run": True, "would_queue": where, "nodes": len(api), "comfy": comfy_url(),
                "message": "Ask the user to approve, then call again with confirm=true."}
    from . import TURN
    turn = TURN.get()
    if turn is not None and turn.stop.is_set():
        return {"queued": False, "status": "stopped by the user"}
    cid = uuid.uuid4().hex
    url = comfy_url()
    r = session().post(url + "/prompt", json={"prompt": api, "client_id": cid}, timeout=60)
    try:
        d = r.json()
    except ValueError:
        d = {"raw": r.text[:500]}
    if not isinstance(d, dict):
        d = {"raw": str(d)[:500]}
    if r.status_code != 200:
        return {"ok": False, "queued": False, "status": r.status_code, "comfy_error": d.get("error"),
                "node_errors": d.get("node_errors")}
    pid = d.get("prompt_id")
    if not isinstance(pid, str) or not pid:
        return {"ok": False, "queued": False, "status": r.status_code, "error": "ComfyUI did not return a prompt_id",
                "reply": str(d)[:300]}
    if turn is not None:              # remember it so the Stop button can cancel it
        turn.comfy_url = url
        turn.comfy_prompts.append(pid)
        if turn.stop.is_set():        # Stop was pressed while the job was being sent: cancel it now
            return {"queued": True, "prompt_id": pid, "status": "stopped by the user", "comfy": cancel_prompts(url, [pid])}
    t0 = time.time()
    while time.time() - t0 < max(5, min(int(wait_seconds or 120), 1800)):
        if turn is not None and turn.stop.wait(2):
            return {"queued": True, "prompt_id": pid, "status": "stopped by the user", "comfy": cancel_prompts(url, [pid])}
        if turn is None:
            time.sleep(2)
        try:
            h = session().get(f"{url}/history/{pid}", timeout=20).json()
        except (requests.RequestException, ValueError):
            continue                  # ComfyUI busy or restarting: try again until wait_seconds
        item = h.get(pid) if isinstance(h, dict) else None
        if isinstance(item, dict):
            st = item.get("status") if isinstance(item.get("status"), dict) else {}
            outs = item.get("outputs") if isinstance(item.get("outputs"), dict) else {}
            files = [f"{img.get('subfolder', '')}/{img.get('filename')}".lstrip("/")
                     for o in outs.values() if isinstance(o, dict)
                     for img in (o.get("images") if isinstance(o.get("images"), list) else [])
                     + (o.get("gifs") if isinstance(o.get("gifs"), list) else []) if isinstance(img, dict)]
            msgs = [m for m in (st.get("messages") if isinstance(st.get("messages"), list) else [])
                    if isinstance(m, (list, tuple)) and len(m) > 1 and m[0] in ("execution_error", "execution_interrupted")]
            return {"queued": True, "prompt_id": pid, "status": st.get("status_str"), "completed": st.get("completed"),
                    "outputs": files, "errors": [m[1] for m in msgs][:3]}
    return {"queued": True, "prompt_id": pid, "status": "still running", "note": "Check the ComfyUI window."}
