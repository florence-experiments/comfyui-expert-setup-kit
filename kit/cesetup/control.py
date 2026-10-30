# Built by Florence for the community.
"""Start, stop and check ComfyUI Expert: its AI brain (its own llama-server, or HomeAI's shared engine) and the app.

  python -m cesetup.control start [--no-browser] | stop | status

Everything listens on 127.0.0.1 only. Logs go to <install folder>/logs (overwritten at each start).
ComfyUI itself is started by you (or with the 'Start ComfyUI' script if the kit installed it)."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .util import IS_WIN, KIT_DIR, read_json

ROOT = os.path.dirname(KIT_DIR)
RESERVED = {8081, 8090}              # HomeAI engine and HomeAI app: never used by ComfyUI Expert


def say(m):
    print("[ComfyUI Expert] " + m, flush=True)


def ok(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def free_port(preferred, avoid=()):
    p = preferred
    while p in RESERVED or p in avoid or port_busy(p):
        p += 1
    return p


def state(root=ROOT):
    return read_json(os.path.join(root, "install.json"), {}) or {}


def _pidfile(root, name):
    d = os.path.join(root, "run")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name + ".pid")


def _spawn(root, name, cmd, cwd, env=None):
    logs = os.path.join(root, "logs")
    os.makedirs(logs, exist_ok=True)
    log = open(os.path.join(logs, name + ".log"), "w", encoding="utf-8")
    kw = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT, "env": env}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(cmd, **kw)
    with open(_pidfile(root, name), "w") as f:
        f.write(str(p.pid))
    return p


def _kill(root, name):
    pf = _pidfile(root, name)
    try:
        with open(pf) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        os.remove(pf)
    except OSError:
        pass
    return True


def llama_cmd(root, st):
    """The llama-server command line for ComfyUI Expert's own brain (also written to app/start-llama.*)."""
    b = st["brain"]
    exe = os.path.join(root, "engine", "llama.cpp", "llama-server.exe" if IS_WIN else "llama-server")
    cmd = [exe, "-m", b["model"]]
    if b.get("mmproj"):
        cmd += ["--mmproj", b["mmproj"]]
    cmd += ["--jinja", "-c", str(b.get("ctx", 32768)), "-ngl", "0" if b.get("cpu") else "99", "-fa", "on",
            "-ctk", "q8_0", "-ctv", "q8_0", "-np", "1"]
    if b.get("n_cpu_moe"):
        cmd += ["--n-cpu-moe", str(b["n_cpu_moe"])]
    if b.get("mtp"):
        cmd += ["--spec-type", "draft-mtp", "--spec-draft-n-max", "3"]
    cmd += list(b.get("sampling") or [])
    cmd += ["--host", "127.0.0.1", "--port", str(b["port"]), "-a", b.get("alias") or "comfy-expert"]
    return cmd


def start_brain(root=ROOT, wait=300):
    st = state(root)
    b = st.get("brain") or {}
    if b.get("shared_with_homeai"):
        url = b["url"].rstrip("/")
        if ok(url + "/health"):
            return True
        hroot = b.get("homeai_root")
        hpy = os.path.join(hroot, "python", "python.exe") if IS_WIN else (read_json(os.path.join(hroot, "install.json"), {}) or {}).get("python")
        if hroot and hpy and os.path.isfile(hpy) and os.path.isdir(os.path.join(hroot, "kit", "homeai_setup")):
            say("Starting HomeAI's AI engine (shared brain)...")
            env = dict(os.environ, PYTHONPATH=os.path.join(hroot, "kit"))
            subprocess.run([hpy, "-m", "homeai_setup.control", "start-engine"], env=env, cwd=hroot, timeout=wait)
            return ok(url + "/health")
        say("HomeAI's AI engine is not running - please start HomeAI first.")
        return False
    url = "http://127.0.0.1:%d" % b["port"]
    if ok(url + "/health"):
        return True
    if port_busy(b["port"]):
        say("Port %d is used by another program. Run setup again to pick another port." % b["port"])
        return False
    cmd = llama_cmd(root, st)
    if not os.path.isfile(cmd[0]):
        say("AI engine not found at %s - run setup again." % cmd[0])
        return False
    say("Starting the AI brain (loading the model can take a minute)...")
    _spawn(root, "llama", cmd, os.path.dirname(cmd[0]))
    end = time.time() + wait
    while time.time() < end:
        if ok(url + "/health"):
            return True
        time.sleep(1)
    say("The AI brain did not answer yet - see logs/llama.log")
    return False


def app_python(root):
    return os.path.join(root, "app", ".venv", "Scripts", "python.exe") if IS_WIN else os.path.join(root, "app", ".venv", "bin", "python")


def start_app(root=ROOT, wait=60):
    port = state(root).get("ui_port", 7860)
    if ok("http://127.0.0.1:%d/" % port):
        return True
    say("Starting the ComfyUI Expert app...")
    app = os.path.join(root, "app")
    _spawn(root, "app", [app_python(root), "-m", "comfy_expert", "web", "--no-browser", "--host", "127.0.0.1",
                          "--port", str(port)], app, dict(os.environ, PYTHONUTF8="1"))
    end = time.time() + wait
    while time.time() < end:
        if ok("http://127.0.0.1:%d/" % port):
            return True
        time.sleep(1)
    say("The app did not answer yet - see logs/app.log")
    return False


def start(root=ROOT, browser=True):
    b = start_brain(root)
    a = start_app(root)
    st = state(root)
    if st.get("comfyui", {}).get("url") and not ok(st["comfyui"]["url"].rstrip("/") + "/system_stats"):
        say("Note: ComfyUI is not running at %s - start it to queue pictures (chat works without it)." % st["comfyui"]["url"])
    if a:
        url = "http://127.0.0.1:%d/" % st.get("ui_port", 7860)
        say("Ready: " + url)
        if browser:
            webbrowser.open(url)
    return 0 if (b and a) else 1


def stop(root=ROOT):
    _kill(root, "app")
    _kill(root, "llama")          # HomeAI's shared engine is left alone: HomeAI owns it
    say("Stopped.")
    return 0


def status(root=ROOT):
    st = state(root)
    b = st.get("brain") or {}
    burl = b.get("url") or "http://127.0.0.1:%s" % b.get("port")
    say("AI brain : %s (%s)" % ("running" if ok(burl.rstrip("/") + "/health") else "stopped", burl))
    say("App      : %s" % ("running" if ok("http://127.0.0.1:%d/" % st.get("ui_port", 7860)) else "stopped"))
    c = (st.get("comfyui") or {}).get("url")
    if c:
        say("ComfyUI  : %s (%s)" % ("running" if ok(c.rstrip("/") + "/system_stats") else "stopped", c))
    return 0


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "start"
    if cmd == "start":
        return start(browser="--no-browser" not in a)
    if cmd == "stop":
        return stop()
    if cmd == "status":
        return status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
