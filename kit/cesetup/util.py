"""Small shared helpers: console output, yes/no questions, JSON files, paths."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys

GiB = 1024 ** 3
IS_WIN = os.name == "nt"
KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # .../kit
PACKAGE_ROOT = os.path.dirname(KIT_DIR)                                        # the unzipped kit folder
PAYLOAD_DIR = os.path.join(PACKAGE_ROOT, "payload")

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


def say(*a):
    print(*a, flush=True)


def gib(n):
    return (n or 0) / GiB


def is_yes(s):
    """Downloads and deletions only happen after the user types yes (any capitalisation)."""
    return (s or "").strip().lower() == "yes"


class Asker:
    """Reads answers from the keyboard, or from a dict in test mode (no keyboard needed)."""

    def __init__(self, answers=None, echo=True):
        self.answers = answers          # None = interactive
        self.echo = echo
        self.log = []

    @property
    def scripted(self):
        return self.answers is not None

    def ask(self, key, prompt, default=""):
        if self.answers is not None:
            v = self.answers.get(key, default)
            v = "" if v is None else str(v)
            if self.echo:
                say("%s%s   [test mode answer]" % (prompt, v))
        else:
            try:
                v = input(prompt).strip()
            except EOFError:
                v = ""
        if v == "":
            v = str(default)
        self.log.append((key, v))
        return v


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def run(cmd, timeout=60):
    """Run a command, return (rc, stdout). Never raises for a missing program."""
    try:
        kw = {}
        if IS_WIN:
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace", **kw)
        return p.returncode, (p.stdout or "") + ("\n" + p.stderr if p.returncode and p.stderr else "")
    except (OSError, subprocess.SubprocessError) as ex:
        return 127, str(ex)


def which(name):
    return shutil.which(name)


def default_install_dir():
    home = os.path.expanduser("~")
    return os.path.join(home, "ComfyUI-Expert")


def arch():
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x64"
