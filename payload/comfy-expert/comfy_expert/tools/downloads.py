"""Plan and perform model downloads into the right ComfyUI models subfolder (resume + size/sha256 check)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

from . import tool, ToolError
from .net import session, human_size
from ..config import load_config

FOLDERS = ["checkpoints", "loras", "vae", "unet", "diffusion_models", "text_encoders", "clip", "clip_vision", "controlnet",
           "upscale_models", "embeddings", "ipadapter", "ultralytics/bbox", "ultralytics/segm", "sams", "style_models",
           "hypernetworks", "photomaker", "instantid", "insightface", "animatediff_models", "model_patches", "vae_approx",
           "latent_upscale_models", "LLM", "audio_encoders", "gligen", "other"]

PROGRESS_CB = None  # set by UI to receive (done, total) updates


def _auth_headers(url: str) -> dict:
    host = urlparse(url).netloc.lower()
    cfg = load_config()
    if host.endswith("civitai.com") and cfg.key("civitai_api_key"):
        return {"Authorization": f"Bearer {cfg.key('civitai_api_key')}"}
    if host.endswith("huggingface.co") and cfg.key("hf_token"):
        return {"Authorization": f"Bearer {cfg.key('hf_token')}"}
    return {}


def _filename_from(r, url: str) -> str | None:
    cd = r.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return unquote(m.group(1)).strip()
    name = unquote(Path(urlparse(r.url or url).path).name)
    return name if "." in name else None


def _target(folder: str, filename: str, subfolder: str = "") -> Path:
    folder = (folder or "").strip().strip("/\\").replace("\\", "/")
    if folder not in FOLDERS:
        raise ToolError(f"Unknown folder '{folder}'. Use one of: {FOLDERS}")
    fn = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(". ")
    if not fn:
        raise ToolError("Bad filename")
    root = load_config().download_root().resolve()
    sub = re.sub(r"[^A-Za-z0-9 _.\-/]", "_", subfolder or "").strip("/")
    t = (root / folder / sub / fn).resolve() if sub else (root / folder / fn).resolve()
    if root not in t.parents:
        raise ToolError("Refusing to write outside the models folder")
    return t


def probe(url: str) -> dict:
    """Ask the server about the file without downloading it."""
    h = {"Range": "bytes=0-0", **_auth_headers(url)}
    r = session().get(url, headers=h, stream=True, allow_redirects=True, timeout=40)
    info = {"url": url, "final_host": urlparse(r.url).netloc, "status": r.status_code}
    ctype = r.headers.get("content-type", "")
    if r.status_code in (200, 206):
        if "text/html" in ctype or "json" in ctype:
            body = r.raw.read(600, decode_content=True).decode("utf-8", "replace")
            info.update(ok=False, problem="Server returned a web page / JSON instead of a file (login or licence needed?)", body=body[:300])
        else:
            total = None
            cr = r.headers.get("content-range")
            if cr and "/" in cr:
                tail = cr.split("/")[-1]
                total = int(tail) if tail.isdigit() else None
            elif r.headers.get("content-length") and r.status_code == 200:
                total = int(r.headers["content-length"])
            info.update(ok=True, size_bytes=total, size=human_size(total), filename=_filename_from(r, url),
                        resumable=r.status_code == 206)
    else:
        body = ""
        try:
            body = r.raw.read(400, decode_content=True).decode("utf-8", "replace")
        except Exception:
            pass
        problem = {401: "Login/API key required (set CIVITAI_API_KEY or HF_TOKEN in .env)",
                   403: "Forbidden: gated repo (accept licence on the website + HF_TOKEN) or early-access model",
                   404: "Not found", 451: "Blocked in your region"}.get(r.status_code, "HTTP error")
        if "REGION_BLOCKED" in body:
            problem = "Civitai is blocked in your region - use a mirror URL (see civitai_get_model mirror_urls) or a VPN"
        info.update(ok=False, problem=problem, body=body[:200])
    r.close()
    return info


@tool("plan_downloads",
      "Check a list of files BEFORE downloading: verifies each URL really works (size, filename, login needed?), picks the target "
      "ComfyUI models folder, says if already present, and checks free disk space. Downloads nothing.",
      {"items": {"type": "array", "items": {"type": "object", "properties": {
          "url": {"type": "string"}, "folder": {"type": "string", "enum": FOLDERS},
          "filename": {"type": "string"}, "subfolder": {"type": "string"}, "sha256": {"type": "string"},
          "why": {"type": "string"}}, "required": ["url", "folder"]}}},
      ["items"], category="downloads")
def plan_downloads(items: list):
    rows, total = [], 0
    for it in items or []:
        url = it.get("url", "")
        row = {"url": url, "folder": it.get("folder"), "why": it.get("why")}
        try:
            p = probe(url)
        except Exception as e:
            p = {"ok": False, "problem": f"{type(e).__name__}: {e}"[:200]}
        row.update({k: p.get(k) for k in ("ok", "size", "size_bytes", "problem", "final_host")})
        fn = it.get("filename") or p.get("filename")
        row["filename"] = fn
        if fn and p.get("ok"):
            try:
                t = _target(it.get("folder"), fn, it.get("subfolder", ""))
                row["target"] = str(t)
                row["already_exists"] = t.exists() and (not p.get("size_bytes") or t.stat().st_size == p["size_bytes"])
                if not row["already_exists"]:
                    total += p.get("size_bytes") or 0
            except ToolError as e:
                row.update(ok=False, problem=str(e))
        if it.get("sha256"):
            row["sha256"] = it["sha256"]
        rows.append(row)
    root = load_config().download_root()
    free = None
    try:
        probe_dir = root if root.exists() else root.anchor or "."
        free = shutil.disk_usage(probe_dir).free
    except Exception:
        pass
    return {"download_root": str(root), "items": rows, "total_to_download": human_size(total),
            "free_space": human_size(free), "enough_space": (free is None or free > total * 1.05),
            "next": "Show this list to the user. For each approved item call download_file (the user must confirm)."}


@tool("download_file",
      "Download ONE model file into the correct ComfyUI models subfolder (resumes partial downloads, checks size and sha256). "
      "Only after the user approved it.",
      {"url": {"type": "string"}, "folder": {"type": "string", "enum": FOLDERS}, "filename": {"type": "string"},
       "subfolder": {"type": "string", "default": ""}, "expected_size_bytes": {"type": "integer"},
       "sha256": {"type": "string"}},
      ["url", "folder"], gated=True, category="downloads")
def download_file(url: str, folder: str, filename: str = "", subfolder: str = "", expected_size_bytes: int | None = None,
                  sha256: str | None = None, confirm: bool = False):
    p = probe(url)
    if not p.get("ok"):
        raise ToolError(f"Cannot download: {p.get('problem')} (HTTP {p.get('status')})")
    fn = filename or p.get("filename")
    if not fn:
        raise ToolError("Could not work out a filename - pass filename")
    target = _target(folder, fn, subfolder)
    size = p.get("size_bytes") or expected_size_bytes
    if target.exists() and (not size or target.stat().st_size == size):
        return {"skipped": True, "reason": "already downloaded", "path": str(target)}
    if not confirm:
        return {"dry_run": True, "would_download": url, "to": str(target), "size": human_size(size),
                "message": "Ask the user to approve, then call again with confirm=true."}
    if target.exists():
        raise ToolError(f"A different file with the same name already exists: {target}. Choose another filename.")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = dict(_auth_headers(url))
    if have:
        headers["Range"] = f"bytes={have}-"
    r = session().get(url, headers=headers, stream=True, allow_redirects=True, timeout=60)
    if have and r.status_code == 200:
        have = 0  # server ignored range: restart
    elif r.status_code not in (200, 206):
        raise ToolError(f"HTTP {r.status_code} while downloading")
    mode = "ab" if have else "wb"
    done, t0, last = have, time.time(), 0.0
    with open(part, mode) as fh:
        for chunk in r.iter_content(1024 * 1024):
            if not chunk:
                continue
            fh.write(chunk)
            done += len(chunk)
            if PROGRESS_CB and time.time() - last > 1:
                last = time.time()
                PROGRESS_CB(fn, done, size)
    got = part.stat().st_size
    if size and got != size:
        return {"ok": False, "error": f"Incomplete: {human_size(got)} of {human_size(size)}. Run download_file again to resume.",
                "partial_file": str(part)}
    if sha256:
        h = hashlib.sha256()
        with open(part, "rb") as fh:
            for b in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                h.update(b)
        if h.hexdigest().lower() != sha256.lower():
            bad = part.with_name(part.name + ".badhash")
            os.replace(part, bad)
            raise ToolError(f"SHA256 mismatch - file kept as {bad} and NOT installed")
    os.replace(part, target)
    secs = max(time.time() - t0, 0.001)
    return {"downloaded": str(target), "size": human_size(got), "speed": human_size((got - have) / secs) + "/s",
            "sha256_checked": bool(sha256),
            "note": "Press 'r' in ComfyUI (or refresh the browser) so the new file shows up in the loader list."}
