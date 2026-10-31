"""Civitai REST API v1 (https://developer.civitai.com/site/reference) with automatic CivArchive fallback.

Civitai blocks some regions (e.g. the UK returns {"code":"REGION_BLOCKED"}). In that case the
tools fall back to civitaiarchive.com (CivArchive), which mirrors Civitai metadata and lists
alternative download mirrors (often Hugging Face copies) with SHA256 hashes.
"""
from __future__ import annotations

import json
import re

from . import tool, ToolError
from .net import get_json, session
from ..config import load_config

API = "https://civitai.com/api/v1"
ARCHIVE = "https://civitaiarchive.com"

MODEL_TYPES = ["Checkpoint", "TextualInversion", "Hypernetwork", "AestheticGradient", "LORA", "LoCon", "DoRA",
               "Controlnet", "Upscaler", "MotionModule", "VAE", "Poses", "Wildcards", "Workflows", "Detection", "Other"]

# Civitai model type -> ComfyUI models subfolder
TYPE_TO_FOLDER = {
    "checkpoint": "checkpoints", "lora": "loras", "locon": "loras", "dora": "loras", "lycoris": "loras",
    "textualinversion": "embeddings", "embedding": "embeddings", "hypernetwork": "hypernetworks",
    "controlnet": "controlnet", "upscaler": "upscale_models", "vae": "vae", "motionmodule": "animatediff_models",
    "detection": "ultralytics/bbox", "unet": "diffusion_models", "diffusion": "diffusion_models",
}


def folder_for(model_type: str | None, base_model: str | None = None, filename: str | None = None) -> str:
    t = (model_type or "").lower().replace(" ", "")
    fn = (filename or "").lower()
    if t == "checkpoint" and fn.endswith(".gguf"):
        return "unet"  # GGUF unets go to models/unet (ComfyUI-GGUF)
    return TYPE_TO_FOLDER.get(t, "checkpoints" if t == "checkpoint" else "other")


class RegionBlocked(Exception):
    pass


def _headers():
    k = load_config().key("civitai_api_key")
    return {"Authorization": f"Bearer {k}"} if k else {}


def _civ(path: str, params: dict | None = None):
    code, data, r = get_json(API + path, params=params, headers=_headers(), timeout=40)
    if isinstance(data, dict) and data.get("code") == "REGION_BLOCKED":
        raise RegionBlocked(data.get("error"))
    if code == 401:
        raise ToolError("Civitai said 401 Unauthorized - set CIVITAI_API_KEY in .env")
    if code != 200 or not isinstance(data, dict):
        raise ToolError(f"Civitai HTTP {code}: {r.text[:300]}")
    return data


def _fallback_ok() -> bool:
    return bool(load_config()["network"].get("civitai_fallback_archive", True))


def _strip_html(s: str | None, n: int = 600) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()[:n]


def _slim_file(f: dict, mtype: str | None) -> dict:
    out = {
        "name": f.get("name"),
        "size": f"{(f.get('sizeKB') or 0) / 1024 / 1024:.2f} GB" if (f.get("sizeKB") or 0) > 1024 * 900 else f"{(f.get('sizeKB') or 0) / 1024:.0f} MB",
        "size_bytes": int((f.get("sizeKB") or 0) * 1024),
        "type": f.get("type"),
        "primary": f.get("primary", f.get("is_primary")),
        "format": (f.get("metadata") or {}).get("format"),
        "fp": (f.get("metadata") or {}).get("fp"),
        "sha256": (f.get("hashes") or {}).get("SHA256") or f.get("sha256"),
        "download_url": f.get("downloadUrl"),
        "target_folder": folder_for(mtype, None, f.get("name")),
    }
    mirrors = [m.get("url") for m in f.get("mirrors") or [] if m.get("url") and m.get("source") != "civitai" and not m.get("deletedAt")]
    if mirrors:
        out["mirror_urls"] = [u if u.startswith("http") else ARCHIVE + u for u in mirrors[:6]]
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def _slim_version(v: dict, mtype: str | None) -> dict:
    out = {
        "version_id": v.get("id"), "name": v.get("name"), "base_model": v.get("baseModel"),
        "base_model_type": v.get("baseModelType"),
        "trigger_words": v.get("trainedWords") or v.get("trigger") or [],
        "created": v.get("createdAt") or v.get("publishedAt"),
        "download_url": v.get("downloadUrl") or f"https://civitai.com/api/download/models/{v.get('id')}",
        "files": [_slim_file(f, mtype) for f in (v.get("files") or [])][:6],
        "page": f"https://civitai.com/models/{v.get('modelId')}?modelVersionId={v.get('id')}" if v.get("modelId") else None,
        "notes": _strip_html(v.get("description"), 500),
    }
    imgs = v.get("images") or []
    metas = []
    for im in imgs[:6]:
        m = im.get("meta") or {}
        if m.get("prompt"):
            metas.append({k: m.get(k) for k in ("prompt", "negativePrompt", "sampler", "cfgScale", "steps", "Size", "clipSkip") if m.get(k)})
        if len(metas) >= 2:
            break
    if metas:
        out["example_settings"] = metas
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def _slim_model(m: dict, max_versions: int = 3) -> dict:
    mtype = m.get("type")
    return {
        "model_id": m.get("id"), "name": m.get("name"), "type": mtype, "nsfw": m.get("nsfw", m.get("is_nsfw")),
        "creator": (m.get("creator") or {}).get("username") or m.get("username"),
        "tags": (m.get("tags") or [])[:10],
        "downloads": (m.get("stats") or {}).get("downloadCount", m.get("downloadCount")),
        "rating": (m.get("stats") or {}).get("thumbsUpCount"),
        "page": f"https://civitai.com/models/{m.get('id')}",
        "versions": [_slim_version(v, mtype) for v in (m.get("modelVersions") or [])[:max_versions]],
    }


# ---------------- CivArchive fallback ----------------

def archive_search(query: str, platform: str | None = None, limit: int = 10) -> list[dict]:
    params = {"q": query}
    if platform:
        params["platform"] = platform
    code, data, _ = get_json(f"{ARCHIVE}/api/search", params=params, timeout=40)
    if code != 200 or not data:
        raise ToolError(f"CivArchive search HTTP {code}")
    out = []
    raw = data.get("results", [])
    raw = [r for r in raw if r.get("kind") != "file"] + [r for r in raw if r.get("kind") == "file"]
    for r in raw[: max(limit * 2, limit)]:
        out.append({"name": (r.get("name") or "").strip(), "type": r.get("type"), "base_model": r.get("base_model"),
                    "platform": r.get("platform"), "model_id": r.get("model_id"), "version_id": r.get("version_id"),
                    "nsfw": r.get("is_nsfw"), "downloads": r.get("download_count"), "deleted": r.get("is_deleted"),
                    "archive_page": ARCHIVE + (r.get("url") or "")})
    # dedupe by (platform, model, version)
    seen, res = set(), []
    for r in out:
        k = (r["platform"], r["model_id"], r["version_id"])
        if k not in seen:
            seen.add(k)
            res.append(r)
    return res[:limit]


def archive_model(model_id, version_id=None) -> dict:
    params = {"modelVersionId": version_id} if version_id else None
    code, data, r = get_json(f"{ARCHIVE}/api/models/{model_id}", params=params, timeout=40)
    if code != 200 or not isinstance(data, dict) or data.get("status") == "error":
        raise ToolError(f"CivArchive has no model {model_id} (HTTP {code})")
    return data


def _slim_archive_model(d: dict) -> dict:
    mtype = d.get("type")
    v = d.get("version") or {}
    sv = _slim_version(v, mtype) if v else {}
    sv["civitai_download_url"] = f"https://civitai.com/api/download/models/{v.get('id')}" if v.get("id") else None
    return {"model_id": d.get("id"), "name": d.get("name"), "type": mtype, "nsfw": d.get("is_nsfw"),
            "creator": d.get("creator_username") or d.get("username"), "tags": (d.get("tags") or [])[:10],
            "downloads": d.get("downloadCount"), "platform": d.get("platform"),
            "page": f"https://civitai.com/models/{d.get('id')}",
            "archive_page": f"{ARCHIVE}/models/{d.get('id')}",
            "deleted_on_civitai": bool(d.get("deletedAt")),
            "selected_version": sv,
            "other_versions": [{"version_id": x.get("id"), "name": x.get("name")} for x in (d.get("versions") or [])[:12]]}


def _blocked_note():
    return ("Civitai is region-blocked from this network (e.g. UK). Data below comes from CivArchive (civitaiarchive.com). "
            "Civitai download URLs will also be blocked here; prefer 'mirror_urls' (Hugging Face copies) - check the sha256 matches.")


# ---------------- tools ----------------

@tool("civitai_search_models",
      "Search Civitai models (checkpoints, LoRAs, VAEs, embeddings, upscalers...). Returns ids, base model, versions, "
      "file names, sizes, trigger words and download URLs. Falls back to CivArchive if Civitai is blocked.",
      {"query": {"type": "string", "description": "Search text, e.g. 'realistic SDXL', 'juggernaut'"},
       "types": {"type": "array", "items": {"type": "string", "enum": MODEL_TYPES}},
       "base_models": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['SDXL 1.0'], ['Illustrious'], ['Pony'], ['Flux.1 D'], ['Qwen'], ['Wan Video 2.2 T2V-A14B']"},
       "sort": {"type": "string", "enum": ["Highest Rated", "Most Downloaded", "Most Liked", "Newest"], "default": "Most Downloaded"},
       "period": {"type": "string", "enum": ["AllTime", "Year", "Month", "Week", "Day"], "default": "AllTime"},
       "nsfw": {"type": "boolean", "default": True},
       "limit": {"type": "integer", "default": 6}},
      [], category="models")
def civitai_search_models(query: str = "", types=None, base_models=None, sort: str = "Most Downloaded",
                          period: str = "AllTime", nsfw: bool = True, limit: int = 6):
    limit = max(1, min(int(limit or 6), 20))
    params: dict = {"limit": limit, "sort": sort or "Most Downloaded", "period": period or "AllTime",
                    "nsfw": "true" if nsfw else "false", "primaryFileOnly": "true"}
    if query:
        params["query"] = query
    if types:
        params["types"] = types if isinstance(types, list) else [types]
    if base_models:
        params["baseModels"] = base_models if isinstance(base_models, list) else [base_models]
    try:
        data = _civ("/models", params)
        return {"source": "civitai", "results": [_slim_model(m, 2) for m in data.get("items", [])],
                "next_cursor": (data.get("metadata") or {}).get("nextCursor")}
    except RegionBlocked:
        if not _fallback_ok():
            raise ToolError("Civitai is region-blocked; enable network.civitai_fallback_archive or set a proxy.")
        q = " ".join([query or ""] + list(base_models or [])).strip() or "realistic"
        res = archive_search(q, "civitai", limit * 2)
        if types:
            want = {t.lower() for t in types}
            res = [r for r in res if (r.get("type") or "").lower() in want] or res
        return {"source": "civarchive", "note": _blocked_note() + " Call civitai_get_model(model_id) for files/mirrors.",
                "results": res[:limit]}


@tool("civitai_get_model",
      "Get one Civitai model by id: all versions (up to 5), base model, trigger words, files, sizes, sha256, download URLs, example prompts.",
      {"model_id": {"type": "integer"}, "version_id": {"type": "integer", "description": "optional: focus on this version"}},
      ["model_id"], category="models")
def civitai_get_model(model_id: int, version_id: int | None = None):
    try:
        m = _civ(f"/models/{int(model_id)}")
        sm = _slim_model(m, 5)
        if version_id:
            sm["versions"] = [v for v in sm["versions"] if v.get("version_id") == int(version_id)] or sm["versions"]
        sm["description"] = _strip_html(m.get("description"), 800)
        sm["source"] = "civitai"
        return sm
    except RegionBlocked:
        d = _slim_archive_model(archive_model(model_id, version_id))
        d["source"] = "civarchive"
        d["note"] = _blocked_note()
        return d


@tool("civitai_get_version",
      "Get one Civitai model VERSION by version id (the number after modelVersionId=): base model, trigger words, files, download URL.",
      {"version_id": {"type": "integer"}}, ["version_id"], category="models")
def civitai_get_version(version_id: int):
    try:
        v = _civ(f"/model-versions/{int(version_id)}")
        mtype = (v.get("model") or {}).get("type")
        out = _slim_version(v, mtype)
        out.update({"model_id": v.get("modelId"), "model_name": (v.get("model") or {}).get("name"), "type": mtype, "source": "civitai"})
        return out
    except RegionBlocked:
        # CivArchive needs the model id; try sha-less lookup through search page
        r = session().get(f"{ARCHIVE}/api/model-versions/{int(version_id)}", timeout=30)
        if r.status_code == 200 and r.text.startswith("{"):
            d = r.json()
            if d.get("modelId"):
                res = _slim_archive_model(archive_model(d["modelId"], version_id))
                res.update({"source": "civarchive", "note": _blocked_note()})
                return res
        raise ToolError(f"Civitai is region-blocked and CivArchive lookup by version id failed. "
                        f"Use civitai_get_model(model_id=..., version_id={version_id}) if you know the model id.")


@tool("civitai_by_hash",
      "Identify a model file from its SHA256 (or AutoV2) hash: tells which Civitai model/version it is, plus mirrors.",
      {"sha256": {"type": "string"}}, ["sha256"], category="models")
def civitai_by_hash(sha256: str):
    h = sha256.strip()
    try:
        v = _civ(f"/model-versions/by-hash/{h}")
        mtype = (v.get("model") or {}).get("type")
        out = _slim_version(v, mtype)
        out.update({"model_id": v.get("modelId"), "model_name": (v.get("model") or {}).get("name"), "source": "civitai"})
        return out
    except RegionBlocked:
        code, data, _ = get_json(f"{ARCHIVE}/api/sha256/{h}")
        if code != 200 or not data or data.get("status") == "error":
            raise ToolError(f"Hash not found on CivArchive (HTTP {code})")
        return {"source": "civarchive", "note": _blocked_note(),
                "files": [{"filename": f.get("filename"), "url": f.get("url"), "source": f.get("source"),
                           "civitai_model_id": f.get("model_id"), "civitai_version_id": f.get("model_version_id")}
                          for f in data.get("files", [])[:10]]}


@tool("civitai_images",
      "Example images for a model/version WITH their generation settings (prompt, negative, sampler, steps, CFG). "
      "Great for copying settings that the model author/community used.",
      {"model_id": {"type": "integer"}, "version_id": {"type": "integer"},
       "nsfw": {"type": "string", "enum": ["None", "Soft", "Mature", "X"], "default": "X"},
       "limit": {"type": "integer", "default": 5}}, [], category="models")
def civitai_images(model_id: int | None = None, version_id: int | None = None, nsfw: str = "X", limit: int = 5):
    params = {"limit": max(1, min(int(limit or 5), 20)), "nsfw": nsfw or "X", "withMeta": "true", "sort": "Most Reactions"}
    if model_id:
        params["modelId"] = int(model_id)
    if version_id:
        params["modelVersionId"] = int(version_id)
    try:
        data = _civ("/images", params)
    except RegionBlocked:
        if model_id:
            d = archive_model(model_id, version_id)
            v = d.get("version") or {}
            ims = [{"url": i.get("url"), "meta": i.get("meta")} for i in (v.get("images") or [])[: params["limit"]]]
            return {"source": "civarchive", "note": _blocked_note(), "images": ims}
        raise ToolError("Civitai is region-blocked; give model_id so CivArchive can be used.")
    out = []
    for im in data.get("items", []):
        m = im.get("meta") or {}
        out.append({"url": im.get("url"), "nsfw_level": im.get("nsfwLevel"), "base_model": im.get("baseModel"),
                    "prompt": (m.get("prompt") or "")[:700], "negative": (m.get("negativePrompt") or "")[:400],
                    "sampler": m.get("sampler"), "scheduler": m.get("scheduler"), "steps": m.get("steps"),
                    "cfg": m.get("cfgScale"), "size": m.get("Size"), "clip_skip": m.get("clipSkip"),
                    "resources": [r.get("name") for r in (m.get("resources") or [])][:6]})
    return {"source": "civitai", "images": out}


@tool("model_archive_search",
      "Search CivArchive (civitaiarchive.com): an archive of Civitai, Tensor.Art, SeaArt and other sites, including "
      "models deleted from Civitai. Also good to find Hugging Face mirrors. platform: civitai | tensorart | seaart | (empty = all).",
      {"query": {"type": "string"}, "platform": {"type": "string", "default": ""},
       "limit": {"type": "integer", "default": 10}}, ["query"], category="models")
def model_archive_search(query: str, platform: str = "", limit: int = 10):
    return {"results": archive_search(query, platform or None, max(1, min(int(limit or 10), 30))),
            "tip": "For civitai results use civitai_get_model(model_id). For tensorart/seaart results use archive_get_page(archive_page)."}


@tool("archive_get_page",
      "Read a CivArchive model page (any platform, e.g. a Tensor.Art or SeaArt model mirrored there): files, sha256, base model, mirrors.",
      {"url": {"type": "string", "description": "archive_page URL from model_archive_search"}}, ["url"], category="models")
def archive_get_page(url: str):
    if not url.startswith(ARCHIVE):
        raise ToolError("url must be a civitaiarchive.com page")
    r = session().get(url, timeout=40)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise ToolError(f"Could not read page (HTTP {r.status_code})")
    try:
        p = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
        d = p.get("model") or {}
    except (ValueError, AttributeError):
        raise ToolError("CivArchive page data could not be read (the site may have changed)")
    v = d.get("version") or {}
    res = {"name": d.get("name"), "type": d.get("type"), "platform": d.get("platform"), "nsfw": d.get("is_nsfw"),
           "tags": (d.get("tags") or [])[:10], "base_model": v.get("baseModel"),
           "trigger_words": v.get("trigger") or v.get("trainedWords") or [],
           "downloadable_on_origin": v.get("allow_download"), "origin_page": v.get("platform_url"),
           "files": [_slim_file(f, d.get("type")) for f in (v.get("files") or [])[:5]],
           "description": _strip_html(d.get("description"), 600)}
    # look for real download mirrors by sha256
    for f in res["files"]:
        h = f.get("sha256")
        if h:
            try:
                code, data, _ = get_json(f"{ARCHIVE}/api/sha256/{h}", timeout=20)
                if code == 200 and data and data.get("files"):
                    f["mirror_urls"] = [x.get("url") for x in data["files"] if (x.get("url") or "").startswith("http")][:6]
            except Exception:
                pass
    return res
