"""Plan and perform model downloads into the right ComfyUI models subfolder (resume + size/sha256 check)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

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
            elif r.status_code == 200:
                total = _pos_int(r.headers.get("content-length"))
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
    size = _pos_int(p.get("size_bytes")) or _pos_int(expected_size_bytes)
    sha = sha256.strip().lower() if isinstance(sha256, str) else ""
    if sha.startswith("sha256:"):
        sha = sha[7:]
    if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ToolError("sha256 must be the 64-character hex SHA-256 of the file")
    if target.exists():
        same = (not size or target.stat().st_size == size) and (not sha or _sha_file(target) == sha)
        if same:
            return {"skipped": True, "reason": "already downloaded", "path": str(target),
                    "verified": "sha256" if sha else ("size" if size else "not checked (no size or sha256 known)")}
    if not confirm:
        return {"dry_run": True, "would_download": url, "to": str(target), "size": human_size(size),
                "message": "Ask the user to approve, then call again with confirm=true."}
    if target.exists():
        raise ToolError(f"A different file with the same name already exists: {target}. Choose another filename.")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    t0 = time.time()
    for round_ in (1, 2):
        got, total, err = _fetch(url, part, size, fn)
        if err == _RESTART and round_ == 1:
            continue
        if err == _RESTART:
            raise ToolError(f"{fn}: the server could not resume the download correctly twice - nothing installed")
        if err:
            return {"ok": False, "error": f"{err}. Run download_file again to resume.", "partial_file": str(part)}
        want = size or total
        if want and got < want:
            return {"ok": False, "error": f"Incomplete: {human_size(got)} of {human_size(want)}. Run download_file again to resume.",
                    "partial_file": str(part)}
        if (not want or got == want) and (not sha or _sha_file(part) == sha):
            break
        _remove(part)                              # too big / wrong size / wrong sha256: never installed
        if round_ == 2:
            raise ToolError(f"{fn} did not match its size / SHA-256 twice - deleted and NOT installed")
    os.replace(part, target)
    secs = max(time.time() - t0, 0.001)
    out = {"downloaded": str(target), "size": human_size(got), "speed": human_size(got / secs) + "/s",
           "sha256_checked": bool(sha), "size_checked": bool(want),
           "note": "Press 'r' in ComfyUI (or refresh the browser) so the new file shows up in the loader list."}
    if not want and not sha:
        out["warning"] = "Neither the size nor a SHA-256 was known, so the file could not be checked."
    return out


_RESTART = "restart"       # _fetch deleted a partial that could not be resumed: fetch again from the start
FAIL_FAST = {401: "login / API key required", 403: "forbidden (gated or early-access?)", 404: "not found", 410: "gone"}


def _pos_int(v) -> int | None:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _remove(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _content_range(r) -> tuple[int | None, int | None]:
    m = re.match(r"\s*bytes\s+(\d+)-\d+/(\d+|\*)", r.headers.get("content-range") or "")
    if not m:
        return None, None
    return int(m.group(1)), (int(m.group(2)) if m.group(2).isdigit() else None)


def _fetch(url: str, part: Path, size: int | None, fn: str) -> tuple[int, int | None, str | None]:
    """One pass: resume `part` if possible. -> (bytes in part, size the server reported, error or None).
    A partial that is already too big, or that the server cannot resume correctly, is started again."""
    have = part.stat().st_size if part.exists() else 0
    if size and have > size:
        _remove(part)
        have = 0
    if size and have == size:
        return have, size, None                    # complete already: only needs checking
    headers = dict(_auth_headers(url))
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        r = session().get(url, headers=headers, stream=True, allow_redirects=True, timeout=60)
    except requests.RequestException as e:
        return have, None, f"download failed ({type(e).__name__})"
    with r:
        if r.status_code in FAIL_FAST:
            raise ToolError(f"HTTP {r.status_code} while downloading: {FAIL_FAST[r.status_code]}")
        if r.status_code == 416 and have:          # nothing left to send: the partial is complete or wrong
            _, total = _content_range(r)
            if total and have == total:
                return have, total, None
            _remove(part)
            return 0, total, _RESTART
        if r.status_code not in (200, 206):
            raise ToolError(f"HTTP {r.status_code} while downloading")
        total = None
        if r.status_code == 206:
            start, total = _content_range(r)
            if start != have:                      # wrong piece: start over rather than glue bad bytes on
                _remove(part)
                return 0, total, _RESTART
        else:
            have = 0                               # server ignored the range: start from the beginning
            total = _pos_int(r.headers.get("content-length"))
        done, last = have, 0.0
        try:
            with open(part, "ab" if have else "wb") as fh:
                for chunk in r.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if size and done > size:       # more than the file should hold: stop, it will be deleted
                        break
                    if PROGRESS_CB and time.time() - last > 1:
                        last = time.time()
                        PROGRESS_CB(fn, done, size or total)
        except requests.RequestException as e:
            return part.stat().st_size if part.exists() else 0, total, f"connection lost ({type(e).__name__})"
    return part.stat().st_size, total, None
