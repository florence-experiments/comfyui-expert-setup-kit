# Built by Florence for the community.
"""ComfyUI Expert Setup Kit - the step-by-step installer.

  Windows: double-click Setup-Windows.cmd        Linux: bash setup-linux.sh
  Advanced: python -m cesetup.main [--answers answers.json] [--no-start]

Steps (each one is explained and asked before anything happens):
  1) look at this computer (read-only)       2) choose the install folder
  3) find your ComfyUI (or install it fresh) 4) link with HomeAI, if it is installed (optional)
  5) choose the AI model                     6) shortcuts
  7) show exactly what will be downloaded, and install ONLY after you type yes.
Everything runs on this computer; no telemetry. Nothing of anyone else's chats or settings is included."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from . import appconfig, comfyui, control, homeai_link as HL, hfsearch as S, launchers, llamacpp, models as M, scan
from .safety_text import SAFETY_RULE
from .util import IS_WIN, PACKAGE_ROOT, Asker, default_install_dir, is_yes, read_json, say, write_json

ENGINE_MB = {"cuda": 700, "vulkan": 60, "cpu": 40}
DOCS = ["README.md", "help.txt", "LICENSE", "DISCLAIMER.md", "THIRD_PARTY_NOTICES.md"]


def banner():
    say("=" * 72)
    say(" ComfyUI Expert Setup Kit - an AI helper for ComfyUI that runs on this computer")
    say("=" * 72)
    say(" ComfyUI Expert chats with you about ComfyUI, finds models and workflows, checks what you have")
    say(" installed, and its Prompt Artist turns ideas or pictures into ready-to-paste prompts.")
    say(" Everything runs locally; no telemetry. Nothing is downloaded until you have seen the list and typed yes.")
    say(" One fixed rule is built in and cannot be switched off: nothing sexual involving anyone under 18.")
    say(" Experimental software, provided as-is with no warranty - see DISCLAIMER.md.")


def step(n, total, title, why):
    say("\n" + "-" * 72)
    say(" Step %d of %d - %s" % (n, total, title))
    say("-" * 72)
    for line in why.split("\n"):
        say(" " + line)
    say("")


def yes_no(ask, key, q, default=True):
    v = ask.ask(key, "%s [%s] " % (q, "Y/n" if default else "y/N"), "y" if default else "n").strip().lower()
    return v in ("y", "yes", "j", "ja", "o", "oui", "s", "si", "1", "true")


def pick_number(ask, key, n_max, default=1, extra=()):
    """Returns an int 1..n_max or one of the extra letters."""
    while True:
        raw = ask.ask(key, "Your choice (Enter = %s): " % default, str(default)).strip().lower()
        if raw in extra:
            return raw
        try:
            n = int(raw)
            if 1 <= n <= n_max:
                return n
        except ValueError:
            pass
        say("Please type one of the choices shown.")
        if ask.scripted:
            return default


# ------------------------------------------------------------------------------------------------ step: ComfyUI
def comfy_step(ask, hw):
    """-> dict(url, root, kind, fresh, fresh_dir) or {} when skipped."""
    say("Searching for ComfyUI (read-only): running copies on this computer, the ComfyUI Desktop app,")
    say("portable ComfyUI_windows_portable folders and the usual folders%s..." % (" on every drive" if IS_WIN else " in your home folder"))
    runs = comfyui.running_all()
    disk = comfyui.find_on_disk()
    opts = []
    for r in runs:
        opts.append({"url": r["url"], "root": r.get("root"), "label": "running now at %s (version %s)%s" % (
            r["url"], r["version"], ", folder " + r["root"] if r.get("root") else "")})
    for d in disk:
        if any(o.get("root") and os.path.normcase(o["root"]) == os.path.normcase(d) for o in opts):
            continue
        ok, kind, _ = comfyui.validate(d)
        opts.append({"url": None, "root": d, "label": "%s (%s, not running)" % (d, "ComfyUI Desktop app" if kind == "desktop" else "folder")})
    extra = ["t", "i", "s"] + (["b"] if IS_WIN else [])
    if opts:
        say("Found:")
        for i, o in enumerate(opts, 1):
            say("  %d) %s" % (i, o["label"]))
        if len(opts) == 1:
            if yes_no(ask, "comfy_use", "Use this one?"):
                return _confirm_comfy(ask, opts[0])
        else:
            say("Which one should ComfyUI Expert use?")
    else:
        say("No ComfyUI was found.")
    say("  t) type the path of your ComfyUI folder")
    if IS_WIN:
        say("  b) browse for the folder")
    say("  i) install ComfyUI fresh (official release from github.com/Comfy-Org/ComfyUI, no image models)")
    say("  s) skip - set it up later in the app's Settings (chat and model search still work)")
    while True:
        c = pick_number(ask, "comfy_pick", len(opts), default=(1 if len(opts) > 1 else "s"), extra=extra)
        if isinstance(c, int):
            return _confirm_comfy(ask, opts[c - 1])
        if c == "s":
            say("Skipped. You can connect ComfyUI later in the app (Settings).")
            return {}
        if c == "i":
            return {"fresh": True}
        path = comfyui.browse_folder() if c == "b" else ask.ask("comfy_path", "ComfyUI folder: ", "")
        ok, kind, msg = comfyui.validate(path)
        if ok:
            return _confirm_comfy(ask, {"url": None, "root": msg})
        say("   That doesn't look like ComfyUI: %s. Try again, or choose i or s." % msg)
        if ask.scripted:
            return {}


def _confirm_comfy(ask, o):
    root = o.get("root")
    kind = None
    if root:
        ok, kind, msg = comfyui.validate(root)
        if not ok:
            say("   Warning: %s" % msg)
            root = None
        else:
            root = msg
    url = o.get("url") or comfyui.DEFAULT_URL
    for _ in range(3):
        r = comfyui.running(url)
        if r:
            say("   ComfyUI answers at %s (version %s) - connection checked." % (url, r["version"]))
            break
        say("   ComfyUI is not answering at %s right now (it may simply not be running)." % url)
        new = ask.ask("comfy_url", "Press Enter to keep this address (start ComfyUI later), or type another address: ", "")
        if not new.strip() or ask.scripted:
            break
        url = new.strip() if new.strip().startswith("http") else "http://" + new.strip()
    return {"url": url, "root": root, "kind": kind}


# ------------------------------------------------------------------------------------------------ step: HomeAI
def homeai_step(ask):
    h = HL.find()
    if not h:
        say("HomeAI (from the HomeAI Setup Kit) was not found - nothing to link. (Skip this step.)")
        p = ask.ask("homeai_path", "If HomeAI is installed somewhere else, type its folder (Enter = skip): ", "")
        h = HL.inspect(p.strip().strip('"')) if p.strip() else None
        if not h:
            return None
    say("Found HomeAI in %s (app on port %s, AI engine at %s)." % (h["root"], h["port"], h["llama_url"]))
    say("Linking is optional. It can:")
    say("  a) share ONE AI engine - ComfyUI Expert's model is added to HomeAI's engine, which keeps only one model")
    say("     in memory at a time, so the two apps never fill your graphics card twice;")
    say("  b) add a 'Prompt Artist (ComfyUI)' button to HomeAI.")
    say("HomeAI files are backed up before any change, and the uninstaller can undo the link.")
    if not yes_no(ask, "homeai_link", "Link ComfyUI Expert with HomeAI?", default=False):
        return None
    if h["kind"] != "kit" or not h.get("ini"):
        say("This HomeAI was not installed with the HomeAI Setup Kit, so it can't be changed automatically.")
        say("ComfyUI Expert will run its own AI engine on a free port (never 8081 or 8090), so there are no clashes.")
        return None
    share = yes_no(ask, "homeai_share", "a) Share HomeAI's AI engine?", default=True)
    preset = yes_no(ask, "homeai_preset", "b) Add the 'Prompt Artist (ComfyUI)' button to HomeAI?", default=True)
    if not (share or preset):
        return None
    return {"h": h, "share": share, "preset": preset}


# ------------------------------------------------------------------------------------------------ step: model
def model_step(ask, hw, link, token):
    """-> dict(kind=download|homeai|local, ...)"""
    hf = S.hf_client(os.path.join(PACKAGE_ROOT, "kit", "cache"), token)
    if os.environ.get("CE_KIT_TEST_TINY"):
        say("TEST MODE: using a tiny test model.")
        return {"kind": "download", "choice": M.fill_tiny(hf)}
    R = M.RECOMMENDED
    fit = M.recommended_fit(hw)
    opts = []
    say("  1) RECOMMENDED: %s" % R["name"])
    say("     The model ComfyUI Expert was built and tested with. Uncensored (no refusals for adult art), sees pictures,")
    say("     %.1f GiB download from %s" % (R["download_gib"], R["url"]))
    say("     On this computer: %s%s" % (fit["where"], (", about %.0f words/s" % (fit["tps"] * 0.75)) if fit.get("tps") else ""))
    if not fit["fits"]:
        say("     WARNING: probably too big for this computer - option 2 finds smaller models.")
    opts.append("rec")
    say("  2) Search Hugging Face for another model that fits this computer")
    opts.append("search")
    hm = []
    if link and link.get("share"):
        hm = [s for s in link["h"]["models"] if not s.startswith(HL.SECTION_PREFIX)]
        if hm:
            say("  3) Use a model HomeAI already has (no download)")
            opts.append("homeai")
    say("  %d) Use a GGUF model file already on this computer" % (len(opts) + 1))
    opts.append("local")
    while True:
        n = pick_number(ask, "model_pick", len(opts), default=1 if fit["fits"] else 2)
        k = opts[n - 1]
        if k == "rec":
            return {"kind": "download", "choice": R}
        if k == "search":
            unc = yes_no(ask, "uncensored", "Prefer uncensored models?", default=True)
            say("Searching Hugging Face (a minute or two)...")
            res, errs = M.search(hf, hw, uncensored=unc)
            if not res:
                say("No suitable model found right now%s." % (" (" + "; ".join(errs) + ")" if errs else ""))
                continue
            for i, ch in enumerate(res, 1):
                say(ch["_desc"].replace("  %d)" % 0, "  %d)" % i, 1) if ch.get("_desc") else "  %d) %s" % (i, ch["name"]))
            say("  0) back")
            m = pick_number(ask, "search_pick", len(res), extra=("0",))
            if m == "0":
                continue
            return {"kind": "download", "choice": res[m - 1]}
        if k == "homeai":
            for i, s in enumerate(hm, 1):
                info = link["h"]["model_info"].get(s, {})
                say("  %d) %s%s" % (i, s, " (sees pictures)" if info.get("mmproj") else " (text only - Prompt Artist can't see pictures)"))
            m = pick_number(ask, "homeai_model_pick", len(hm))
            return {"kind": "homeai", "section": hm[m - 1], "ctx": link["h"]["model_info"].get(hm[m - 1], {}).get("ctx", 0)}
        if k == "local":
            p = ask.ask("local_path", "Full path of the .gguf file: ", "").strip().strip('"')
            g = M.local_gguf(p)
            if g:
                say("   OK: %s (%s, %.1f GiB)%s" % (g["model"], g["arch"], g["gib"], ", vision add-on found" if g["mmproj"] else ""))
                return {"kind": "local", **g}
            say("   Not a GGUF model file.")
            if ask.scripted:
                return None


# ------------------------------------------------------------------------------------------------ plan + install
def show_plan(hw, root, comfy, link, mp, cplan):
    say("\n" + "=" * 72)
    say(" What will be downloaded and installed")
    say("=" * 72)
    say("  Folder    : %s" % root)
    total = 0.0
    if not (link and link.get("share")):
        mb = ENGINE_MB.get(hw["backend"], 60)
        say("  AI engine : llama.cpp (%s build) from github.com/ggml-org/llama.cpp, about %d MB, SHA-256 checked" % (hw["backend"].upper(), mb))
        total += mb / 1024
    else:
        say("  AI engine : HomeAI's (shared) - nothing to download")
    say("  App       : ComfyUI Expert + its Python packages (about 150 MB from pypi.org)")
    total += 0.15
    if mp["kind"] == "download":
        ch = mp["choice"]
        say("  Model     : %s %s, %.2f GiB from huggingface.co, SHA-256 checked" % (ch["repo"], ch["quant"], ch["download_gib"]))
        total += ch["download_gib"]
    elif mp["kind"] == "homeai":
        say("  Model     : HomeAI's %s (no download)" % mp["section"])
    else:
        say("  Model     : your file %s (no download)" % mp["model"])
    if comfy.get("fresh"):
        say("  ComfyUI   : fresh install %s, about %.1f GB%s (no image models)" % (cplan["tag"], cplan["gib"],
            ", SHA-256 checked" if IS_WIN else " incl. PyTorch"))
        total += cplan["gib"]
    elif comfy.get("url"):
        say("  ComfyUI   : use yours (%s%s)" % (comfy["url"], ", " + comfy["root"] if comfy.get("root") else ""))
    else:
        say("  ComfyUI   : not connected (can be set later)")
    if link:
        say("  HomeAI    : %s%s (HomeAI files backed up first)" % ("share the AI engine" if link["share"] else "",
            (" + " if link["share"] else "") + "Prompt Artist button" if link["preset"] else ""))
    say("  Total     : about %.1f GB" % total)


def copy_runtime(root):
    if not IS_WIN:
        return
    src, dst = sys.base_prefix, os.path.join(root, "python")
    if os.path.abspath(src) == os.path.abspath(dst) or os.path.isfile(os.path.join(dst, "python.exe")):
        return
    say("   copying Python into the install folder...")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))


def install_kit_files(root):
    dst = os.path.join(root, "kit")
    if os.path.abspath(os.path.join(PACKAGE_ROOT, "kit")) != os.path.abspath(dst):
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(PACKAGE_ROOT, "kit"), dst, ignore=shutil.ignore_patterns("__pycache__", "cache", ".runtime"))


def hardware_summary(hw):
    g = hw.get("gpu") or {}
    return "%s, %s, %.0f GB RAM, %s" % (hw.get("os_name") or hw["os"], hw.get("cpu_name") or "CPU",
                                       hw.get("ram_gib", 0), ("%s %.0f GB VRAM" % (g.get("name"), g.get("vram_gib", 0))) if g else "no usable GPU")


def install(root, hw, comfy, link, mp, cplan, token, shortcuts):
    sp = os.path.join(root, "install.json")
    st = read_json(sp, {})
    if not isinstance(st, dict):
        st = {}
    st.update({"kit_version": "1.0.0", "root": root, "installed": time.strftime("%Y-%m-%d")})
    if not IS_WIN:
        st["python"] = sys.executable
    os.makedirs(root, exist_ok=True)
    copy_runtime(root)
    install_kit_files(root)
    write_json(sp, st)
    N = 6
    # 1 engine
    say("\n[1/%d] AI engine" % N)
    if link and link.get("share"):
        say("   using HomeAI's engine")
    elif not isinstance(st.get("llama"), dict) or st["llama"].get("backend") != hw["backend"] or not os.path.isfile(control.llama_cmd(root, {"brain": {"model": "", "port": 0}})[0]):
        info = llamacpp.install(os.path.join(root, "engine"), hw)
        st["llama"] = {"build": info["build"], "backend": info["backend"]}
        write_json(sp, st)
    else:
        say("   already installed (%s)" % st["llama"]["build"])
    # 2 model
    say("\n[2/%d] AI model" % N)
    model = mmproj = None
    ctx, n_cpu_moe, mtp, sampling = 32768, 0, False, []
    if mp["kind"] == "download":
        ch = mp["choice"]
        hf = S.hf_client(os.path.join(root, "kit", "cache"), token)
        ok, model, mmproj = M.download(hf, root, ch)
        if not ok:
            raise RuntimeError("model download failed or the file did not match its SHA-256 - run setup again to resume")
        ctx, n_cpu_moe, mtp, sampling = max(ctx, int(ch.get("ctx") or 0)), int(ch.get("n_cpu_moe") or 0), bool(ch.get("mtp")), ch.get("sampling") or []
        if ch.get("params_b", 1) < 1:
            ctx = 8192        # tiny test model
    elif mp["kind"] == "local":
        model, mmproj = mp["model"], mp.get("mmproj")
    # 3 HomeAI link
    say("\n[3/%d] HomeAI link" % N)
    llm_url, llm_model = None, ""
    if link:
        h = link["h"]
        rec = {"root": h["root"], "ini": h["ini"], "data": h["data"], "backups": [], "preset": False}
        if link["share"]:
            if mp["kind"] == "homeai":
                llm_model = mp["section"]
            else:
                llm_model = HL.section_name(mp["choice"]) if mp["kind"] == "download" else HL.SECTION_PREFIX + os.path.basename(model)[:-5]
                HL.add_section(h, llm_model, model, mmproj, ctx, hw["backend"] != "cpu", n_cpu_moe, rec["backups"])
                rec["section"], rec["section_added"] = llm_model, True
                rec["state_added"] = HL.register_in_state(h, llm_model, model, mmproj, ctx, n_cpu_moe, rec["backups"])
            llm_url = h["llama_url"].rstrip("/") + "/v1"
            st["brain"] = {"shared_with_homeai": True, "url": h["llama_url"], "homeai_root": h["root"]}
            say("   AI engine shared: model id %s" % llm_model)
        if link["preset"]:
            pm = llm_model or (h["models"][0] if h["models"] else "")
            rec["preset"] = HL.add_preset(h, HL.prompt_artist_preset(os.path.join(PACKAGE_ROOT, "payload", "comfy-expert"), pm, SAFETY_RULE), rec["backups"])
            say("   Prompt Artist button %s" % ("added to HomeAI" if rec["preset"] else "could not be added"))
        for b in rec["backups"]:
            say("   backup: %s" % b)
        st["homeai_link"] = rec
    else:
        say("   not linked")
    if not llm_url:
        port = (st.get("brain") or {}).get("port") if (st.get("brain") or {}).get("port") and not control.port_busy(st["brain"]["port"]) else control.free_port(8080)
        st["brain"] = {"model": model, "mmproj": mmproj, "ctx": ctx, "cpu": hw["backend"] == "cpu", "n_cpu_moe": n_cpu_moe,
                       "mtp": mtp and model and "-mtp" in os.path.basename(model).lower(), "sampling": sampling, "port": port,
                       "alias": "comfy-expert"}
        llm_url = "http://127.0.0.1:%d/v1" % port
        if port != 8080:
            say("   port 8080 is busy, the AI brain will use port %d" % port)
    write_json(sp, st)
    # 4 ComfyUI
    say("\n[4/%d] ComfyUI" % N)
    comfy_start = None
    if comfy.get("fresh"):
        old = st.get("comfyui") if isinstance(st.get("comfyui"), dict) else {}
        d = comfyui.install(comfy.get("fresh_dir") or root, hw, cplan,
                            known=old.get("root") if old.get("installed_by_kit") and isinstance(old.get("root"), str) else None)
        comfy.update({"root": d, "url": comfyui.DEFAULT_URL, "installed_by_kit": comfyui.kit_installed(d),
                      "install_dir": os.path.dirname(d) if IS_WIN else d})
        comfy_start = comfyui.start_command(d, hw)
        say("   installed in %s" % d)
    elif comfy.get("root"):
        say("   using %s" % comfy["root"])
    else:
        say("   not connected")
    st["comfyui"] = {k: comfy.get(k) for k in ("url", "root", "installed_by_kit", "install_dir") if comfy.get(k)}
    write_json(sp, st)
    # 5 app
    say("\n[5/%d] ComfyUI Expert app" % N)
    app = os.path.join(root, "app")
    appconfig.copy_app(app)
    ui_port = control.free_port(st.get("ui_port") or 7860, avoid={st["brain"].get("port")}) if not control.port_busy(st.get("ui_port") or 0) else st["ui_port"]
    mcp_port = control.free_port(8765, avoid={ui_port, st["brain"].get("port")})
    st["ui_port"], st["mcp_port"] = ui_port, mcp_port
    croot = comfy.get("root")
    appconfig.write_config(app, {"llm_url": llm_url, "llm_model": llm_model, "ctx": ctx, "comfy_url": comfy.get("url"),
                                 "comfy_root": croot if comfy.get("kind") != "desktop" else "",
                                 "model_roots": [os.path.join(croot, "models")] if croot else [],
                                 "workflow_dirs": [os.path.join(croot, "user", "default", "workflows")] if croot else [],
                                 "ui_port": ui_port, "mcp_port": mcp_port, "hardware": hardware_summary(hw)})
    appconfig.make_venv(app, os.path.join(root, "python", "python.exe") if IS_WIN else sys.executable)
    write_json(sp, st)
    # 6 launchers
    say("\n[6/%d] Launchers and shortcuts" % N)
    scripts = launchers.write_scripts(root, comfy_start, control.llama_cmd(root, st) if not st["brain"].get("shared_with_homeai") else None)
    if shortcuts:
        st["shortcuts"] = sorted(set(st.get("shortcuts", []) + launchers.make_shortcuts(root, scripts)))
    for d in DOCS:
        s = os.path.join(PACKAGE_ROOT, d)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(root, d))
    write_json(sp, st)
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(description="ComfyUI Expert Setup Kit")
    ap.add_argument("--answers", help="JSON file with answers (testing / unattended installs)")
    ap.add_argument("--no-start", action="store_true", help="do not start ComfyUI Expert at the end")
    a = ap.parse_args(argv)
    answers = None
    if a.answers:
        try:
            with open(a.answers, encoding="utf-8-sig") as f:
                answers = json.load(f)
        except (OSError, ValueError) as ex:
            say("Could not read the answers file %s: %s" % (a.answers, ex))
            return 2
        if not isinstance(answers, dict):
            say("The answers file %s must hold a JSON object ({...})." % a.answers)
            return 2
    ask = Asker(answers)
    T = 7
    banner()
    step(1, T, "Look at this computer", "Reads your system, processor, memory, graphics card and free disk space, so the\n"
         "right AI engine build and a model that fits can be chosen. Read-only; nothing leaves this computer.")
    hw = scan.scan()
    say(scan.describe(hw))
    if hw["os"] not in ("windows", "linux"):
        say("Sorry, this kit supports Windows and Linux only.")
        return 2

    step(2, T, "Install folder", "Where ComfyUI Expert, its AI engine and its model will live (about 12 GB with the\n"
         "recommended model). Nothing outside this folder is changed, apart from shortcuts and the optional HomeAI link.")
    root = os.path.abspath(os.path.expanduser(ask.ask("install_dir", "Folder (Enter = %s): " % default_install_dir(), default_install_dir())))
    hw["disk_free_gib"] = scan.scan(root).get("disk_free_gib", hw.get("disk_free_gib")) if not ask.scripted else hw.get("disk_free_gib")
    if read_json(os.path.join(root, "install.json"), None):
        say("ComfyUI Expert is already installed there - your chats and settings are kept; setup will repair / update.")
    if hw.get("disk_free_gib", 0) < 2:
        say("Less than 2 GB free on that drive - please free some space or pick another folder.")
        return 2

    step(3, T, "Find your ComfyUI", "ComfyUI Expert reads your ComfyUI's models, nodes and workflows and can queue pictures\n"
         "in it. It needs to know where your ComfyUI is.")
    comfy = comfy_step(ask, hw)
    cplan = None
    if comfy.get("fresh"):
        try:
            cplan = comfyui.plan(hw)
        except Exception as ex:
            say("Could not read the ComfyUI releases (%s) - skipping ComfyUI; you can connect it later." % ex)
            comfy = {}
        if cplan:
            dflt = root
            comfy["fresh_dir"] = os.path.abspath(os.path.expanduser(ask.ask("comfy_dir", "Install ComfyUI into (Enter = %s): " % dflt, dflt)))
            if IS_WIN and hw["backend"] == "cpu":
                say("No usable graphics card was found: ComfyUI will run on the processor (very slow for pictures).")

    step(4, T, "HomeAI (optional)", "If you use HomeAI (from the HomeAI Setup Kit), the two can share one AI engine and\n"
         "HomeAI can get a Prompt Artist button. Ports never clash: HomeAI 8090, HomeAI engine 8081, ComfyUI Expert 8080/7860.")
    link = homeai_step(ask)

    step(5, T, "Choose the AI model", "The brain of ComfyUI Expert. Downloads come from huggingface.co and are checked\n"
         "against their published SHA-256 fingerprints.")
    token = os.environ.get("HF_TOKEN") or None
    mp = model_step(ask, hw, link, token)
    if not mp:
        say("No model chosen - nothing was installed.")
        return 1

    step(6, T, "Shortcuts", "A 'ComfyUI Expert' shortcut with the kit icon on the desktop and in the %s, plus Stop and Uninstall."
         % ("Start menu" if IS_WIN else "applications menu"))
    shortcuts = yes_no(ask, "shortcuts", "Create shortcuts?", default=True)

    step(7, T, "Check and install", "Here is everything that will happen. Nothing has been downloaded or changed yet.")
    show_plan(hw, root, comfy, link, mp, cplan)
    if not is_yes(ask.ask("confirm", "\nType yes to download and install (anything else cancels): ", "")):
        say("Cancelled - nothing was downloaded or installed.")
        return 0
    install(root, hw, comfy, link, mp, cplan, token, shortcuts)
    say("\n" + "=" * 72)
    say(" Done! ComfyUI Expert is installed in %s" % root)
    say(" Start it with %s" % ("the 'ComfyUI Expert' shortcut or 'Start ComfyUI Expert.cmd'" if IS_WIN else "./start-comfy-expert.sh (or the menu entry)"))
    say(" It opens in your browser. It starts fresh: no chats, drafts or history from anyone else.")
    say(" Remove it with 'Uninstall ComfyUI Expert'.")
    say("=" * 72)
    if not a.no_start and yes_no(ask, "start", "Start ComfyUI Expert now?", default=True):
        control.start(root)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nCancelled.")
        sys.exit(1)
