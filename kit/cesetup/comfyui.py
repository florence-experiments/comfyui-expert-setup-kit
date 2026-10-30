"""Find an existing ComfyUI (running or on disk), or install a fresh one (optional step).

Detection is read-only: it asks a ComfyUI already running on this computer (127.0.0.1:8188) where it lives,
reads the ComfyUI Desktop app's own settings file, and looks in the usual folders. Nothing is changed.
A fresh install uses the official release from github.com/Comfy-Org/ComfyUI (SHA-256 checked on Windows,
a pinned git tag on Linux). ComfyUI's own image models are NOT downloaded."""
from __future__ import annotations

import glob
import json
import os
import string
import urllib.request

from . import llamacpp
from .util import IS_WIN, read_json, run, say, which

DEFAULT_URL = "http://127.0.0.1:8188"
REPO_API = "https://api.github.com/repos/Comfy-Org/ComfyUI/releases?per_page=10"
REPO_GIT = "https://github.com/Comfy-Org/ComfyUI.git"


def _get_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:      # 127.0.0.1 only
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def is_comfy_dir(d):
    return bool(d) and os.path.isfile(os.path.join(d, "main.py")) and os.path.isdir(os.path.join(d, "comfy")) \
        and os.path.isdir(os.path.join(d, "models"))


def running(url=DEFAULT_URL):
    """-> {'url', 'version', 'root'} if a ComfyUI answers on this computer, else None."""
    st = _get_json(url.rstrip("/") + "/system_stats")
    if not isinstance(st, dict) or "system" not in st:
        return None
    sysd = st.get("system") or {}
    root = None
    argv = sysd.get("argv") or []
    if argv:
        cand = os.path.dirname(os.path.abspath(argv[0])) if argv[0].endswith(".py") else None
        if cand and is_comfy_dir(cand):
            root = cand
    return {"url": url, "version": sysd.get("comfyui_version") or "?", "root": root}


def _desktop_app_dirs():
    """ComfyUI Desktop keeps its 'basePath' (user files, models) in its config.json."""
    out = []
    for cfg in ([os.path.join(os.environ.get("APPDATA", ""), "ComfyUI", "config.json")] if IS_WIN else
                [os.path.expanduser("~/.config/ComfyUI/config.json")]):
        d = read_json(cfg, {}) or {}
        if d.get("basePath"):
            out.append(d["basePath"])
    return out


def find_on_disk(max_hits=6):
    home = os.path.expanduser("~")
    bases = [home, os.path.join(home, "Documents"), os.path.join(home, "Desktop"), os.path.join(home, "AI")]
    if IS_WIN:
        for letter in string.ascii_uppercase[2:]:
            drv = letter + ":\\"
            if os.path.isdir(drv):
                bases.append(drv)
                bases += [p for p in glob.glob(drv + "*") if os.path.isdir(p) and not os.path.basename(p).lower()
                          in ("windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
                              "system volume information", "users")]
    else:
        bases += ["/opt", "/srv", os.path.join(home, "apps"), os.path.join(home, "src")]
    hits, seen = [], set()
    pats = ["ComfyUI", "*/ComfyUI", "*/*/ComfyUI", "ComfyUI_windows_portable*/ComfyUI"]
    for b in bases:
        for pat in pats:
            for d in glob.glob(os.path.join(b, pat)):
                k = os.path.normcase(os.path.abspath(d))
                if k not in seen and is_comfy_dir(d):
                    seen.add(k)
                    hits.append(os.path.abspath(d))
                    if len(hits) >= max_hits:
                        return hits
    for d in _desktop_app_dirs():
        if os.path.isdir(d) and os.path.normcase(d) not in seen:
            hits.append(d)        # Desktop app: no main.py here, but models/ and user/ are
    return hits


def describe_found(run_info, disk):
    lines = []
    if run_info:
        lines.append("  ComfyUI    : running now at %s (version %s)%s" % (
            run_info["url"], run_info["version"], (", folder " + run_info["root"]) if run_info.get("root") else ""))
    elif disk:
        lines.append("  ComfyUI    : not running; found on disk:")
    else:
        lines.append("  ComfyUI    : not found (you can install it in a later step, or connect it later)")
    for d in disk:
        if not run_info or os.path.normcase(d) != os.path.normcase(run_info.get("root") or ""):
            lines.append("               - %s" % d)
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- fresh install
def windows_asset(backend, gpu_vendor):
    if backend == "cuda":
        return "ComfyUI_windows_portable_nvidia.7z"
    if gpu_vendor == "amd":
        return "ComfyUI_windows_portable_amd.7z"
    if gpu_vendor == "intel":
        return "ComfyUI_windows_portable_intel.7z"
    return "ComfyUI_windows_portable_nvidia.7z"       # runs on the processor with --cpu


def latest_release():
    with llamacpp._open(REPO_API, 40, {"Accept": "application/vnd.github+json"}) as r:
        rels = json.loads(r.read().decode("utf-8"))
    rels = [r for r in rels if not r.get("draft") and not r.get("prerelease")]
    return rels[0] if rels else None


def plan(hw):
    rel = latest_release()
    if not rel:
        raise RuntimeError("could not read the ComfyUI releases from GitHub")
    if IS_WIN:
        name = windows_asset(hw["backend"], (hw.get("gpu") or {}).get("vendor"))
        a = next((x for x in rel.get("assets", []) if x["name"] == name), None)
        if not a:
            raise RuntimeError("ComfyUI %s has no %s" % (rel["tag_name"], name))
        return {"tag": rel["tag_name"], "asset": a, "gib": a["size"] / 1024 ** 3}
    return {"tag": rel["tag_name"], "asset": None, "gib": 6.0}


def _seven_zip():
    for c in (which("7z"), which("7za"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if c and os.path.isfile(c):
            return c
    return None


TORCH_INDEX = {"cuda": None, "cpu": "https://download.pytorch.org/whl/cpu",
               "amd": "https://download.pytorch.org/whl/rocm6.4", "intel": "https://download.pytorch.org/whl/xpu"}


def install(dest_parent, hw, p, log=say):
    """Windows: official portable build. Linux: git clone of the release tag + its own venv. Returns the ComfyUI folder."""
    os.makedirs(dest_parent, exist_ok=True)
    if IS_WIN:
        a = p["asset"]
        sha = (a.get("digest") or "").split(":", 1)[-1].lower()
        if not sha:
            raise RuntimeError("GitHub did not publish a SHA-256 for %s - refusing to use it" % a["name"])
        arc = os.path.join(dest_parent, a["name"])
        if not os.path.exists(arc):
            log("   downloading %s (%.1f GB) ..." % (a["name"], a["size"] / 1e9))
            llamacpp.download(a["browser_download_url"], arc, a["size"], sha)
        log("   SHA-256 verified - unpacking (this takes a few minutes)...")
        sz = _seven_zip()
        rc, out = run([sz, "x", "-y", "-o" + dest_parent, arc] if sz else ["tar", "-xf", arc, "-C", dest_parent], 3600)
        if rc:
            raise RuntimeError("could not unpack %s (%s). Install 7-Zip from https://7-zip.org and run setup again."
                               % (a["name"], out.strip()[-200:]))
        os.remove(arc)
        hits = glob.glob(os.path.join(dest_parent, "ComfyUI_windows_portable*", "ComfyUI"))
        if not hits:
            raise RuntimeError("ComfyUI folder not found after unpacking")
        return hits[0]
    if not which("git"):
        raise RuntimeError("git is needed to install ComfyUI on Linux (e.g. sudo apt install git)")
    dest = os.path.join(dest_parent, "ComfyUI")
    if not is_comfy_dir(dest):
        log("   downloading ComfyUI %s (git, pinned tag)..." % p["tag"])
        rc, out = run(["git", "clone", "--depth", "1", "--branch", p["tag"], REPO_GIT, dest], 1800)
        if rc:
            raise RuntimeError("git clone failed: " + out.strip()[-300:])
    import sys
    venv = os.path.join(dest, ".venv")
    py = os.path.join(venv, "bin", "python")
    if not os.path.isfile(py):
        rc, out = run([sys.executable, "-m", "venv", venv], 600)
        if rc:
            raise RuntimeError("could not create a venv (on Debian/Ubuntu: sudo apt install python3-venv): " + out[-200:])
    key = "cuda" if hw["backend"] == "cuda" else ((hw.get("gpu") or {}).get("vendor") if hw["backend"] == "vulkan" else "cpu")
    idx = TORCH_INDEX.get(key or "cpu", TORCH_INDEX["cpu"])
    log("   installing PyTorch (%s build, several GB for GPU builds)..." % (key or "cpu"))
    cmd = [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-q", "torch", "torchvision", "torchaudio"]
    rc, out = run(cmd + (["--index-url", idx] if idx else []), 7200)
    if rc:
        raise RuntimeError("PyTorch install failed: " + out.strip()[-400:])
    log("   installing ComfyUI's requirements...")
    rc, out = run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-q", "-r",
                   os.path.join(dest, "requirements.txt")], 3600)
    if rc:
        raise RuntimeError("pip install -r requirements.txt failed: " + out.strip()[-400:])
    return dest


def start_command(root, hw):
    """How to start this ComfyUI (shown to the user and written into the Start-ComfyUI script)."""
    parent = os.path.dirname(root)
    if IS_WIN:
        for bat in ("run_nvidia_gpu.bat", "run_amd_gpu.bat", "run_intel_gpu.bat", "run_cpu.bat"):
            if os.path.isfile(os.path.join(parent, bat)):
                if hw["backend"] == "cpu" and os.path.isfile(os.path.join(parent, "run_cpu.bat")):
                    bat = "run_cpu.bat"
                return os.path.join(parent, bat)
        return None
    py = os.path.join(root, ".venv", "bin", "python")
    if os.path.isfile(py):
        return "%s %s --listen 127.0.0.1 --port 8188%s" % (py, os.path.join(root, "main.py"), " --cpu" if hw["backend"] == "cpu" else "")
    return None


# ------------------------------------------------------------------------------------- prompted detection helpers
PORTS = [8188, 8000, 8189, 8190, 8187, 8288, 8888]      # 8000 = ComfyUI Desktop app default


def running_all(ports=PORTS):
    out = []
    for p in ports:
        r = running("http://127.0.0.1:%d" % p)
        if r:
            out.append(r)
    return out


def is_desktop_base(d):
    """ComfyUI Desktop 'basePath': has models/ and user/ but the program itself lives elsewhere."""
    return bool(d) and os.path.isdir(os.path.join(d, "models")) and os.path.isdir(os.path.join(d, "user"))


def validate(path):
    """-> (ok, kind, message). kind: 'source' (main.py + models), 'desktop' (Desktop app data folder)."""
    if not path:
        return False, None, "no folder given"
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    for d in (path, os.path.join(path, "ComfyUI")):
        if is_comfy_dir(d):
            return True, "source", d
    if is_desktop_base(path):
        return True, "desktop", path
    if not os.path.isdir(path):
        return False, None, "folder does not exist: %s" % path
    return False, None, "no ComfyUI here (expected main.py, comfy/ and models/ - or the Desktop app's models/ and user/)"


def browse_folder():
    """Windows folder picker (no network). Returns a path or ''."""
    if not IS_WIN:
        return ""
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
          "$d.Description = 'Choose your ComfyUI folder'; if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }")
    rc, out = run(["powershell", "-NoProfile", "-STA", "-Command", ps], 600)
    return out.strip().splitlines()[-1] if (rc == 0 and out.strip()) else ""
