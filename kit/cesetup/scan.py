"""System scan: OS, CPU, RAM, GPU (vendor / model / VRAM), free disk, Docker, WSL.

Read-only. Collects only what is needed to pick a llama.cpp build and models that fit.
It never records the computer name, user name, serial numbers or network details.
"""
from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil

from .util import GiB, IS_WIN, arch, gib, run, say, which

VENDORS = {"10de": "nvidia", "1002": "amd", "1022": "amd", "8086": "intel"}


def _vendor_from_name(name):
    n = (name or "").lower()
    if any(k in n for k in ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla")):
        return "nvidia"
    if any(k in n for k in ("amd", "radeon", "ati ")):
        return "amd"
    if any(k in n for k in ("intel", "arc ", "iris", "uhd graphics")):
        return "intel"
    if any(k in n for k in ("microsoft basic", "virtual", "vmware", "virtualbox", "parsec", "remote")):
        return "virtual"
    return "other"


def _nvidia_smi():
    if not which("nvidia-smi"):
        return []
    rc, out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"], 20)
    gpus = []
    if rc == 0:
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[1].replace(".", "").isdigit():
                gpus.append({"vendor": "nvidia", "name": parts[0], "vram_gib": round(float(parts[1]) / 1024, 1),
                             "driver": parts[2]})
    return gpus


def _ps_json(script, timeout=60):
    rc, out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    if rc != 0 or not out.strip():
        return []
    try:
        d = json.loads(out)
    except ValueError:
        return []
    return d if isinstance(d, list) else [d]


def _windows():
    info = {}
    os_rows = _ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,TotalVisibleMemorySize | ConvertTo-Json -Compress")
    if os_rows:
        info["os_name"] = os_rows[0].get("Caption") or "Windows"
        info["os_version"] = os_rows[0].get("Version") or ""
        if os_rows[0].get("TotalVisibleMemorySize"):
            info["ram_gib"] = round(int(os_rows[0]["TotalVisibleMemorySize"]) * 1024 / GiB, 1)
    cpu = _ps_json("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress")
    if cpu:
        info["cpu_name"] = (cpu[0].get("Name") or "").strip()
        info["cpu_cores"] = sum(int(c.get("NumberOfCores") or 0) for c in cpu) or None
        info["cpu_threads"] = sum(int(c.get("NumberOfLogicalProcessors") or 0) for c in cpu) or None
    # Win32_VideoController.AdapterRAM is capped at 4 GiB, so the real size comes from the display driver's
    # registry key (HardwareInformation.qwMemorySize). Only the adapter name and memory size are read.
    gpus = []
    reg = _ps_json(
        "Get-ItemProperty -Path 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' "
        "-ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ Name = $_.DriverDesc; "
        "Mem = $_.'HardwareInformation.qwMemorySize'; Mem32 = $_.'HardwareInformation.MemorySize' } } | ConvertTo-Json -Compress")
    for r in reg:
        name = (r.get("Name") or "").strip()
        if not name:
            continue
        mem = r.get("Mem") or 0
        if not mem:
            m32 = r.get("Mem32")
            if isinstance(m32, int):
                mem = m32
        if isinstance(mem, list):           # some drivers store it as REG_BINARY (little-endian bytes)
            try:
                mem = int.from_bytes(bytes(int(b) & 255 for b in mem), "little")
            except (TypeError, ValueError):
                mem = 0
        try:
            mem = int(mem)
        except (TypeError, ValueError):
            mem = 0
        gpus.append({"vendor": _vendor_from_name(name), "name": name, "vram_gib": round(mem / GiB, 1)})
    if not gpus:
        for v in _ps_json("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"):
            name = (v.get("Name") or "").strip()
            gpus.append({"vendor": _vendor_from_name(name), "name": name, "vram_gib": round(int(v.get("AdapterRAM") or 0) / GiB, 1)})
    # nvidia-smi is exact for NVIDIA cards and gives the driver version (needed to pick the CUDA build)
    smi = _nvidia_smi()
    if smi:
        gpus = [g for g in gpus if g["vendor"] != "nvidia"] + smi
    info["gpus"] = gpus
    return info


def _linux():
    info = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            kv = dict(l.strip().split("=", 1) for l in f if "=" in l)
        info["os_name"] = kv.get("PRETTY_NAME", "Linux").strip('"')
    except OSError:
        info["os_name"] = "Linux"
    info["os_version"] = platform.release()
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            mi = {l.split(":")[0]: l.split(":")[1].strip() for l in f if ":" in l}
        info["ram_gib"] = round(int(mi["MemTotal"].split()[0]) * 1024 / GiB, 1)
        info["ram_available_gib"] = round(int(mi.get("MemAvailable", "0 kB").split()[0]) * 1024 / GiB, 1)
    except (OSError, KeyError, ValueError):
        pass
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            txt = f.read()
        m = re.search(r"^model name\s*:\s*(.+)$", txt, re.M)
        info["cpu_name"] = m.group(1).strip() if m else platform.processor()
        cores = {(a, b) for a, b in re.findall(r"physical id\s*:\s*(\d+).*?core id\s*:\s*(\d+)", txt, re.S)}
        info["cpu_threads"] = len(re.findall(r"^processor\s*:", txt, re.M)) or os.cpu_count()
        info["cpu_cores"] = len(cores) or info["cpu_threads"]
        info["cpu_flags_avx2"] = " avx2 " in (" " + txt.replace("\n", " ") + " ")
    except OSError:
        pass
    gpus = []
    smi = _nvidia_smi()
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        try:
            with open(os.path.join(card, "vendor")) as f:
                ven = VENDORS.get(f.read().strip().lower().replace("0x", ""), "other")
        except OSError:
            continue
        if ven == "nvidia" and smi:
            continue
        vram = 0
        for fn in ("mem_info_vram_total",):
            p = os.path.join(card, fn)
            if os.path.exists(p):
                try:
                    vram = int(open(p).read().strip())
                except (OSError, ValueError):
                    pass
        name = ven.upper() + " GPU"
        if which("lspci"):
            slot = os.path.basename(os.path.realpath(card))
            rc, out = run(["lspci", "-s", slot], 10)
            if rc == 0 and ":" in out:
                name = out.split(":", 2)[-1].strip()
        if ven in ("amd", "intel", "nvidia", "other"):
            gpus.append({"vendor": ven, "name": name, "vram_gib": round(vram / GiB, 1)})
    info["gpus"] = smi + gpus
    info["vulkan_loader"] = bool(glob.glob("/usr/lib*/**/libvulkan.so.1", recursive=True) or glob.glob("/lib*/**/libvulkan.so.1", recursive=True))
    return info


def _docker():
    if not which("docker"):
        return {"installed": False, "running": False}
    rc, out = run(["docker", "info", "--format", "{{.ServerVersion}}"], 25)
    return {"installed": True, "running": rc == 0 and bool(out.strip())}


def best_gpu(gpus):
    real = [g for g in gpus if g.get("vendor") in ("nvidia", "amd", "intel")]
    if not real:
        return None
    return sorted(real, key=lambda g: ({"nvidia": 2, "amd": 1, "intel": 0}[g["vendor"]] if g.get("vram_gib", 0) >= 3.5 else -1,
                                       g.get("vram_gib", 0)), reverse=True)[0]


def choose_backend(info):
    """cuda for NVIDIA, vulkan for AMD / Intel (Arc or >=4 GiB dedicated), cpu otherwise."""
    g = best_gpu(info.get("gpus") or [])
    if not g or (g.get("vram_gib") or 0) < 3.5:
        return "cpu", None
    if g["vendor"] == "nvidia":
        return "cuda", g
    return "vulkan", g


def scan(install_dir=None):
    say("Scanning this computer (read-only)...")
    info = {"os": "windows" if IS_WIN else ("linux" if platform.system() == "Linux" else platform.system().lower()),
            "arch": arch(), "python": platform.python_version()}
    try:
        info.update(_windows() if IS_WIN else _linux())
    except Exception as ex:                    # a scan problem must never stop setup
        info["scan_error"] = repr(ex)[:200]
    info.setdefault("cpu_threads", os.cpu_count())
    info.setdefault("cpu_cores", info.get("cpu_threads"))
    info.setdefault("gpus", [])
    info.setdefault("ram_gib", 8.0)
    target = install_dir or os.path.expanduser("~")
    probe = target
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        info["disk_free_gib"] = round(gib(shutil.disk_usage(probe or os.path.expanduser("~")).free), 1)
    except OSError:
        info["disk_free_gib"] = 0.0
    backend, gpu = choose_backend(info)
    info["backend"] = backend
    info["gpu"] = gpu
    info["vram_gib"] = (gpu or {}).get("vram_gib", 0.0) if backend != "cpu" else 0.0
    return info


def describe(info):
    lines = ["  System     : %s (%s)" % (info.get("os_name", info["os"]), info["arch"]),
             "  Processor  : %s, %s cores / %s threads" % (info.get("cpu_name", "?"), info.get("cpu_cores"), info.get("cpu_threads")),
             "  Memory     : %.1f GiB RAM" % info.get("ram_gib", 0)]
    if info.get("gpus"):
        for g in info["gpus"]:
            lines.append("  Graphics   : %s (%s, %.1f GiB)" % (g.get("name"), g.get("vendor"), g.get("vram_gib") or 0))
    else:
        lines.append("  Graphics   : none found (models will run on the processor)")
    lines.append("  Free disk  : %.1f GiB" % info.get("disk_free_gib", 0))
    lines.append("  AI engine  : llama.cpp %s build" % {"cuda": "CUDA (NVIDIA)", "vulkan": "Vulkan (AMD / Intel)", "cpu": "CPU-only"}[info["backend"]])
    return "\n".join(lines)


if __name__ == "__main__":
    i = scan()
    say(describe(i))
    say(json.dumps(i, indent=1))
