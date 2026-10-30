"""Start/stop/uninstall scripts in the install folder, plus desktop / start-menu shortcuts with the kit icon."""
from __future__ import annotations

import os
import subprocess
import sys

from .util import IS_WIN, say


def _write(p, text):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def write_scripts(root, comfy_start=None, llama_cmd=None):
    """Returns {key: path}. comfy_start: how to start a ComfyUI the kit installed. llama_cmd: list, for app/start-llama.*"""
    out = {}
    if IS_WIN:
        head = "@echo off\r\nrem Built by Florence for the community.\r\nset \"PYTHONPATH=%~dp0kit\"\r\n"
        py = "\"%~dp0python\\python.exe\""
        files = {"start": ("Start ComfyUI Expert.cmd", head + py + " -m cesetup.control start\r\nif errorlevel 1 pause\r\n"),
                 "stop": ("Stop ComfyUI Expert.cmd", head + py + " -m cesetup.control stop\r\ntimeout /t 3 >nul\r\n"),
                 "uninstall": ("Uninstall ComfyUI Expert.cmd", head + py + " -m cesetup.uninstall\r\npause\r\n")}
        if comfy_start:
            files["comfyui"] = ("Start ComfyUI.cmd", "@echo off\r\ncd /d \"%s\"\r\ncall \"%s\"\r\n"
                                % (os.path.dirname(comfy_start), comfy_start))
        if llama_cmd:
            files["llama"] = (os.path.join("app", "start-llama.bat"), "@echo off\r\nrem Starts only the AI brain (the Start "
                              "ComfyUI Expert shortcut does this for you).\r\n" + subprocess.list2cmdline(llama_cmd) + "\r\n")
    else:
        py = sys.executable
        sh = "#!/usr/bin/env bash\n# Built by Florence for the community.\ncd \"$(dirname \"$0\")\"\nexport PYTHONPATH=\"$PWD/kit\"\n"
        files = {"start": ("start-comfy-expert.sh", sh + "exec \"%s\" -m cesetup.control start \"$@\"\n" % py),
                 "stop": ("stop-comfy-expert.sh", sh + "exec \"%s\" -m cesetup.control stop\n" % py),
                 "uninstall": ("uninstall-comfy-expert.sh", sh + "exec \"%s\" -m cesetup.uninstall\n" % py)}
        if comfy_start:
            files["comfyui"] = ("start-comfyui.sh", "#!/usr/bin/env bash\nexec %s\n" % comfy_start)
        if llama_cmd:
            import shlex
            files["llama"] = (os.path.join("app", "start-llama.sh"), "#!/usr/bin/env bash\nexec " +
                              " ".join(shlex.quote(c) for c in llama_cmd) + "\n")
    for k, (name, text) in files.items():
        p = os.path.join(root, name)
        _write(p, text)
        if not IS_WIN:
            os.chmod(p, 0o755)
        out[k] = p
    return out


def _ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def make_shortcuts(root, scripts, log=say):
    made = []
    icon_ico = os.path.join(root, "kit", "icons", "comfy-expert.ico")
    icon_png = os.path.join(root, "kit", "icons", "comfy-expert.png")
    if IS_WIN:
        desktop = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True, timeout=30)
            if r.stdout.strip():
                desktop = r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "ComfyUI Expert")
        os.makedirs(menu, exist_ok=True)
        items = [("ComfyUI Expert", "start", True), ("Stop ComfyUI Expert", "stop", False),
                 ("Uninstall ComfyUI Expert", "uninstall", False), ("Start ComfyUI", "comfyui", False)]
        lines = ["$s = New-Object -ComObject WScript.Shell"]
        for name, key, on_desktop in items:
            if key not in scripts:
                continue
            for lnk in [os.path.join(menu, name + ".lnk")] + ([os.path.join(desktop, name + ".lnk")] if on_desktop else []):
                lines += ["$l = $s.CreateShortcut(%s)" % _ps_quote(lnk), "$l.TargetPath = %s" % _ps_quote(scripts[key]),
                          "$l.WorkingDirectory = %s" % _ps_quote(os.path.dirname(scripts[key])),
                          "$l.IconLocation = %s" % _ps_quote(icon_ico + ",0"),
                          "$l.WindowStyle = %d" % (7 if key in ("start", "stop") else 1), "$l.Save()"]
                made.append(lnk)
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "\n".join(lines)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            log("   could not create shortcuts: " + (r.stderr or "")[-200:])
            return []
        made.append(menu)
    else:
        apps = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
        os.makedirs(apps, exist_ok=True)
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        for name, key, term in (("ComfyUI Expert", "start", "false"), ("Stop ComfyUI Expert", "stop", "false"),
                                ("Uninstall ComfyUI Expert", "uninstall", "true")):
            text = ("[Desktop Entry]\nType=Application\nName=%s\nExec=\"%s\"\nIcon=%s\nTerminal=%s\nCategories=Graphics;Utility;\n"
                    % (name, scripts[key], icon_png, term))
            for d in [apps] + ([desk] if key == "start" and os.path.isdir(desk) else []):
                p = os.path.join(d, "comfy-expert-%s.desktop" % key)
                _write(p, text)
                os.chmod(p, 0o755)
                made.append(p)
    log("   %d shortcut(s) created" % len(made))
    return made
