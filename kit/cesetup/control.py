# Built by Florence for the community.
"""Start, stop and check ComfyUI Expert: its AI brain (its own llama-server, or HomeAI's shared engine) and the app.

  python -m cesetup.control start [--no-browser] | stop | status

Everything listens on 127.0.0.1 only. Logs go to <install folder>/logs (overwritten at each start).
ComfyUI itself is started by you (or with the 'Start ComfyUI' script if the kit installed it)."""
from __future__ import annotations

import json
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


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # 127.0.0.1 checks never go via a proxy


def ok(url, timeout=2):
    try:
        with _LOCAL.open(url, timeout=timeout) as r:
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
    st = read_json(os.path.join(root, "install.json"), {})
    return st if isinstance(st, dict) else {}


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
    try:
        p = subprocess.Popen(cmd, **kw)
    finally:
        log.close()                                    # the child keeps its own copy of the handle
    write_pidfile(_pidfile(root, name), p.pid, cmd)
    return p


# ---- pid files: {"pid", "start", "cmd", "exe"}. A pid is only signalled when the running process is provably the
# one ComfyUI Expert started (same start time, same command line / program), so a stale or reused pid never kills anything.
def _proc_start(pid):
    """Process start time as an opaque token (Linux: clock ticks since boot; Windows: creation FILETIME), or None."""
    if IS_WIN:
        return (_win_proc(pid) or {}).get("start")
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            stat = f.read().decode("utf-8", "replace")
        return int(stat[stat.rindex(")") + 2:].split()[19])      # field 22, counted after the "(comm)" field
    except (OSError, ValueError, IndexError):
        return None


def _proc_cmdline(pid):
    """Linux: argv of a running process as a list, or None."""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [a.decode("utf-8", "surrogateescape") for a in raw.split(b"\0")[:-1]] if raw else None


def _win_proc(pid):
    """Windows: {'start': creation time, 'exe': full program path} of a running process, or None (stdlib ctypes)."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, int(pid))            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:     # 259 = STILL_ACTIVE
                return None
            ft = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
                return None
            start = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
            buf = ctypes.create_unicode_buffer(32768)
            n = wintypes.DWORD(len(buf))
            exe = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
            return {"start": start, "exe": exe}
        finally:
            k32.CloseHandle(h)
    except (OSError, AttributeError, ValueError):
        return None


def _same_path(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (TypeError, ValueError):
        return False


def write_pidfile(pf, pid, cmd):
    rec = {"pid": int(pid), "start": _proc_start(pid), "cmd": [str(c) for c in cmd],
           "exe": os.path.abspath(str(cmd[0]))}
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    tmp = pf + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, pf)


def read_pidfile(pf):
    """-> record dict or None. Old kits wrote a bare number: that gives {'pid': n} with nothing to check against."""
    try:
        with open(pf, encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        rec = None
    if isinstance(rec, int):
        rec = {"pid": rec}
    if not isinstance(rec, dict):
        return None
    try:
        rec["pid"] = int(rec.get("pid"))
    except (TypeError, ValueError):
        return None
    return rec if rec["pid"] > 0 else None


def owned_pid(pf, expect_cmd=None):
    """The pid in pid file `pf` if that process is still the one ComfyUI Expert started, else None.
    expect_cmd: the command ComfyUI Expert would have started (used for old pid files that only hold a number)."""
    rec = read_pidfile(pf)
    if not rec:
        return None
    pid = rec["pid"]
    if pid == os.getpid():
        return None
    want = rec.get("cmd") or ([str(c) for c in expect_cmd] if expect_cmd else None)
    if not want:
        return None
    if rec.get("start") is not None and _proc_start(pid) != rec["start"]:
        return None                                    # pid gone or reused by a newer process
    if IS_WIN:
        info = _win_proc(pid)
        if not info or not info.get("exe") or not _same_path(info["exe"], rec.get("exe") or want[0]):
            return None
        return pid
    argv = _proc_cmdline(pid)
    if not argv:
        return None                                    # not running (or no /proc to check): never guess
    if argv == want or (len(argv) == len(want) and argv[1:] == want[1:] and _same_path(argv[0], want[0])):
        return pid
    return None


def kill_pidfile(pf, expect_cmd=None, log=None):
    """Stop the process recorded in pid file `pf` only if it is still ours; always removes the pid file.
    Returns True when a process was signalled."""
    if not os.path.exists(pf):
        return False
    pid = owned_pid(pf, expect_cmd)
    killed = False
    if pid is None:
        if log:
            log("%s: no matching ComfyUI Expert process is running (old pid file removed, nothing stopped)" % os.path.basename(pf))
    else:
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                try:
                    own_group = os.getpgid(pid) == pid and pid != os.getpgrp()
                except OSError:
                    own_group = False
                if own_group:                          # started with start_new_session: the group is ours
                    os.killpg(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
            killed = True
        except OSError:
            pass
    try:
        os.remove(pf)
    except OSError:
        pass
    return killed


def _kill(root, name, expect_cmd=None):
    return kill_pidfile(_pidfile(root, name), expect_cmd, say)


def llama_cmd(root, st):
    """The llama-server command line for ComfyUI Expert's own brain (also written to app/start-llama.*)."""
    b = st.get("brain") or {}
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
    cmd += ["--host", "127.0.0.1", "--port", str(b.get("port")), "-a", b.get("alias") or "comfy-expert"]
    return cmd


def start_brain(root=ROOT, wait=300):
    st = state(root)
    b = st.get("brain") or {}
    if b.get("shared_with_homeai"):
        url = str(b.get("url") or "http://127.0.0.1:8081").rstrip("/")
        if ok(url + "/health"):
            return True
        hroot = b.get("homeai_root") if isinstance(b.get("homeai_root"), str) else None
        hst = read_json(os.path.join(hroot, "install.json"), {}) if hroot else {}
        hpy = None
        if hroot:
            hpy = os.path.join(hroot, "python", "python.exe") if IS_WIN else (hst if isinstance(hst, dict) else {}).get("python")
        if hroot and hpy and os.path.isfile(hpy) and os.path.isdir(os.path.join(hroot, "kit", "homeai_setup")):
            say("Starting HomeAI's AI engine (shared brain)...")
            env = dict(os.environ, PYTHONPATH=os.path.join(hroot, "kit"))
            subprocess.run([hpy, "-m", "homeai_setup.control", "start-engine"], env=env, cwd=hroot, timeout=wait)
            return ok(url + "/health")
        say("HomeAI's AI engine is not running - please start HomeAI first.")
        return False
    if not isinstance(b.get("port"), int) or not b.get("model"):
        say("The AI brain settings in install.json are missing or damaged - run setup again (your chats are kept).")
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


def _ui_port(st):
    p = st.get("ui_port")
    return p if isinstance(p, int) and 0 < p < 65536 else 7860


def app_cmd(root, port):
    return [app_python(root), "-m", "comfy_expert", "web", "--no-browser", "--host", "127.0.0.1", "--port", str(port)]


def start_app(root=ROOT, wait=60):
    port = _ui_port(state(root))
    if ok("http://127.0.0.1:%d/" % port):
        return True
    say("Starting the ComfyUI Expert app...")
    app = os.path.join(root, "app")
    _spawn(root, "app", app_cmd(root, port), app, dict(os.environ, PYTHONUTF8="1"))
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
    curl = (st.get("comfyui") or {}).get("url") if isinstance(st.get("comfyui"), dict) else None
    if isinstance(curl, str) and curl and not ok(curl.rstrip("/") + "/system_stats"):
        say("Note: ComfyUI is not running at %s - start it to queue pictures (chat works without it)." % curl)
    if a:
        url = "http://127.0.0.1:%d/" % _ui_port(st)
        say("Ready: " + url)
        if browser:
            webbrowser.open(url)
    return 0 if (b and a) else 1


def stop(root=ROOT):
    """Stops only processes this kit started and that are provably still the same process (start time + command
    line), so a stale pid file can never stop an unrelated program that got the same pid."""
    st = state(root)
    _kill(root, "app", app_cmd(root, _ui_port(st)))
    _kill(root, "llama", llama_cmd(root, st) if (st.get("brain") or {}).get("model") else None)
    # HomeAI's shared engine is left alone: HomeAI owns it
    say("Stopped.")
    return 0


def status(root=ROOT):
    st = state(root)
    b = st.get("brain") or {}
    burl = b.get("url") or "http://127.0.0.1:%s" % b.get("port")
    say("AI brain : %s (%s)" % ("running" if ok(burl.rstrip("/") + "/health") else "stopped", burl))
    say("App      : %s" % ("running" if ok("http://127.0.0.1:%d/" % _ui_port(st)) else "stopped"))
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
