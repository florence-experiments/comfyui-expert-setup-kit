"""Writes the app's config.yaml (from config.example.yaml) and the app's own Python environment (.venv)."""
from __future__ import annotations

import os
import re
import shutil
import sys

from .util import IS_WIN, PAYLOAD_DIR, run, say


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


def set_key(text, section, key, value):
    """Replace 'key:' inside 'section:' of a simple 2-level YAML file, keeping the comment after it."""
    m = re.search(r"(?ms)^%s:\s*\n(.*?)(?=^\S|\Z)" % re.escape(section), text)
    if not m:
        return text + "\n%s:\n  %s: %s\n" % (section, key, value)
    block = m.group(1)
    pat = re.compile(r"(?m)^(  %s:)[ \t]*(?:'(?:[^']|'')*'|\"[^\"]*\"|\[[^\]]*\]|[^\s#]*)([ \t]*#.*)?$" % re.escape(key))
    if pat.search(block):
        block = pat.sub(lambda mm: "%s %s%s" % (mm.group(1), value, mm.group(2) or ""), block, count=1)
    else:
        block = "  %s: %s\n" % (key, value) + block
    return text[:m.start(1)] + block + text[m.end(1):]


def copy_app(dst):
    """Copies the app into dst. A previous config.yaml, .env, data/ (chats, lessons) and .venv are kept."""
    src = os.path.join(PAYLOAD_DIR, "comfy-expert")
    keep = {"config.yaml", ".env", "data", ".venv", "cache", "drafts", "start-llama.bat", "start-llama.sh"}
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        if name in keep and os.path.exists(os.path.join(dst, name)):
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(s, d)


def write_config(app, s):
    """s: dict with llm_url, llm_model, ctx, comfy_url, comfy_root, model_roots, workflow_dirs, ui_port, mcp_port, hardware."""
    path = os.path.join(app, "config.yaml")
    base = path if os.path.isfile(path) else os.path.join(app, "config.example.yaml")
    t = open(base, encoding="utf-8").read()
    if base.endswith("example.yaml"):
        t = t.replace("# ComfyUI Expert settings. setup.bat copies this to config.yaml - edit config.yaml, not this file.",
                      "# ComfyUI Expert settings, written by the ComfyUI Expert Setup Kit. You can edit this file.")
    t = set_key(t, "llm", "base_url", q(s["llm_url"]))
    t = set_key(t, "llm", "model", q(s.get("llm_model") or ""))
    t = set_key(t, "llm", "context_size", str(int(s.get("ctx") or 32768)))
    t = set_key(t, "comfyui", "url", q(s.get("comfy_url") or "http://127.0.0.1:8188"))
    t = set_key(t, "comfyui", "root", q(s.get("comfy_root") or ""))
    t = set_key(t, "comfyui", "model_roots", "[" + ", ".join(q(x) for x in s.get("model_roots") or []) + "]")
    t = set_key(t, "comfyui", "workflow_dirs", "[" + ", ".join(q(x) for x in s.get("workflow_dirs") or []) + "]")
    t = set_key(t, "ui", "port", str(s.get("ui_port") or 7860))
    t = set_key(t, "mcp", "port", str(s.get("mcp_port") or 8765))
    t = set_key(t, "hardware", "summary", q(s.get("hardware") or ""))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(t)
    env = os.path.join(app, ".env")
    if not os.path.exists(env):
        shutil.copy2(os.path.join(app, ".env.example"), env)
    return path


def venv_python(app):
    return os.path.join(app, ".venv", "Scripts", "python.exe") if IS_WIN else os.path.join(app, ".venv", "bin", "python")


def make_venv(app, base_python=None, log=say):
    py = venv_python(app)
    if not os.path.isfile(py):
        log("   creating the app's own Python environment (.venv)...")
        rc, out = run([base_python or sys.executable, "-m", "venv", os.path.join(app, ".venv")], 900)
        if rc:
            raise RuntimeError("could not create a Python venv (%s)%s" % (out.strip()[-200:],
                               "" if IS_WIN else " - on Debian/Ubuntu run: sudo apt install python3-venv"))
    log("   installing the app's Python packages (pip, a few minutes the first time)...")
    rc, out = run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-q", "-r",
                   os.path.join(app, "requirements.txt")], 3600)
    if rc:
        raise RuntimeError("pip install failed: " + out.strip()[-400:])
    return py
