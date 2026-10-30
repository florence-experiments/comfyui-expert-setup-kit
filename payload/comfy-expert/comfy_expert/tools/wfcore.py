"""Pure workflow logic (no tool decorators): load, normalise, slots, edit, validate, convert.

UI format  = what ComfyUI saves from the menu (nodes[], links[], groups[], widgets_values).
API format = {"<id>": {"class_type", "inputs": {name: value | [node_id, slot]}}} used by POST /prompt.
"""
from __future__ import annotations

import copy
import json
import re
import struct
import zlib
from pathlib import Path

from .comfy import (DYNAMIC_COMBO, AUTOGROW, get_object_info, input_defs, is_widget, combo_options, FRONTEND_ONLY,
                    find_local_model, MODEL_EXT)

MODEL_EXTS = tuple(e for e in MODEL_EXT if e != ".yaml")

# widget name -> models folder (overrides per node type below)
FIELD_FOLDER = {
    "ckpt_name": "checkpoints", "lora_name": "loras", "vae_name": "vae", "unet_name": "diffusion_models",
    "clip_name": "text_encoders", "clip_name1": "text_encoders", "clip_name2": "text_encoders",
    "clip_name3": "text_encoders", "clip_name4": "text_encoders", "control_net_name": "controlnet",
    "ipadapter_file": "ipadapter", "style_model_name": "style_models", "gligen_name": "gligen",
    "upscale_model": "upscale_models", "model_path": "checkpoints", "embedding": "embeddings",
}
NODE_FIELD_FOLDER = {
    ("UpscaleModelLoader", "model_name"): "upscale_models",
    ("CLIPVisionLoader", "clip_name"): "clip_vision",
    ("UltralyticsDetectorProvider", "model_name"): "ultralytics",
    ("SAMLoader", "model_name"): "sams",
    ("UnetLoaderGGUF", "unet_name"): "unet",
    ("UnetLoaderGGUFAdvanced", "unet_name"): "unet",
    ("CLIPLoaderGGUF", "clip_name"): "text_encoders",
    ("DualCLIPLoaderGGUF", "clip_name1"): "text_encoders",
    ("DualCLIPLoaderGGUF", "clip_name2"): "text_encoders",
    ("ImageOnlyCheckpointLoader", "ckpt_name"): "checkpoints",
    ("InstantIDModelLoader", "instantid_file"): "instantid",
    ("PhotoMakerLoader", "photomaker_model_name"): "photomaker",
    ("ModelPatchLoader", "name"): "model_patches",
}


def model_folder_for(node_type: str, widget: str, value: str) -> str | None:
    if (node_type, widget) in NODE_FIELD_FOLDER:
        return NODE_FIELD_FOLDER[(node_type, widget)]
    if widget in FIELD_FOLDER:
        return FIELD_FOLDER[widget]
    v = value.lower()
    if "lora" in node_type.lower() or "lora" in widget.lower():
        return "loras"
    if v.endswith(".gguf"):
        return "unet"
    return None


# ---------------------------------------------------------------- loading

def _png_text_chunks(data: bytes) -> dict[str, str]:
    out = {}
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return out
    i = 8
    while i + 8 <= len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + ln]
        i += 12 + ln
        if typ == b"tEXt" and b"\x00" in body:
            k, v = body.split(b"\x00", 1)
            out[k.decode("latin-1")] = v.decode("utf-8", "replace")
        elif typ == b"iTXt" and b"\x00" in body:
            try:
                k, rest = body.split(b"\x00", 1)
                flag = rest[0]
                _lang, _tk, txt = rest[2:].split(b"\x00", 2)
                txt = zlib.decompress(txt) if flag == 1 else txt
                out[k.decode("latin-1")] = txt.decode("utf-8", "replace")
            except Exception:
                pass
        elif typ == b"IEND":
            break
    return out


def parse_workflow_bytes(raw: bytes, name: str = "") -> dict:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        ch = _png_text_chunks(raw)
        if "workflow" in ch:
            return json.loads(ch["workflow"])
        if "prompt" in ch:
            return json.loads(ch["prompt"])
        raise ValueError("PNG has no ComfyUI workflow metadata (maybe it was stripped by a website).")
    txt = raw.decode("utf-8-sig", "replace")
    return json.loads(txt)


def detect_format(wf: dict) -> str:
    if isinstance(wf, dict) and isinstance(wf.get("nodes"), list):
        return "ui"
    if isinstance(wf, dict) and wf and all(isinstance(v, dict) and "class_type" in v for v in wf.values()):
        return "api"
    if isinstance(wf, dict) and isinstance(wf.get("prompt"), dict):
        return "api-wrapped"
    if isinstance(wf, dict) and isinstance(wf.get("workflow"), dict):
        return "ui-wrapped"
    return "unknown"


def unwrap(wf: dict) -> tuple[str, dict]:
    f = detect_format(wf)
    if f == "api-wrapped":
        return "api", wf["prompt"]
    if f == "ui-wrapped":
        return "ui", wf["workflow"]
    return f, wf


# ---------------------------------------------------------------- UI helpers

def norm_links(wf: dict) -> list[dict]:
    out = []
    for l in wf.get("links") or []:
        if isinstance(l, list) and len(l) >= 5:
            out.append({"id": l[0], "origin_id": l[1], "origin_slot": l[2], "target_id": l[3], "target_slot": l[4],
                        "type": l[5] if len(l) > 5 else "*"})
        elif isinstance(l, dict):
            out.append({"id": l.get("id"), "origin_id": l.get("origin_id"), "origin_slot": l.get("origin_slot"),
                        "target_id": l.get("target_id"), "target_slot": l.get("target_slot"), "type": l.get("type", "*")})
    return out


def subgraphs(wf: dict) -> list[dict]:
    return list(((wf.get("definitions") or {}).get("subgraphs")) or [])


def all_nodes(wf: dict) -> list[tuple[str | None, dict]]:
    """Top-level nodes plus nodes inside subgraph definitions. (subgraph_name|None, node)."""
    res = [(None, n) for n in wf.get("nodes") or []]
    for sg in subgraphs(wf):
        res += [(sg.get("name") or sg.get("id"), n) for n in sg.get("nodes") or []]
    return res


def _child_defs(opt_inputs: dict):
    for sec in ("required", "optional"):
        for n, v in (opt_inputs.get(sec) or {}).items():
            t = v[0] if isinstance(v, (list, tuple)) and v else v
            o = v[1] if isinstance(v, (list, tuple)) and len(v) > 1 and isinstance(v[1], dict) else {}
            yield sec, n, t, o


def _slots_for(defs, slots: list, wv: list | None, prefix: str = ""):
    for _sec, name, t, o in defs:
        if not is_widget(t, o):
            continue
        full = prefix + name
        slots.append(full)
        if (t == "INT" and (o.get("control_after_generate") or name in ("seed", "noise_seed"))):
            slots.append("$control_after_generate")
        if (o.get("image_upload") or o.get("video_upload") or o.get("audio_upload")) and not o.get("widgetType"):
            slots.append("$upload")
        if t == DYNAMIC_COMBO:
            # the chosen option's child widgets follow right after the combo value
            idx = len(slots) - 1
            chosen = wv[idx] if wv is not None and idx < len(wv) else o.get("default")
            opts = [x for x in (o.get("options") or []) if isinstance(x, dict)]
            sel = next((x for x in opts if x.get("key") == chosen), opts[0] if (opts and chosen is None) else None)
            if sel:
                _slots_for(list(_child_defs(sel.get("inputs") or {})), slots, wv, full + ".")


def _required_widget_slots(info: dict) -> list[str]:
    slots: list[str] = []
    _slots_for([d for d in input_defs(info) if d[0] == "required"], slots, None)
    socketless = {name for _s, name, _t, o in input_defs(info) if o.get("socketless") or o.get("hidden")}
    return [x for x in slots if "." not in x and not x.startswith("$") and x not in socketless]


def widget_slots(node_type: str, oi: dict, wv: list | None = None) -> list[str] | None:
    """Names for each widgets_values position (with pseudo slots), or None if unknown node.
    Pass the node's widgets_values so V3 dynamic combos expand to the chosen option's child widgets."""
    info = oi.get(node_type)
    if not info or info.get("_scanned"):
        return None
    slots: list[str] = []
    _slots_for(input_defs(info), slots, wv)
    return slots


def named_widgets(node: dict, oi: dict) -> dict:
    wv = node.get("widgets_values")
    if isinstance(wv, dict):
        return dict(wv)
    wv = wv or []
    slots = widget_slots(node.get("type", ""), oi, wv)
    if slots is None:
        return {f"widget_{i}": v for i, v in enumerate(wv)}
    out = {}
    for i, v in enumerate(wv):
        name = slots[i] if i < len(slots) else f"extra_{i}"
        if not name.startswith("$"):
            out[name] = v
    return out


def iter_model_refs(node_type: str, widgets: dict):
    for k, v in widgets.items():
        vals = []
        if isinstance(v, str):
            vals = [(k, v)]
        elif isinstance(v, dict):  # e.g. rgthree Power Lora Loader rows
            for kk, vv in v.items():
                if isinstance(vv, str):
                    vals.append((k if kk in ("lora", "name") else f"{k}.{kk}", vv))
        for name, s in vals:
            if s.lower().endswith(MODEL_EXTS):
                folder = model_folder_for(node_type, name.split(".")[0], s) or ("loras" if "lora" in name.lower() else None)
                yield name, s, folder


# ---------------------------------------------------------------- summarise

ANIME_HINTS = ("illustrious", "noob", "pony", "anime", "animagine", "anything", "counterfeit", "waifu", "hassaku",
               "nova", "wai", "meina", "toon", "cartoon", "hentai", "booru", "manga")
ANIME_TAGS = ("1girl", "1boy", "masterpiece", "best quality", "score_9", "score_8_up", "absurdres", "highres",
              "solo", "anime", "looking at viewer")


def guess_family(types: set[str], models: list[str], prompts: list[str], clip_types: list[str]) -> list[str]:
    t = " ".join(models).lower()
    p = " ".join(prompts).lower()
    fam = []
    ct = " ".join(clip_types).lower()
    if "qwen_image" in ct or "qwen-image" in t or "qwen_image" in t:
        fam.append("Qwen-Image" + (" Edit" if "edit" in t or any("QwenImageEdit" in x for x in types) else ""))
    if "wan" in ct or "wan2" in t or "wan_" in t or any(x.startswith("Wan") for x in types):
        fam.append("Wan video")
    if "flux2" in t or "flux_2" in t or "EmptyFlux2LatentImage" in types:
        fam.append("Flux.2")
    elif "kontext" in t:
        fam.append("Flux Kontext (edit)")
    elif "flux" in t or "FluxGuidance" in types or ("DualCLIPLoader" in types and "flux" in ct):
        fam.append("Flux.1")
    if "chroma" in t:
        fam.append("Chroma (Flux-based)")
    if "z_image" in t or "z-image" in t:
        fam.append("Z-Image")
    if "hidream" in t:
        fam.append("HiDream")
    if "sd3" in t or "sd3.5" in t:
        fam.append("SD3/3.5")
    if "pony" in t or "score_9" in p:
        fam.append("Pony (SDXL-based)")
    if "illustrious" in t or "noob" in t or "ilxl" in t:
        fam.append("Illustrious/NoobAI (SDXL-based)")
    t_noenc = t.replace("t5xxl", "").replace("umt5_xxl", "").replace("umt5-xxl", "")
    if not fam and "xl" in t_noenc:
        fam.append("SDXL")
    if not fam and ("sd15" in t or "v1-5" in t or "1.5" in t):
        fam.append("SD 1.5")
    if not fam and "CheckpointLoaderSimple" in types:
        fam.append("SD-style checkpoint (check the model page: SD1.5/SDXL/Pony/Illustrious)")
    return fam


def summarize(wf: dict, oi: dict | None = None) -> dict:
    fmt, wf = unwrap(wf)
    if oi is None:
        oi, _ = get_object_info()
    nodes_out, models, prompts, samplers, sizes, loras, clip_types = [], [], [], [], [], [], []
    embedded_links: list[dict] = []
    types: set[str] = set()
    if fmt == "api":
        items = [(None, {"id": k, "type": v.get("class_type"), "title": (v.get("_meta") or {}).get("title"),
                         "_api_inputs": v.get("inputs", {})}) for k, v in wf.items()]
    elif fmt == "ui":
        items = all_nodes(wf)
    else:
        raise ValueError("Not a ComfyUI workflow (neither UI nor API format).")
    sg_names = {sg.get("id"): sg.get("name") for sg in subgraphs(wf)} if fmt == "ui" else {}
    for sg, n in items:
        ntype = n.get("type") or "?"
        if ntype in sg_names:  # subgraph instance: its inner nodes are listed separately
            nodes_out.append({"id": n.get("id"), "type": f"subgraph '{sg_names[ntype]}'",
                              **({"in_subgraph": sg} if sg else {})})
            continue
        types.add(ntype)
        if fmt == "api":
            w = {k: v for k, v in n["_api_inputs"].items() if not isinstance(v, list)}
        else:
            w = named_widgets(n, oi)
        mode = {0: "active", 2: "MUTED", 4: "BYPASSED"}.get(n.get("mode", 0), str(n.get("mode")))
        short = {k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v) for k, v in w.items()
                 if not (isinstance(v, str) and len(v) > 200)}
        entry = {"id": n.get("id"), "type": ntype}
        if n.get("title") and n.get("title") != ntype:
            entry["title"] = n["title"]
        if mode != "active":
            entry["mode"] = mode
        if sg:
            entry["in_subgraph"] = sg
        if ntype not in oi and ntype not in FRONTEND_ONLY and not any(ntype == s.get("id") for s in subgraphs(wf) if fmt == "ui"):
            entry["NOT_INSTALLED"] = True
        if short and ntype not in ("Note", "MarkdownNote"):
            entry["settings"] = short
        nodes_out.append(entry)
        for m in ((n.get("properties") or {}).get("models") or []) if fmt == "ui" else []:
            if isinstance(m, dict) and m.get("url"):
                embedded_links.append({"file": m.get("name"), "url": m.get("url"), "folder": m.get("directory"),
                                       "node": n.get("id")})
        for name, val, folder in iter_model_refs(ntype, w):
            loc = find_local_model(val, folder)
            rec = {"node": n.get("id"), "node_type": ntype, "field": name, "file": val, "folder": folder,
                   "found_locally": bool(loc)}
            (loras if folder == "loras" else models).append(rec)
            if folder == "loras":
                rec["strength"] = {k: w[k] for k in ("strength_model", "strength_clip", "strength") if k in w}
        for k, v in w.items():
            if isinstance(v, str) and (k in ("text", "prompt", "positive", "negative", "text_g", "text_l", "wildcard_text", "populated_text")
                                       or (len(v) > 30 and " " in v and ntype not in ("Note", "MarkdownNote"))):
                if not v.lower().endswith(MODEL_EXTS):
                    prompts.append({"node": n.get("id"), "node_type": ntype, "title": n.get("title"), "field": k, "text": v[:1500]})
        if "steps" in w and ("cfg" in w or "sampler_name" in w):
            samplers.append({"node": n.get("id"), "node_type": ntype, **{k: w[k] for k in ("seed", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "denoise", "start_at_step", "end_at_step", "guidance") if k in w}})
        if "width" in w and "height" in w:
            sizes.append({"node": n.get("id"), "node_type": ntype, "width": w["width"], "height": w["height"], "batch": w.get("batch_size")})
        if "type" in w and "clip" in ntype.lower():
            clip_types.append(str(w["type"]))
        if "guidance" in w and ntype == "FluxGuidance":
            samplers.append({"node": n.get("id"), "node_type": ntype, "guidance": w["guidance"]})
    groups = []
    if fmt == "ui":
        for g in wf.get("groups") or []:
            b = g.get("bounding") or [0, 0, 0, 0]
            inside = [n.get("id") for n in wf.get("nodes") or []
                      if b[0] <= (n.get("pos") or [0, 0])[0] <= b[0] + b[2] and b[1] <= (n.get("pos") or [0, 0])[1] <= b[1] + b[3]]
            groups.append({"title": g.get("title"), "nodes": inside})
    prompt_text = [p["text"] for p in prompts]
    positive_text = [p["text"] for p in prompts if "neg" not in f"{p.get('title') or ''} {p['field']}".lower()]
    style_hits = sorted({h for h in ANIME_HINTS if any(h in m["file"].lower() for m in models + loras)} |
                        {t for t in ANIME_TAGS if any(t in p.lower() for p in positive_text)})
    res = {
        "format": fmt, "node_count": len(items), "group_count": len(groups),
        "model_family_guess": guess_family(types, [m["file"] for m in models + loras], prompt_text, clip_types),
        "models": models, "loras": loras, "prompts": prompts, "sampler_settings": samplers, "image_sizes": sizes,
        "groups": groups, "pipeline_order": pipeline_order(wf, fmt),
        "anime_style_signals": style_hits,
        "embedded_model_links": embedded_links,
        "custom_or_missing_types": sorted(t for t in types if t not in oi and t not in FRONTEND_ONLY
                                          and t not in {sg.get("id") for sg in (subgraphs(wf) if fmt == "ui" else [])}),
        "nodes": nodes_out,
    }
    if fmt == "ui" and subgraphs(wf):
        res["subgraphs"] = [{"id": s.get("id"), "name": s.get("name"), "nodes": len(s.get("nodes") or [])} for s in subgraphs(wf)]
    return res


def pipeline_order(wf: dict, fmt: str) -> list[str]:
    """Topological order 'id:type' of top-level nodes (helps explain the flow)."""
    edges: dict = {}
    names: dict = {}
    if fmt == "ui":
        sgname = {sg.get("id"): sg.get("name") for sg in subgraphs(wf)}
        for n in wf.get("nodes") or []:
            if n.get("type") in FRONTEND_ONLY and n.get("type") not in ("Reroute", "PrimitiveNode"):
                continue
            t = n.get("type")
            label = f"subgraph '{sgname[t]}'" if t in sgname else t
            names[n.get("id")] = f"{n.get('id')}:{label}" + (f" ({n['title']})" if n.get("title") and n.get("title") != t else "")
            edges.setdefault(n.get("id"), set())
        for l in norm_links(wf):
            edges.setdefault(l["target_id"], set()).add(l["origin_id"])
    else:
        for k, v in wf.items():
            names[k] = f"{k}:{(v.get('_meta') or {}).get('title') or v.get('class_type')}"
            edges.setdefault(k, set())
            for val in (v.get("inputs") or {}).values():
                if isinstance(val, list) and len(val) == 2 and str(val[0]) in wf:
                    edges[k].add(str(val[0]))
    order, seen, temp = [], set(), set()

    def visit(n):
        if n in seen or n in temp:
            return
        temp.add(n)
        for d in sorted(edges.get(n, ()), key=str):
            visit(d)
        temp.discard(n)
        seen.add(n)
        if n in names:
            order.append(names[n])
    for n in sorted(edges, key=lambda x: (str(type(x)), x)):
        visit(n)
    skip = ("Note", "MarkdownNote")
    return [o for o in order if not o.endswith(skip)][:200]


# ---------------------------------------------------------------- validation

def types_compatible(a: str, b: str) -> bool:
    if not a or not b or a == "*" or b == "*":
        return True
    sa, sb = set(str(a).split(",")), set(str(b).split(","))
    return bool(sa & sb)


def validate(wf: dict, oi: dict | None = None, oi_source: str = "") -> dict:
    fmt, wf = unwrap(wf)
    if oi is None:
        oi, oi_source = get_object_info()
    live = oi_source == "live"
    issues: list[dict] = []
    missing_models: list[dict] = []
    found_models: list[dict] = []

    def add(level, msg, node=None, **kw):
        d = {"level": level, "message": msg}
        if node is not None:
            d["node"] = node
        d.update(kw)
        issues.append(d)

    if fmt == "api":
        has_output = False
        for nid, v in wf.items():
            ct = v.get("class_type")
            info = oi.get(ct)
            if not info:
                add("error", f"Node type '{ct}' is not installed", nid, node_type=ct)
                continue
            if info.get("output_node"):
                has_output = True
            ins = v.get("inputs") or {}
            for sec, name, t, o in input_defs(info):
                val = ins.get(name)
                if val is None:
                    if sec == "required":
                        add("error", f"Required input '{name}' missing", nid, node_type=ct)
                    continue
                if isinstance(val, list) and len(val) == 2 and not isinstance(t, list):
                    src = wf.get(str(val[0]))
                    if src is None:
                        add("error", f"Input '{name}' links to missing node {val[0]}", nid)
                    else:
                        si = oi.get(src.get("class_type")) or {}
                        outs = si.get("output") or []
                        if outs and (not isinstance(val[1], int) or val[1] >= len(outs)):
                            add("error", f"Input '{name}' uses output slot {val[1]} that node {val[0]} does not have", nid)
                        elif outs and not types_compatible(outs[val[1]], t if isinstance(t, str) else "COMBO"):
                            add("error", f"Type mismatch on '{name}': {outs[val[1]]} -> {t}", nid)
                _check_value(ct, name, t, o, val, nid, add, live, missing_models, found_models)
        if not has_output:
            add("warn", "No output node (SaveImage/PreviewImage/...) - nothing would run")
        return _result(fmt, issues, missing_models, found_models, oi_source)

    if fmt != "ui":
        return {"ok": False, "format": fmt, "issues": [{"level": "error", "message": "Not a ComfyUI workflow"}]}

    sg_ids = {s.get("id") for s in subgraphs(wf)}
    scopes = [("main", wf.get("nodes") or [], norm_links(wf))] + \
             [(f"subgraph '{s.get('name')}'", s.get("nodes") or [], norm_links(s)) for s in subgraphs(wf)]
    has_output = False
    for scope, nodes, links in scopes:
        by_id = {n.get("id"): n for n in nodes}
        if len(by_id) != len(nodes):
            add("error", f"Duplicate node ids in {scope}")
        link_by_id = {l["id"]: l for l in links}
        sg_io_ids = {-10, -20}  # subgraph input/output pseudo nodes
        for l in links:
            for end in ("origin_id", "target_id"):
                if l[end] not in by_id and l[end] not in sg_io_ids:
                    add("error", f"Link {l['id']} points to node {l[end]} which does not exist ({scope})")
            o = by_id.get(l["origin_id"])
            if o is not None and l["origin_slot"] is not None and l["origin_slot"] >= len(o.get("outputs") or []):
                add("error", f"Link {l['id']} uses output slot {l['origin_slot']} that node {o.get('id')} lacks", o.get("id"))
        for n in nodes:
            ntype = n.get("type")
            nid = n.get("id")
            if ntype in FRONTEND_ONLY or ntype in sg_ids:
                continue
            info = oi.get(ntype)
            if info is None:
                add("error", f"Node type '{ntype}' is not installed (red node). Use find_node_pack to find the pack.",
                    nid, node_type=ntype, scope=scope)
                continue
            if info.get("output_node") and n.get("mode", 0) == 0:
                has_output = True
            for idx, inp in enumerate(n.get("inputs") or []):
                lid = inp.get("link")
                if lid is None:
                    continue
                l = link_by_id.get(lid)
                if l is None:
                    add("error", f"Input '{inp.get('name')}' refers to link {lid} that does not exist", nid)
                    continue
                if l["target_id"] != nid:
                    add("error", f"Link {lid} target mismatch (says node {l['target_id']})", nid)
                if not types_compatible(l.get("type"), inp.get("type")):
                    add("error", f"Type mismatch on input '{inp.get('name')}': link carries {l.get('type')}, input wants {inp.get('type')}", nid)
            for oidx, out in enumerate(n.get("outputs") or []):
                for lid in out.get("links") or []:
                    if lid not in link_by_id:
                        add("warn", f"Output '{out.get('name')}' lists link {lid} that does not exist", nid)
            if info.get("_scanned"):
                continue
            if n.get("mode", 0) == 0:
                linked = {i.get("name") for i in n.get("inputs") or [] if i.get("link") is not None}
                for sec, name, t, o in input_defs(info):
                    if sec != "required" or is_widget(t, o) or name in linked:
                        continue
                    if t == AUTOGROW or any(str(x).startswith(name + ".") or str(x).startswith(name) for x in linked):
                        continue  # V3 growing socket list (images.image0 ...)
                    add("error", f"Required input '{name}' ({t}) is not connected", nid, node_type=ntype)
            wv = n.get("widgets_values")
            slots = widget_slots(ntype, oi, wv if isinstance(wv, list) else None)
            if slots is not None and isinstance(wv, list):
                n_required = len(_required_widget_slots(info))
                if len(wv) < n_required:
                    add("warn", f"widgets_values has {len(wv)} values but this node version needs at least {n_required} "
                                f"({', '.join(s for s in slots if not s.startswith('$'))}). The node pack version probably differs "
                                f"- open the workflow in ComfyUI and re-save, or check the values.", nid, node_type=ntype)
                elif len(wv) > len(slots) and slots:
                    add("info", f"widgets_values has {len(wv)} values, this node version defines {len(slots)} widgets "
                                f"(extra values are usually harmless frontend state or an older/newer pack version).", nid, node_type=ntype)
            w = named_widgets(n, oi)
            defs = {name: (t, o) for _s, name, t, o in input_defs(info)}
            for name, val in w.items():
                if name in defs:
                    _check_value(ntype, name, defs[name][0], defs[name][1], val, nid, add, live, missing_models, found_models)
            for name, val, folder in iter_model_refs(ntype, {k: v for k, v in w.items() if k not in defs}):
                _model_check(ntype, name, val, folder, nid, missing_models, found_models)
    if not has_output:
        add("warn", "No active output node (SaveImage / PreviewImage / VHS_VideoCombine ...)")
    return _result(fmt, issues, missing_models, found_models, oi_source)


def _model_check(ntype, name, val, folder, nid, missing_models, found_models, live_opts=None):
    loc = find_local_model(val, folder)
    rec = {"node": nid, "node_type": ntype, "field": name, "file": val, "folder": folder}
    if live_opts:
        norm = lambda x: str(x).replace("\\", "/").lower()
        if norm(val) in {norm(x) for x in live_opts}:
            rec["found_in"] = "listed by running ComfyUI"
            found_models.append(rec)
            return
        same = [x for x in live_opts if norm(x).rsplit("/", 1)[-1] == norm(val).rsplit("/", 1)[-1]]
        if same:
            rec["note"] = f"ComfyUI lists it as '{same[0]}' - set the widget to exactly that value"
            found_models.append(rec)
            return
        if loc:
            rec["note"] = ("file is on disk but the running ComfyUI does not list it - refresh ComfyUI (press R) "
                           "or restart it; check the folder / extra_model_paths.yaml")
            rec["found_in"] = f"{loc['root']}/{loc['folder']}/{loc['rel']}"
        missing_models.append(rec)
        return
    if loc:
        rec["found_in"] = f"{loc['root']}/{loc['folder']}/{loc['rel']}"
        if loc.get("match") != "exact":
            rec["note"] = f"found as '{loc['rel']}' - set the widget to exactly that value"
        found_models.append(rec)
    else:
        missing_models.append(rec)


def _check_value(ntype, name, t, o, val, nid, add, live, missing_models, found_models):
    if isinstance(val, list):
        return
    opts = combo_options(t, o)
    if isinstance(val, str) and val.lower().endswith(MODEL_EXTS):
        _model_check(ntype, name, val, model_folder_for(ntype, name, val), nid, missing_models, found_models,
                     opts if live else None)
        return
    if opts and isinstance(val, (str, int, float)) and val not in opts and str(val) not in [str(x) for x in opts]:
        if o.get("image_upload") or o.get("video_upload") or o.get("audio_upload"):
            add("warn", f"Input file '{val}' for '{name}' is not in ComfyUI's input folder - pick or upload your own file "
                        f"in the node before running.", nid, node_type=ntype)
        elif len(opts) < 60 or live:
            add("error" if live else "warn", f"'{name}' = {val!r} is not a valid option. Valid: {opts[:25]}", nid, node_type=ntype)
    if t in ("INT", "FLOAT") and isinstance(val, (int, float)) and not isinstance(val, bool):
        mn, mx = o.get("min"), o.get("max")
        if (mn is not None and val < mn) or (mx is not None and val > mx):
            add("warn", f"'{name}' = {val} outside allowed range {mn}..{mx}", nid, node_type=ntype)


def _result(fmt, issues, missing_models, found_models, oi_source):
    errors = [i for i in issues if i["level"] == "error"]
    return {"ok": not errors and not missing_models, "format": fmt, "node_types_from": oi_source,
            "errors": len(errors), "warnings": len([i for i in issues if i["level"] == "warn"]),
            "missing_models_count": len(missing_models), "issues": issues[:80],
            "missing_models": missing_models, "models_found_locally": found_models,
            "verdict": ("VALID - all nodes installed, links ok, all models present" if not errors and not missing_models else
                        "Structure OK but some model files are missing (download them or change the widget)" if not errors else
                        "INVALID - fix the errors listed")}


# ---------------------------------------------------------------- editing (UI format)

class EditError(Exception):
    pass


def _max_ids(wf):
    nid = max([n.get("id", 0) for n in wf.get("nodes") or [] if isinstance(n.get("id"), int)] + [wf.get("last_node_id") or 0])
    lid = max([l["id"] for l in norm_links(wf) if isinstance(l["id"], int)] + [wf.get("last_link_id") or 0])
    return nid, lid


def _links_are_lists(wf) -> bool:
    ls = wf.get("links") or []
    return not ls or isinstance(ls[0], list)


_TEXT_ALIASES = {"value", "prompt", "text", "positive", "negative", "positiveprompt", "negativeprompt", "string"}


def _norm_label(x) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def _node(wf, nid):
    nodes = wf.get("nodes") or []
    for n in nodes:
        if str(n.get("id")) == str(nid):
            return n
    # Small models often pass a title or a type instead of the numeric id. Accept it only when unambiguous.
    q = _norm_label(nid)
    if q and not q.isdigit():
        for cands in ([n for n in nodes if n.get("title") and _norm_label(n["title"]) == q],
                      [n for n in nodes if _norm_label(n.get("type", "")) == q],
                      [n for n in nodes if n.get("title") and len(_norm_label(n["title"])) >= 4
                       and (_norm_label(n["title"]) in q or q in _norm_label(n["title"]))]):
            if len(cands) == 1:
                return cands[0]
    listing = "; ".join(f"{n.get('id')}={n.get('type')}" + (f" '{n['title']}'" if n.get("title") else "") for n in nodes[:60])
    raise EditError(f"No node with id {nid}. Use the numeric id. Nodes: {listing}")


def _remove_link(wf, lid):
    keep = []
    for l in wf.get("links") or []:
        i = l[0] if isinstance(l, list) else l.get("id")
        if i == lid:
            o_id = l[1] if isinstance(l, list) else l.get("origin_id")
            t_id = l[3] if isinstance(l, list) else l.get("target_id")
            for n in wf.get("nodes") or []:
                if n.get("id") == o_id:
                    for out in n.get("outputs") or []:
                        if out.get("links") and lid in out["links"]:
                            out["links"].remove(lid)
                if n.get("id") == t_id:
                    for inp in n.get("inputs") or []:
                        if inp.get("link") == lid:
                            inp["link"] = None
            continue
        keep.append(l)
    wf["links"] = keep


def _add_link(wf, from_id, from_slot, to_id, to_name_or_slot):
    src, dst = _node(wf, from_id), _node(wf, to_id)
    outs = src.get("outputs") or []
    if isinstance(from_slot, str):
        names = [o.get("name") for o in outs]
        types = [o.get("type") for o in outs]
        if from_slot in names:
            from_slot = names.index(from_slot)
        elif from_slot in types:
            from_slot = types.index(from_slot)
        elif from_slot.upper() in types:
            from_slot = types.index(from_slot.upper())
        else:
            raise EditError(f"Node {from_id} ({src.get('type')}) has no output '{from_slot}'. Outputs: {names}")
    if not isinstance(from_slot, int) or from_slot >= len(outs):
        raise EditError(f"Node {from_id} has no output slot {from_slot}")
    out_type = outs[from_slot].get("type")
    ins = dst.setdefault("inputs", [])
    idx = None
    if isinstance(to_name_or_slot, int):
        idx = to_name_or_slot if to_name_or_slot < len(ins) else None
    else:
        for i, inp in enumerate(ins):
            if inp.get("name") == to_name_or_slot:
                idx = i
                break
    if idx is None:
        # maybe a widget being converted to an input, or an optional input not yet listed
        oi, _ = get_object_info()
        info = oi.get(dst.get("type")) or {}
        d = {n: (t, o) for _s, n, t, o in input_defs(info)}
        if to_name_or_slot in d:
            t, o = d[to_name_or_slot]
            entry = {"name": to_name_or_slot, "type": t if isinstance(t, str) else "COMBO", "link": None}
            if is_widget(t, o):
                entry["widget"] = {"name": to_name_or_slot}
            ins.append(entry)
            idx = len(ins) - 1
        else:
            raise EditError(f"Node {to_id} ({dst.get('type')}) has no input '{to_name_or_slot}'. Inputs: {[i.get('name') for i in ins]}")
    if not types_compatible(out_type, ins[idx].get("type")):
        raise EditError(f"Type mismatch: output {out_type} cannot go into input '{ins[idx].get('name')}' ({ins[idx].get('type')})")
    if ins[idx].get("link") is not None:
        _remove_link(wf, ins[idx]["link"])
    _nid, lid = _max_ids(wf)
    lid += 1
    if _links_are_lists(wf):
        wf.setdefault("links", []).append([lid, src["id"], from_slot, dst["id"], idx, out_type])
    else:
        wf.setdefault("links", []).append({"id": lid, "origin_id": src["id"], "origin_slot": from_slot,
                                           "target_id": dst["id"], "target_slot": idx, "type": out_type})
    ins[idx]["link"] = lid
    outs[from_slot].setdefault("links", [])
    if outs[from_slot]["links"] is None:
        outs[from_slot]["links"] = []
    outs[from_slot]["links"].append(lid)
    outs[from_slot]["slot_index"] = from_slot
    wf["last_link_id"] = lid
    return lid


def default_widget_values(node_type: str, oi: dict, overrides: dict | None = None) -> list:
    info = oi.get(node_type)
    if not info:
        raise EditError(f"Unknown node type '{node_type}' - check comfy_node_info / comfy_list_installed_nodes")
    overrides = dict(overrides or {})
    vals = []
    for _sec, name, t, o in input_defs(info):
        if not is_widget(t, o):
            continue
        opts = combo_options(t, o)
        if name in overrides:
            v = overrides.pop(name)
        elif "default" in o:
            v = o["default"]
        elif opts is not None:
            v = opts[0] if opts else ""
        elif t == "STRING":
            v = ""
        elif t == "BOOLEAN":
            v = False
        else:
            v = 0
        vals.append(v)
        if t == "INT" and (o.get("control_after_generate") or name in ("seed", "noise_seed")):
            vals.append(overrides.pop("control_after_generate", "fixed"))
        if o.get("image_upload") or o.get("video_upload") or o.get("audio_upload"):
            vals.append("image")
    if overrides:
        raise EditError(f"{node_type} has no widget(s) {list(overrides)}. Widgets: {[s for s in widget_slots(node_type, oi) or [] if not s.startswith('$')]}")
    return vals


def make_node(wf: dict, node_type: str, oi: dict, widgets: dict | None = None, pos=None, title=None) -> dict:
    info = oi.get(node_type)
    if not info or info.get("_scanned"):
        raise EditError(f"Cannot add '{node_type}': not installed or inputs unknown. Check comfy_node_info.")
    nid, _ = _max_ids(wf)
    nid += 1
    inputs = []
    for _sec, name, t, o in input_defs(info):
        if not is_widget(t, o):
            inputs.append({"name": name, "type": t if isinstance(t, str) else "*", "link": None})
    outputs = []
    onames = info.get("output_name") or []
    for i, t in enumerate(info.get("output") or []):
        outputs.append({"name": onames[i] if i < len(onames) else t, "type": t if isinstance(t, str) else "*", "links": [], "slot_index": i})
    n = {"id": nid, "type": node_type, "pos": list(pos or [100, 100]), "size": [320, 130], "flags": {},
         "order": len(wf.get("nodes") or []), "mode": 0, "inputs": inputs, "outputs": outputs,
         "properties": {"Node name for S&R": node_type}, "widgets_values": default_widget_values(node_type, oi, widgets)}
    if title:
        n["title"] = title
    wf.setdefault("nodes", []).append(n)
    wf["last_node_id"] = nid
    return n


def set_widget(node: dict, widget, value, oi: dict):
    wv = node.get("widgets_values")
    if isinstance(wv, dict):
        if widget not in wv:
            raise EditError(f"Node {node.get('id')} has no widget '{widget}'. Widgets: {list(wv)}")
        old = wv[widget]
        wv[widget] = value
        return old
    wv = node.setdefault("widgets_values", [])
    if isinstance(widget, int) or (isinstance(widget, str) and widget.isdigit()):
        idx = int(widget)
    else:
        slots = widget_slots(node.get("type"), oi, wv)
        if slots is None:
            raise EditError(f"Node type {node.get('type')} unknown - use the widget index (0..{len(wv) - 1}) instead of a name. "
                            f"Current values: {wv}")
        real = [s for s in slots if not s.startswith("$")]
        if widget not in slots and real == ["text"] and _norm_label(widget) in _TEXT_ALIASES:
            widget = "text"  # prompt nodes: 'value'/'prompt'/'positive_prompt' all mean the one text widget
        if widget not in slots:
            raise EditError(f"Node {node.get('id')} ({node.get('type')}) has no widget '{widget}'. Widgets: {[s for s in slots if not s.startswith('$')]}")
        idx = slots.index(widget)
    if idx >= len(wv):
        raise EditError(f"Widget index {idx} out of range (node has {len(wv)} values)")
    old = wv[idx]
    wv[idx] = value
    return old


def remove_node(wf: dict, nid, reconnect: bool = True) -> list[str]:
    n = _node(wf, nid)
    notes = []
    in_links = {i.get("type"): next((l for l in norm_links(wf) if l["id"] == i.get("link")), None)
                for i in n.get("inputs") or [] if i.get("link") is not None}
    out_targets = []
    for oi_, out in enumerate(n.get("outputs") or []):
        for lid in list(out.get("links") or []):
            l = next((x for x in norm_links(wf) if x["id"] == lid), None)
            if l:
                tgt = _node(wf, l["target_id"])
                tname = (tgt.get("inputs") or [])[l["target_slot"]].get("name") if l["target_slot"] < len(tgt.get("inputs") or []) else l["target_slot"]
                out_targets.append((out.get("type"), l["target_id"], tname))
    for i in n.get("inputs") or []:
        if i.get("link") is not None:
            _remove_link(wf, i["link"])
    for out in n.get("outputs") or []:
        for lid in list(out.get("links") or []):
            _remove_link(wf, lid)
    wf["nodes"] = [x for x in wf["nodes"] if x is not n]
    if reconnect:
        for typ, tid, tname in out_targets:
            src = in_links.get(typ)
            if src:
                _add_link(wf, src["origin_id"], src["origin_slot"], tid, tname)
                notes.append(f"reconnected {typ}: node {src['origin_id']} -> node {tid}.{tname}")
            else:
                notes.append(f"node {tid}.{tname} ({typ}) is now unconnected - connect it")
    return notes


MODE = {"active": 0, "always": 0, "mute": 2, "never": 2, "bypass": 4}


def apply_ops(wf: dict, ops: list[dict], oi: dict | None = None) -> tuple[dict, list[str]]:
    """Apply edit operations to a COPY of a UI workflow. Returns (new_wf, log)."""
    if oi is None:
        oi, _ = get_object_info()
    fmt, base = unwrap(wf)
    if fmt == "api":
        return apply_ops_api(base, ops, oi)
    if fmt != "ui":
        raise EditError("Not a ComfyUI workflow")
    wf = copy.deepcopy(base)
    refs: dict[str, int] = {}
    log = []

    def rid(x):
        if isinstance(x, str) and x.startswith("$"):
            if x[1:] not in refs:
                raise EditError(f"Unknown ref {x}")
            return refs[x[1:]]
        return int(x) if isinstance(x, str) and x.lstrip("-").isdigit() else x

    for i, op in enumerate(ops or []):
        kind = op.get("op")
        try:
            if kind == "set_widget":
                n = _node(wf, rid(op["node"]))
                try:
                    old = set_widget(n, op["widget"], op.get("value"), oi)
                except EditError as e:
                    if _norm_label(op["widget"]) in _TEXT_ALIASES or "prompt" in _norm_label(op["widget"]):
                        txt = [f"{x.get('id')} '{x.get('title') or x.get('type')}'" for x in wf.get("nodes") or []
                               if (widget_slots(x.get("type"), oi, x.get("widgets_values") or []) or []) == ["text"]]
                        if txt:
                            raise EditError(f"{e}. Prompt text is the 'text' widget of these nodes: {', '.join(txt)}") from None
                    has = [f"{x.get('id')} {x.get('type')}" for x in wf.get("nodes") or []
                           if op["widget"] in (widget_slots(x.get("type"), oi, x.get("widgets_values") or []) or [])]
                    if has:
                        raise EditError(f"{e}. Widget '{op['widget']}' is on node(s): {', '.join(has)} - use that node id") from None
                    raise
                log.append(f"#{i} node {n['id']} {n['type']}.{op['widget']}: {str(old)[:60]!r} -> {str(op.get('value'))[:60]!r}")
            elif kind == "set_title":
                n = _node(wf, rid(op["node"]))
                n["title"] = op["title"]
                log.append(f"#{i} node {n['id']} title -> {op['title']}")
            elif kind == "set_mode":
                n = _node(wf, rid(op["node"]))
                n["mode"] = MODE.get(str(op.get("mode", "active")).lower(), 0)
                log.append(f"#{i} node {n['id']} mode -> {op.get('mode')}")
            elif kind == "remove_node":
                notes = remove_node(wf, rid(op["node"]), op.get("reconnect", True))
                log.append(f"#{i} removed node {op['node']}; " + "; ".join(notes))
            elif kind == "add_node":
                n = make_node(wf, op["type"], oi, op.get("widgets"), op.get("pos"), op.get("title"))
                if op.get("ref"):
                    refs[op["ref"]] = n["id"]
                log.append(f"#{i} added node {n['id']} {op['type']}" + (f" (ref ${op['ref']})" if op.get("ref") else ""))
            elif kind == "connect":
                lid = _add_link(wf, rid(op["from"]), op.get("from_slot", 0), rid(op["to"]), op["to_input"])
                log.append(f"#{i} link {lid}: {op['from']}[{op.get('from_slot', 0)}] -> {op['to']}.{op['to_input']}")
            elif kind == "disconnect":
                n = _node(wf, rid(op["node"]))
                for inp in n.get("inputs") or []:
                    if inp.get("name") == op["input"] and inp.get("link") is not None:
                        _remove_link(wf, inp["link"])
                log.append(f"#{i} disconnected {op['node']}.{op['input']}")
            elif kind == "replace_node":
                old = _node(wf, rid(op["node"]))
                new = make_node(wf, op["type"], oi, op.get("widgets"), old.get("pos"), op.get("title") or old.get("title"))
                ins = [(i_.get("name"), i_.get("type"), next((l for l in norm_links(wf) if l["id"] == i_.get("link")), None))
                       for i_ in old.get("inputs") or [] if i_.get("link") is not None]
                outs = []
                for o in old.get("outputs") or []:
                    for lid in o.get("links") or []:
                        l = next((x for x in norm_links(wf) if x["id"] == lid), None)
                        if l:
                            t = _node(wf, l["target_id"])
                            outs.append((o.get("type"), o.get("name"), l["target_id"], (t.get("inputs") or [])[l["target_slot"]].get("name")))
                remove_node(wf, old["id"], reconnect=False)
                moved = []
                for name, typ, l in ins:
                    tgt = next((x.get("name") for x in new["inputs"] if x.get("name") == name), None) or \
                          next((x.get("name") for x in new["inputs"] if x.get("type") == typ and x.get("link") is None), None)
                    if tgt and l:
                        _add_link(wf, l["origin_id"], l["origin_slot"], new["id"], tgt)
                        moved.append(f"in {name}")
                for typ, oname, tid, tname in outs:
                    slot = next((k for k, x in enumerate(new["outputs"]) if x.get("type") == typ), None)
                    if slot is not None:
                        _add_link(wf, new["id"], slot, tid, tname)
                        moved.append(f"out {typ}->{tid}")
                    else:
                        log.append(f"#{i} WARNING: new node has no {typ} output for node {tid}.{tname}")
                if op.get("ref"):
                    refs[op["ref"]] = new["id"]
                log.append(f"#{i} replaced node {old['id']} {old['type']} with {new['id']} {op['type']} ({', '.join(moved)})")
            elif kind == "add_group":
                wf.setdefault("groups", []).append({"title": op.get("title", "Group"), "bounding": op.get("bounding", [0, 0, 600, 400]),
                                                    "color": op.get("color", "#3f789e"), "font_size": 24, "flags": {}})
                log.append(f"#{i} added group {op.get('title')}")
            elif kind == "add_note":
                nid, _ = _max_ids(wf)
                wf.setdefault("nodes", []).append({"id": nid + 1, "type": "MarkdownNote", "pos": op.get("pos", [0, -300]),
                                                   "size": [420, 220], "flags": {}, "order": 0, "mode": 0, "inputs": [], "outputs": [],
                                                   "properties": {}, "widgets_values": [op.get("text", "")],
                                                   "title": op.get("title", "Note")})
                wf["last_node_id"] = nid + 1
                log.append(f"#{i} added note")
            else:
                raise EditError(f"Unknown op '{kind}'. Use set_widget, set_title, set_mode, remove_node, add_node, connect, disconnect, replace_node, add_group, add_note")
        except KeyError as e:
            raise EditError(f"op #{i} ({kind}) is missing field {e}")
        except EditError as e:
            raise EditError(f"op #{i} ({kind}) failed: {e}")
    return wf, log


def apply_ops_api(wf: dict, ops: list[dict], oi: dict) -> tuple[dict, list[str]]:
    wf = copy.deepcopy(wf)
    log = []
    for i, op in enumerate(ops or []):
        kind = op.get("op")
        nid = str(op.get("node", ""))
        if kind == "set_widget":
            if nid not in wf:
                raise EditError(f"op #{i}: no node {nid}")
            old = wf[nid]["inputs"].get(op["widget"])
            wf[nid]["inputs"][op["widget"]] = op.get("value")
            log.append(f"#{i} {nid}.{op['widget']}: {old!r} -> {op.get('value')!r}")
        elif kind == "remove_node":
            wf.pop(nid, None)
            log.append(f"#{i} removed {nid} (API format: re-link inputs manually with 'connect')")
        elif kind == "connect":
            wf[str(op["to"])]["inputs"][op["to_input"]] = [str(op["from"]), int(op.get("from_slot", 0))]
            log.append(f"#{i} {op['from']}[{op.get('from_slot', 0)}] -> {op['to']}.{op['to_input']}")
        elif kind == "add_node":
            new_id = str(max([int(k) for k in wf if str(k).isdigit()] + [0]) + 1)
            wf[new_id] = {"class_type": op["type"], "inputs": dict(op.get("widgets") or {})}
            log.append(f"#{i} added {new_id} {op['type']}")
        else:
            raise EditError(f"op '{kind}' not supported for API-format workflows")
    return wf, log


# ---------------------------------------------------------------- UI -> API

def ui_to_api(wf: dict, oi: dict | None = None) -> dict:
    fmt, wf = unwrap(wf)
    if fmt == "api":
        return wf
    if oi is None:
        oi, _ = get_object_info()
    if subgraphs(wf):
        raise ValueError("Workflow uses subgraphs; open it in ComfyUI and use 'Export (API)' instead.")
    nodes = {n["id"]: n for n in wf.get("nodes") or []}
    links = {l["id"]: l for l in norm_links(wf)}

    def resolve(lid, want_type=None, depth=0):
        """Return [origin_id, slot] or ('value', v) or None following reroutes/bypasses."""
        l = links.get(lid)
        if l is None or depth > 50:
            return None
        o = nodes.get(l["origin_id"])
        if o is None:
            return None
        if o.get("type") == "Reroute":
            ins = o.get("inputs") or []
            return resolve(ins[0].get("link"), want_type, depth + 1) if ins and ins[0].get("link") is not None else None
        if o.get("type") == "PrimitiveNode":
            wv = o.get("widgets_values") or []
            return ("value", wv[0] if wv else None)
        if o.get("mode") == 4:  # bypassed: pass through matching type
            t = l.get("type")
            for inp in o.get("inputs") or []:
                if inp.get("link") is not None and types_compatible(inp.get("type"), t):
                    return resolve(inp["link"], t, depth + 1)
            return None
        if o.get("mode") == 2:
            return None
        return [str(o["id"]), l["origin_slot"]]

    out = {}
    for nid, n in nodes.items():
        t = n.get("type")
        if t in FRONTEND_ONLY or n.get("mode") in (2, 4):
            continue
        info = oi.get(t)
        if not info:
            raise ValueError(f"Node {nid} type '{t}' is not installed - cannot convert")
        inputs = {}
        w = named_widgets(n, oi)
        for k, v in w.items():
            if not k.startswith(("widget_", "extra_")):
                inputs[k] = v
        linked_names = {i.get("name") for i in n.get("inputs") or [] if i.get("link") is not None}
        for sec, name, wt, o in input_defs(info):  # fill required widgets missing from older workflows with defaults
            if sec == "required" and is_widget(wt, o) and name not in inputs and name not in linked_names:
                if "default" in o:
                    inputs[name] = o["default"]
                elif combo_options(wt, o):
                    inputs[name] = combo_options(wt, o)[0]
        for inp in n.get("inputs") or []:
            if inp.get("link") is None:
                continue
            r = resolve(inp["link"])
            if r is None:
                continue
            if isinstance(r, tuple):
                inputs[inp["name"]] = r[1]
            else:
                inputs[inp["name"]] = r
        out[str(nid)] = {"class_type": t, "inputs": inputs, "_meta": {"title": n.get("title") or info.get("display_name") or t}}
    return out
