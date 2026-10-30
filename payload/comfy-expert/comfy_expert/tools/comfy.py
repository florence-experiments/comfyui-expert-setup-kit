"""ComfyUI knowledge from the real install: live /object_info, custom_nodes scan, local model files."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import tool, ToolError
from .net import session, human_size
from ..config import load_config, PKG_DIR

BUNDLED = PKG_DIR / "data" / "object_info_bundled.json"
MODEL_EXT = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft", ".pkl", ".yaml")

# folder aliases ComfyUI treats as the same model type (folder_paths.py)
FOLDER_ALIASES = {
    "text_encoders": ["text_encoders", "clip"], "clip": ["text_encoders", "clip"],
    "diffusion_models": ["diffusion_models", "unet"], "unet": ["diffusion_models", "unet"],
    "upscale_models": ["upscale_models", "latent_upscale_models"],
    "embeddings": ["embeddings"], "ultralytics": ["ultralytics"],
}

# Frontend-only node types that never appear in /object_info but are fine in UI workflows
FRONTEND_ONLY = {"Reroute", "Note", "MarkdownNote", "PrimitiveNode", "Fast Groups Muter (rgthree)",
                 "Fast Groups Bypasser (rgthree)", "Fast Bypasser (rgthree)", "Fast Muter (rgthree)",
                 "Label (rgthree)", "Bookmark (rgthree)", "Fast Actions Button (rgthree)", "Note Plus (mtb)",
                 "Comment", "workflow/", "GroupNode"}

_OI_CACHE: dict = {"t": 0, "data": None, "source": None}


def comfy_url() -> str:
    return load_config()["comfyui"]["url"].rstrip("/")


def comfy_alive(timeout: float = 3) -> bool:
    try:
        r = session().get(comfy_url() + "/system_stats", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def scan_custom_node_names(custom_nodes_dir: Path) -> dict[str, str]:
    """Best-effort: find node class names registered by each custom node pack (no import)."""
    names: dict[str, str] = {}
    if not custom_nodes_dir.is_dir():
        return names
    pat_map = re.compile(r"NODE_CLASS_MAPPINGS\s*(?:\.update\(|=|\[)", re.S)
    pat_key = re.compile(r"""["']([A-Za-z0-9_ .\-|()\[\]/+]{2,80})["']\s*:\s*[A-Za-z_][\w.]*""")
    pat_item = re.compile(r"""NODE_CLASS_MAPPINGS\[\s*["']([^"']+)["']\s*\]\s*=""")
    pat_v3 = re.compile(r"""node_id\s*=\s*["']([^"']+)["']""")
    for pack in sorted(custom_nodes_dir.iterdir()):
        if pack.name.startswith(".") or pack.name.endswith(".disabled") or pack.name == "__pycache__":
            continue
        files = [pack] if pack.is_file() and pack.suffix == ".py" else list(pack.rglob("*.py"))[:400] if pack.is_dir() else []
        for f in files:
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                src = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "NODE_CLASS_MAPPINGS" in src:
                for m in pat_item.finditer(src):
                    names.setdefault(m.group(1), pack.name)
                for m in pat_map.finditer(src):
                    seg = src[m.end(): m.end() + 20000]
                    end = seg.find("}")
                    for k in pat_key.finditer(seg[: end if end > 0 else 4000]):
                        names.setdefault(k.group(1), pack.name)
            if "node_id" in src and "io.Schema" in src:
                for m in pat_v3.finditer(src):
                    names.setdefault(m.group(1), pack.name)
    return names


def get_object_info(force: bool = False) -> tuple[dict, str]:
    """Returns (object_info, source). source = 'live' | 'bundled+scan'."""
    now = time.time()
    if not force and _OI_CACHE["data"] is not None and now - _OI_CACHE["t"] < 120:
        return _OI_CACHE["data"], _OI_CACHE["source"]
    data, source = None, None
    try:
        r = session().get(comfy_url() + "/object_info", timeout=25)
        if r.status_code == 200:
            data, source = r.json(), "live"
    except Exception:
        pass
    if data is None:
        data = json.loads(BUNDLED.read_text(encoding="utf-8"))
        source = "bundled (ComfyUI 0.34.0 core + Impact Pack/Subpack, IPAdapter_plus, ComfyUI-GGUF)"
        root = load_config().comfy_root
        if root:
            scanned = scan_custom_node_names(root / "custom_nodes")
            for n, pack in scanned.items():
                if n not in data:
                    data[n] = {"input": {}, "output": [], "python_module": f"custom_nodes.{pack}",
                               "category": "(found by file scan - inputs unknown; start ComfyUI for details)",
                               "_scanned": True}
            if scanned:
                source += f" + file scan of {root / 'custom_nodes'}"
    _OI_CACHE.update(t=now, data=data, source=source)
    return data, source


def input_defs(info: dict) -> list[tuple[str, str, list, dict]]:
    """[(section, name, type, opts)] in UI order."""
    out = []
    inp = info.get("input") or {}
    order = info.get("input_order") or {}
    for sec in ("required", "optional"):
        s = inp.get(sec) or {}
        names = order.get(sec) or list(s.keys())
        for n in names:
            if n not in s:
                continue
            v = s[n]
            t = v[0] if isinstance(v, (list, tuple)) and v else v
            o = v[1] if isinstance(v, (list, tuple)) and len(v) > 1 and isinstance(v[1], dict) else {}
            out.append((sec, n, t, o))
    return out


WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"   # V3 combo whose choice adds child widgets named "<combo>.<child>"
AUTOGROW = "COMFY_AUTOGROW_V3"            # V3 growing list of sockets (image0, image1, ...)


def is_widget(t, o: dict) -> bool:
    if o.get("forceInput"):
        return False
    if o.get("socketless") or t == DYNAMIC_COMBO:
        return True
    return isinstance(t, list) or (isinstance(t, str) and t in WIDGET_TYPES)


def combo_options(t, o: dict) -> list | None:
    if isinstance(t, list):
        return t
    if t == "COMBO":
        return o.get("options") or []
    if t == DYNAMIC_COMBO:
        return [x.get("key") for x in (o.get("options") or []) if isinstance(x, dict)]
    return None


def describe_node(name: str, info: dict) -> dict:
    ins, widgets = [], []
    for sec, n, t, o in input_defs(info):
        opts = combo_options(t, o)
        entry = {"name": n, "required": sec == "required"}
        if is_widget(t, o):
            entry["type"] = "COMBO" if opts is not None else t
            if opts is not None:
                entry["options"] = opts[:40] + (["..."] if len(opts) > 40 else [])
                if not opts:
                    entry["options_note"] = "list filled from your model folders at runtime"
            for k in ("default", "min", "max", "step", "multiline"):
                if k in o:
                    entry[k] = o[k]
            widgets.append(entry)
        else:
            entry["type"] = t
            ins.append(entry)
    return {"node_type": name, "display_name": info.get("display_name"), "category": info.get("category"),
            "from": info.get("python_module"), "description": (info.get("description") or "")[:300],
            "link_inputs": ins, "widgets_in_order": widgets,
            "outputs": [{"slot": i, "type": t, "name": (info.get("output_name") or [None] * 99)[i] if i < len(info.get("output_name") or []) else t}
                        for i, t in enumerate(info.get("output") or [])],
            "note": "widgets_values in a UI workflow follow widgets_in_order; an INT 'seed'/'noise_seed' (or control_after_generate) "
                    "is followed by an extra 'randomize'/'fixed' value; LoadImage-style image_upload adds an extra 'image' value."}


@tool("comfy_status", "Check if ComfyUI is running (URL from config) and show versions / GPU / VRAM.", {}, [], category="comfy")
def comfy_status():
    try:
        r = session().get(comfy_url() + "/system_stats", timeout=5)
        if r.status_code == 200:
            d = r.json()
            dev = [{"name": x.get("name"), "vram_total": human_size(x.get("vram_total")), "vram_free": human_size(x.get("vram_free"))}
                   for x in d.get("devices", [])]
            return {"running": True, "url": comfy_url(), "system": d.get("system"), "devices": dev}
    except Exception as e:
        return {"running": False, "url": comfy_url(), "error": str(e)[:200],
                "note": "Start ComfyUI for live node/model info. Bundled node list is used meanwhile."}
    return {"running": False, "url": comfy_url()}


@tool("comfy_list_installed_nodes",
      "List node types that exist in the user's ComfyUI (live from the running ComfyUI, else bundled list + custom_nodes scan). "
      "Filter by text (matches name, display name, category or pack).",
      {"filter": {"type": "string", "default": ""}, "limit": {"type": "integer", "default": 80}}, [], category="comfy")
def comfy_list_installed_nodes(filter: str = "", limit: int = 80):
    data, source = get_object_info()
    f = (filter or "").lower()
    rows = []
    for n, i in data.items():
        hay = f"{n} {i.get('display_name') or ''} {i.get('category') or ''} {i.get('python_module') or ''}".lower()
        if not f or all(w in hay for w in f.split()):
            rows.append({"type": n, "display": i.get("display_name"), "category": i.get("category"), "from": i.get("python_module")})
    packs = sorted({(i.get("python_module") or "").split(".")[1] for i in data.values()
                    if (i.get("python_module") or "").startswith("custom_nodes.")})
    lim = max(1, min(int(limit or 80), 400))
    return {"source": source, "total_node_types": len(data), "matches": len(rows), "nodes": rows[:lim],
            "truncated": len(rows) > lim, "custom_node_packs": packs}


@tool("comfy_node_info",
      "Exact inputs (link inputs + widgets in order, with types/defaults/options) and outputs of a node type. "
      "ALWAYS use this before adding or editing a node. Suggests close names if the type does not exist.",
      {"node_type": {"type": "string"}}, ["node_type"], category="comfy")
def comfy_node_info(node_type: str):
    data, source = get_object_info()
    if node_type in data:
        d = describe_node(node_type, data[node_type])
        d["source"] = source
        if data[node_type].get("_scanned"):
            d["warning"] = "Found only by scanning files; inputs unknown. Start ComfyUI so live /object_info is used."
        return d
    low = node_type.lower().replace(" ", "")
    close = [n for n in data if low in n.lower().replace(" ", "") or n.lower().replace(" ", "") in low][:15]
    if not close:
        import difflib
        close = difflib.get_close_matches(node_type, list(data), n=10, cutoff=0.5)
    return {"ok": False, "error": f"Node type '{node_type}' is NOT installed / does not exist.", "did_you_mean": close,
            "source": source, "tip": "If it comes from a custom node pack, use find_node_pack."}


# ---------------- local models ----------------
_IDX: dict = {"t": 0, "data": None}


def model_index(force: bool = False) -> dict[str, list[dict]]:
    """{folder_type: [{rel, size, root}]} across all model roots."""
    if not force and _IDX["data"] is not None and time.time() - _IDX["t"] < 90:
        return _IDX["data"]
    idx: dict[str, list[dict]] = {}
    for root in load_config().model_roots():
        if not root.is_dir():
            continue
        for sub in root.iterdir():
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            for dp, _dn, fns in os.walk(sub):
                for fn in fns:
                    if not fn.lower().endswith(MODEL_EXT) or fn.lower().endswith(".yaml") and sub.name != "configs":
                        continue
                    p = Path(dp) / fn
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        continue
                    rel = p.relative_to(sub).as_posix()
                    idx.setdefault(sub.name, []).append({"rel": rel, "size": sz, "root": str(root)})
    _IDX.update(t=time.time(), data=idx)
    return idx


def find_local_model(value: str, folder_hint: str | None = None) -> dict | None:
    v = (value or "").replace("\\", "/").strip()
    if not v:
        return None
    base = v.rsplit("/", 1)[-1].lower()
    idx = model_index()
    folders = FOLDER_ALIASES.get(folder_hint or "", [folder_hint] if folder_hint else []) or list(idx)
    best = None
    for pass_folders in (folders, list(idx)):
        for ft in pass_folders:
            for e in idx.get(ft, []):
                if e["rel"].lower() == v.lower():
                    return {"folder": ft, **e, "match": "exact"}
                if best is None and e["rel"].rsplit("/", 1)[-1].lower() == base:
                    best = {"folder": ft, **e, "match": "same filename, different subfolder"}
        if best:
            return best
    return best


@tool("list_local_models",
      "List model files the user already has, by folder type (checkpoints, loras, vae, unet, diffusion_models, text_encoders, "
      "clip, clip_vision, controlnet, upscale_models, ipadapter, ultralytics, sams, embeddings...). Without folder_type: counts per folder.",
      {"folder_type": {"type": "string", "default": ""}, "match": {"type": "string", "default": ""},
       "limit": {"type": "integer", "default": 150}}, [], category="comfy")
def list_local_models(folder_type: str = "", match: str = "", limit: int = 150):
    idx = model_index(force=True)
    roots = [str(r) for r in load_config().model_roots()]
    if not folder_type:
        summary = {k: {"files": len(v), "total": human_size(sum(e["size"] for e in v))} for k, v in sorted(idx.items())}
        res = {"model_roots": roots, "folders": summary}
        if match:
            m = match.lower()
            res["matches"] = [{"folder": k, "file": e["rel"], "size": human_size(e["size"])}
                              for k, v in idx.items() for e in v if m in e["rel"].lower()][: int(limit or 150)]
        return res
    folders = FOLDER_ALIASES.get(folder_type, [folder_type])
    files = []
    for ft in folders:
        for e in idx.get(ft, []):
            if match and match.lower() not in e["rel"].lower():
                continue
            files.append({"folder": ft, "file": e["rel"], "size": human_size(e["size"]), "root": e["root"]})
    files.sort(key=lambda x: x["file"].lower())
    lim = max(1, min(int(limit or 150), 1000))
    return {"model_roots": roots, "folder_type": folder_type, "count": len(files), "files": files[:lim], "truncated": len(files) > lim}
