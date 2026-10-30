"""Download the official llama.cpp build for this computer from github.com/ggml-org/llama.cpp/releases.

Picks the newest numbered release (bNNNNN) that has the right file: CUDA for NVIDIA, Vulkan for AMD / Intel,
CPU otherwise. Every file is checked against the SHA-256 digest GitHub publishes for it."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
import zipfile

from .hfcore import HostGuard, check_url
from .util import IS_WIN, gib, say

API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=%d"
ALLOWED = ["github.com", "api.github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
           "githubusercontent.com"]
UA = "ComfyUI-Expert-Setup-Kit/1.0"


def _open(url, timeout=60, headers=None):
    check_url(url, ALLOWED)
    op = urllib.request.build_opener(HostGuard(ALLOWED))
    return op.open(urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})}), timeout=timeout)


def releases(n=15):
    for attempt in range(3):
        try:
            with _open(API % n, 40, {"Accept": "application/vnd.github+json"}) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code in (403, 429) and attempt < 2:
                time.sleep(10 * (attempt + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
            time.sleep(5)
    return []


def wanted_assets(os_name, arch, backend, cuda_driver=None):
    """-> list of regexes, first = main archive; for CUDA on Windows also the CUDA runtime archive."""
    win = os_name == "windows"
    cuda13 = True
    try:
        cuda13 = float(str(cuda_driver).split(".")[0]) >= 580 if cuda_driver else True
    except ValueError:
        pass
    cv = r"13\.\d+" if cuda13 else r"12\.\d+"
    if win:
        if backend == "cuda" and arch == "x64":
            return [r"^llama-b\d+-bin-win-cuda-%s-x64\.zip$" % cv, r"^cudart-llama-bin-win-cuda-%s-x64\.zip$" % cv]
        if backend == "vulkan":
            return [r"^llama-b\d+-bin-win-vulkan-%s\.zip$" % arch]
        return [r"^llama-b\d+-bin-win-cpu-%s\.zip$" % arch]
    if backend == "cuda":
        return [r"^llama-b\d+-bin-ubuntu-cuda-%s-%s\.tar\.gz$" % (cv, arch),
                r"^cudart-llama-b\d+-bin-ubuntu-cuda-%s-%s\.tar\.gz$" % (cv, arch)]
    if backend == "vulkan":
        return [r"^llama-b\d+-bin-ubuntu-vulkan-%s\.tar\.gz$" % arch]
    return [r"^llama-b\d+-bin-ubuntu-%s\.tar\.gz$" % arch]


def pick_release(rels, patterns):
    """Newest release named bNNNN that has every wanted file (the 'latest' tag can be a non-binary release)."""
    rels = sorted([r for r in rels if re.fullmatch(r"b\d+", r.get("tag_name", "")) and not r.get("draft")],
                  key=lambda r: int(r["tag_name"][1:]), reverse=True)
    for r in rels:
        got = []
        for pat in patterns:
            a = next((a for a in r.get("assets", []) if re.match(pat, a["name"])), None)
            if not a:
                break
            got.append(a)
        if len(got) == len(patterns):
            return r["tag_name"], got
    return None, []


def download(url, dest, size, sha256):
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    h = hashlib.sha256()
    if have:
        with open(part, "rb") as f:
            for b in iter(lambda: f.read(8 << 20), b""):
                h.update(b)
    for attempt in range(5):
        try:
            with _open(url, 60, {"Range": "bytes=%d-" % have} if have else None) as r:
                mode = "ab" if have and r.status == 206 else "wb"
                if mode == "wb":
                    have, h = 0, hashlib.sha256()
                with open(part, mode) as out:
                    last = 0
                    for b in iter(lambda: r.read(4 << 20), b""):
                        out.write(b); h.update(b); have += len(b)
                        if time.time() - last > 2:
                            last = time.time()
                            print("\r   %s  %.0f / %.0f MB   " % (os.path.basename(dest), have / 1e6, (size or 0) / 1e6), end="", flush=True)
            break
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            say("\n   connection problem (%s), retrying..." % ex)
            time.sleep(4 * (attempt + 1))
            have = os.path.getsize(part) if os.path.exists(part) else 0
            h = hashlib.sha256()
            if have:
                with open(part, "rb") as f:
                    for b in iter(lambda: f.read(8 << 20), b""):
                        h.update(b)
    print()
    if size and have != size:
        raise RuntimeError("download incomplete (%d of %d bytes) - run setup again to resume" % (have, size))
    if sha256 and h.hexdigest() != sha256:
        os.replace(part, dest + ".bad-sha")
        raise RuntimeError("SHA-256 mismatch for %s - file NOT used" % os.path.basename(dest))
    os.replace(part, dest)
    return dest


def _safe_extract(archive, to):
    os.makedirs(to, exist_ok=True)
    root = os.path.realpath(to)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                name = m.filename.replace("\\", "/")
                target = os.path.realpath(os.path.join(to, name))
                if not target.startswith(root + os.sep) and target != root:
                    raise RuntimeError("unsafe path in archive: %s" % name)
                if name.endswith("/"):
                    os.makedirs(target, exist_ok=True); continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                target = os.path.realpath(os.path.join(to, m.name))
                if not target.startswith(root + os.sep) and target != root:
                    raise RuntimeError("unsafe path in archive: %s" % m.name)
            try:
                t.extractall(to, filter="data")
            except TypeError:
                t.extractall(to)


def install(engine_dir, hw, log=say, rels=None):
    """Download + verify + unpack into engine_dir/llama.cpp. Returns {'build', 'backend', 'server', 'files'}."""
    os_name, arch, backend = hw["os"], hw["arch"], hw["backend"]
    drv = (hw.get("gpu") or {}).get("driver")
    pats = wanted_assets(os_name, arch, backend, drv)
    rels = rels if rels is not None else releases()
    tag, assets = pick_release(rels, pats)
    if not tag and backend != "cpu":
        log("   no %s build found in the recent releases - using the CPU build instead" % backend)
        backend = "cpu"
        tag, assets = pick_release(rels, wanted_assets(os_name, arch, "cpu"))
    if not tag:
        raise RuntimeError("no suitable llama.cpp build found for %s %s" % (os_name, arch))
    dl = os.path.join(engine_dir, "downloads")
    os.makedirs(dl, exist_ok=True)
    dest_root = os.path.join(engine_dir, "llama.cpp")
    staging = dest_root + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    for a in assets:
        digest = (a.get("digest") or "").lower()
        sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
        if not sha:
            raise RuntimeError("GitHub did not publish a SHA-256 for %s - refusing to use it" % a["name"])
        log("   llama.cpp %s: %s (%.0f MB)" % (tag, a["name"], a["size"] / 1e6))
        path = os.path.join(dl, a["name"])
        if os.path.exists(path):
            with open(path, "rb") as f:
                ok = hashlib.sha256(f.read()).hexdigest() == sha
            if not ok:
                os.remove(path)
        if not os.path.exists(path):
            download(a["browser_download_url"], path, a["size"], sha)
        log("   SHA-256 verified")
        _safe_extract(path, staging)
    exe = "llama-server.exe" if IS_WIN or os_name == "windows" else "llama-server"
    found = None
    for d, _, files in os.walk(staging):
        if exe in files:
            found = d; break
    if not found:
        raise RuntimeError("llama-server not found in the downloaded archive")
    if found != staging:          # Linux tarballs have a top folder; Windows CUDA runtime DLLs sit next to it already
        for d, _, files in os.walk(staging):
            if d == found:
                continue
            for f in files:
                if f.lower().endswith((".dll", ".so")) or ".so." in f:
                    if not os.path.exists(os.path.join(found, f)):
                        shutil.copy2(os.path.join(d, f), os.path.join(found, f))
    if os.path.exists(dest_root):
        shutil.rmtree(dest_root + ".old", ignore_errors=True)
        os.replace(dest_root, dest_root + ".old")
    os.replace(found, dest_root) if found != staging else os.replace(staging, dest_root)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(dest_root + ".old", ignore_errors=True)
    shutil.rmtree(dl, ignore_errors=True)          # archives are verified and unpacked; free the space
    server = os.path.join(dest_root, exe)
    if not IS_WIN:
        for f in os.listdir(dest_root):
            p = os.path.join(dest_root, f)
            if os.path.isfile(p) and (f.startswith("llama-") or f.startswith("rpc-")) and "." not in f:
                os.chmod(p, 0o755)
    return {"build": tag, "backend": backend, "server": server, "assets": [a["name"] for a in assets]}
