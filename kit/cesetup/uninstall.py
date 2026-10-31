# Built by Florence for the community.
"""Uninstall ComfyUI Expert. Asks before EVERY step (type yes); anything you don't confirm is left as it is.
Also undoes the optional HomeAI link (only the parts this kit added; HomeAI's backups are kept)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import control, homeai_link
from .util import IS_WIN, KIT_DIR, Asker, is_yes, read_json, say, write_json

ROOT = os.path.dirname(KIT_DIR)


def _size_gb(path):
    tot = 0
    for d, _, files in os.walk(path):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return tot / 1e9


def _rm(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


def _too_broad(path):
    """A drive root or the home folder is never offered for deletion, whatever install.json says."""
    p = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    return p in ("", os.path.normcase(os.path.abspath(os.path.expanduser("~"))).rstrip("\\/")) or \
        os.path.dirname(os.path.abspath(path)) == os.path.abspath(path)


def main(argv=None, ask=None, root=None):
    root = root or ROOT
    ask = ask or Asker()
    sp = os.path.join(root, "install.json")
    st = read_json(sp, None)
    if not isinstance(st, dict) or not st:
        say("No ComfyUI Expert installation found in %s" % root)
        return 2
    say("ComfyUI Expert uninstaller - each item is only removed if you type yes.\n")
    control.stop(root)

    def offer(key, question, action):
        if is_yes(ask.ask(key, question + " Type yes: ", "")):
            action()
            say("   done")
            return True
        say("   kept")
        return False

    link = st.get("homeai_link")
    if isinstance(link, dict) and link:
        if offer("unlink", "Undo the HomeAI link (remove the ComfyUI Expert model entry and the Prompt Artist button "
                 "from HomeAI at %s)?" % link.get("root"), lambda: homeai_link.unlink(link)):
            st.pop("homeai_link", None)
            write_json(sp, st)
    sc = [p for p in (st.get("shortcuts") if isinstance(st.get("shortcuts"), list) else [])
          if isinstance(p, str) and os.path.exists(p)]
    if sc:
        offer("shortcuts", "Remove %d ComfyUI Expert shortcut(s)?" % len(sc), lambda: [_rm(p) for p in sc])
    comfy = st.get("comfyui") if isinstance(st.get("comfyui"), dict) else {}
    if comfy.get("installed_by_kit") and isinstance(comfy.get("install_dir"), str) and os.path.isdir(comfy["install_dir"]) \
            and not _too_broad(comfy["install_dir"]):
        p = comfy["install_dir"]
        offer("comfyui", "Delete the ComfyUI that this kit installed, INCLUDING any models and pictures inside it (%s, %.1f GB)?"
              % (p, _size_gb(p)), lambda: _rm(p))
    for key, rel, what in (("models", "models", "the downloaded AI model(s)"),
                           ("chats", os.path.join("app", "data"), "your chats, lessons and settings in the app")):
        p = os.path.join(root, rel)
        if os.path.isdir(p):
            offer(key, "Delete %s (%s, %.1f GB)?" % (what, p, _size_gb(p)), lambda p=p: _rm(p))
    offer("rest", "Delete the rest of the ComfyUI Expert folder (%s: app, AI engine, Python, logs)?" % root, lambda: _rm_rest(root))
    say("\nUninstall finished. Anything you kept is still where it was.")
    return 0


def _rm_rest(root):
    keep = {n for n in ("models", "ComfyUI") if os.path.isdir(os.path.join(root, n))}
    data = os.path.join(root, "app", "data")
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if name in keep or name in ("kit", "python") or name.startswith("ComfyUI_windows_portable"):
            continue
        if name == "app" and os.path.isdir(data):
            for n in os.listdir(p):
                if n != "data":
                    _rm(os.path.join(p, n))
            continue
        _rm(p)
    if IS_WIN:
        cmd = 'ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s" & rmdir /s /q "%s" & rmdir "%s"' % (
            os.path.join(root, "kit"), os.path.join(root, "python"), root)
        subprocess.Popen(["cmd", "/c", cmd], creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True, cwd=os.path.dirname(root))
    else:
        _rm(os.path.join(root, "kit"))
        try:
            os.rmdir(root)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
