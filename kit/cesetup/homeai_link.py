"""Optional link with HomeAI (from the HomeAI Setup Kit, github.com/florence-experiments/homeai-setup-kit).

What linking does (each part is asked separately and can be undone from the uninstaller):
  1. Share one AI brain: ComfyUI Expert's model is added as one more [section] in HomeAI's engine/models.ini, and
     ComfyUI Expert talks to HomeAI's AI engine (llama.cpp router, 127.0.0.1:8081) instead of starting its own
     llama-server on 8080. The router keeps one model in memory at a time, so the two apps never hold two big
     models on the graphics card at once. Alternatively ComfyUI Expert can use a model HomeAI already has.
  2. A "Prompt Artist (ComfyUI)" button in HomeAI: a HomeAI preset with ComfyUI Expert's Prompt Artist
     instructions (and the fixed under-18 rule), using the shared model.
Every HomeAI file that is changed is first copied to <file>.bak-comfy-expert-<date-time>."""
from __future__ import annotations

import os
import re
import shutil
import string
import time

from .util import IS_WIN, read_json, say, write_json

HOMEAI_APP_PORT = 8090
HOMEAI_ENGINE_PORT = 8081
SECTION_PREFIX = "ComfyUI-Expert-"
PRESET_ID = "comfy-expert-prompt-artist"
MARK = "; added by the ComfyUI Expert Setup Kit"


def candidates():
    home = os.path.expanduser("~")
    c = [os.path.join(home, "HomeAI")]
    if IS_WIN:
        c += ["%s:\\HomeAI" % L for L in string.ascii_uppercase[2:] if os.path.isdir("%s:\\" % L)]
    return c


def inspect(root):
    """-> dict describing a HomeAI install in root, or None. Supports the HomeAI Setup Kit layout (install.json,
    engine/models.ini, homeai/data) and, read-only, an older hand-made layout (config.json + data/)."""
    if not root or not os.path.isdir(root):
        return None
    st = read_json(os.path.join(root, "install.json"), None)
    if isinstance(st, dict) and os.path.isdir(os.path.join(root, "homeai")):
        cfg = read_json(os.path.join(root, "homeai", "config.json"), {}) or {}
        ini = os.path.join(root, "engine", "models.ini")
        return {"root": root, "kind": "kit", "state": st, "ini": ini if os.path.isfile(ini) else None,
                "data": os.path.join(root, "homeai", "data"), "llama_url": cfg.get("llama_url") or "http://127.0.0.1:%d" % HOMEAI_ENGINE_PORT,
                "port": cfg.get("port") or HOMEAI_APP_PORT, "models": sorted((st.get("models") or {}).keys()),
                "model_info": st.get("models") or {}}
    cfg = read_json(os.path.join(root, "config.json"), None)
    if isinstance(cfg, dict) and cfg.get("llama_url") and os.path.isfile(os.path.join(root, "server.py")):
        return {"root": root, "kind": "manual", "state": {}, "ini": None, "data": os.path.join(root, cfg.get("data_dir") or "data"),
                "llama_url": cfg["llama_url"], "port": cfg.get("port") or HOMEAI_APP_PORT, "models": [], "model_info": {}}
    return None


def find():
    for c in candidates():
        h = inspect(c)
        if h:
            return h
    return None


def _backup(path, made):
    if os.path.isfile(path):
        b = "%s.bak-comfy-expert-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, b)
        made.append(b)
        return b
    return None


def section_name(choice):
    base = re.sub(r"(?i)[-_.]gguf$", "", choice["repo"].split("/", 1)[-1])
    return re.sub(r"[^A-Za-z0-9._-]+", "-", SECTION_PREFIX + base + "-" + choice["quant"])[:90]


def add_section(h, name, model, mmproj, ctx, gpu=True, n_cpu_moe=0, backups=None):
    """Append our [section] to HomeAI's models.ini (idempotent). Returns the section name."""
    ini = h["ini"]
    text = open(ini, encoding="utf-8").read()
    if re.search(r"(?m)^\[%s\]\s*$" % re.escape(name), text):
        return name
    _backup(ini, backups if backups is not None else [])
    lines = ["", MARK, "[%s]" % name, "model = %s" % model]
    if mmproj:
        lines.append("mmproj = %s" % mmproj)
    if not gpu:
        lines.append("n-gpu-layers = 0")
    elif n_cpu_moe:
        lines.append("n-cpu-moe = %d" % n_cpu_moe)
    lines += ["ctx-size = %d" % max(32768, int(ctx or 0)), "jinja = true", "flash-attn = on", "cache-type-k = q8_0",
              "cache-type-v = q8_0", ""]
    with open(ini, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return name


def register_in_state(h, name, model, mmproj, ctx, n_cpu_moe=0, backups=None):
    """HomeAI kit installs rebuild models.ini from install.json when a mode is added, so the entry is also recorded
    there (marked added_by=comfy-expert-kit) and survives. The model files stay in the ComfyUI Expert folder."""
    if h.get("kind") != "kit":
        return False
    sp = os.path.join(h["root"], "install.json")
    st = read_json(sp, None)
    if not isinstance(st, dict) or name in (st.get("models") or {}):
        return False
    _backup(sp, backups if backups is not None else [])
    st.setdefault("models", {})[name] = {"repo": "", "quant": "", "model": model, "files": [model] + ([mmproj] if mmproj else []),
                                         "ctx": max(32768, int(ctx or 0)), "n_cpu_moe": int(n_cpu_moe or 0),
                                         "added_by": "comfy-expert-kit", **({"mmproj": mmproj} if mmproj else {})}
    write_json(sp, st)
    return True


def unregister_in_state(root, name):
    sp = os.path.join(root or "", "install.json")
    st = read_json(sp, None)
    if isinstance(st, dict) and (st.get("models") or {}).get(name, {}).get("added_by") == "comfy-expert-kit":
        del st["models"][name]
        write_json(sp, st)
        return True
    return False


def remove_section(ini, name):
    """Removes exactly our section (and the marker line above it). Anything else in the file is left alone."""
    if not ini or not os.path.isfile(ini):
        return False
    text = open(ini, encoding="utf-8").read()
    pat = re.compile(r"\n?(?:%s\n)?\[%s\]\n(?:(?!\[).*\n?)*" % (re.escape(MARK), re.escape(name)))
    new, n = pat.subn("\n", text)
    if n:
        with open(ini, "w", encoding="utf-8", newline="\n") as f:
            f.write(new.rstrip("\n") + "\n")
    return bool(n)


def prompt_artist_preset(app_dir, model_id, safety_rule):
    p = os.path.join(app_dir, "comfy_expert", "prompts", "prompt_artist.md")
    body = open(p, encoding="utf-8").read() if os.path.isfile(p) else "You are Prompt Artist, an expert ComfyUI prompt writer."
    body = body.replace("{{LESSONS}}", "(none)").replace("{{INVENTORY}}", "(unknown - suggest common checkpoints)")
    return {"id": PRESET_ID, "name": "Prompt Artist (ComfyUI)", "color": "#f59e0b", "icon": "image", "model": model_id,
            "thinking": "off", "desc": "Picture or idea -> ready-to-paste ComfyUI prompt. Full app: http://127.0.0.1:7860",
            "starter": "Describe the picture you want, or attach an image to turn into a prompt.",
            "system": safety_rule + "\n\n" + body,
            "params": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "max_tokens": 0,
                       "repeat_penalty": 1.0, "seed": -1}}


def add_preset(h, preset, backups):
    pp = os.path.join(h["data"], "presets.json")
    presets = read_json(pp, None)
    if presets is None:
        presets = []
    if not isinstance(presets, list):
        return False
    if any(isinstance(x, dict) and x.get("id") == PRESET_ID for x in presets):
        return True
    _backup(pp, backups)
    presets.append(preset)
    write_json(pp, presets)
    return True


def remove_preset(data_dir):
    pp = os.path.join(data_dir, "presets.json")
    presets = read_json(pp, None)
    if not isinstance(presets, list):
        return False
    keep = [x for x in presets if not (isinstance(x, dict) and x.get("id") == PRESET_ID)]
    if len(keep) != len(presets):
        write_json(pp, keep)
        return True
    return False


def unlink(link, log=say):
    """Undo what link recorded in install.json: our models.ini section and our preset. Backups are kept."""
    if not link:
        return
    if link.get("section") and link.get("section_added"):
        log("   HomeAI models.ini: %s" % ("section removed" if remove_section(link.get("ini"), link["section"]) else "nothing to remove"))
        if link.get("state_added"):
            log("   HomeAI install.json: %s" % ("entry removed" if unregister_in_state(link.get("root"), link["section"]) else "nothing to remove"))
    if link.get("preset"):
        log("   HomeAI preset: %s" % ("removed" if remove_preset(link.get("data")) else "nothing to remove"))
    for b in link.get("backups", []):
        if os.path.exists(b):
            log("   backup kept: %s" % b)
