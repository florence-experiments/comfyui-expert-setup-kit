"""Hugging Face Hub API (no library needed). HF_TOKEN optional (needed for gated repos)."""
from __future__ import annotations

from urllib.parse import quote

from . import tool, ToolError
from .net import get_json, human_size
from ..config import load_config

HF = "https://huggingface.co"


def _headers():
    t = load_config().key("hf_token")
    return {"Authorization": f"Bearer {t}"} if t else {}


MODEL_EXT = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".onnx", ".sft")


def guess_folder(path: str) -> str:
    p = path.lower()
    name = p.rsplit("/", 1)[-1]
    if "lora" in p:
        return "loras"
    if name.endswith(".gguf"):
        if any(k in name for k in ("t5", "umt5", "qwen2.5-vl", "qwen_2.5_vl", "clip", "text_encoder", "llama", "gemma", "mistral")):
            return "text_encoders"
        return "unet"
    if "vae" in p:
        return "vae"
    if any(k in p for k in ("text_encoder", "t5xxl", "umt5", "clip_l", "clip_g", "qwen_2.5_vl", "qwen2.5_vl")):
        return "text_encoders"
    if "clip_vision" in p or "image_encoder" in p:
        return "clip_vision"
    if "controlnet" in p or "control_" in name:
        return "controlnet"
    if "ipadapter" in p or "ip-adapter" in p or "ip_adapter" in p:
        return "ipadapter"
    if "upscale" in p or "esrgan" in p or name.startswith(("4x", "2x", "8x")):
        return "upscale_models"
    if "diffusion_models" in p or "unet" in p or "transformer" in p:
        return "diffusion_models"
    if "yolo" in name or name.endswith(".pt") and "face" in name:
        return "ultralytics/bbox"
    return "checkpoints"


@tool("hf_search_models",
      "Search Hugging Face models. Good for official base models (Flux, Qwen-Image, Wan, SDXL), Comfy-Org repackaged "
      "files, GGUF quants (city96, QuantStack, unsloth), upscalers, ControlNets. author= narrows to one org/user.",
      {"query": {"type": "string"}, "author": {"type": "string"},
       "filter": {"type": "string", "description": "tag filter, e.g. 'gguf', 'text-to-image', 'lora', 'diffusers'"},
       "sort": {"type": "string", "enum": ["downloads", "likes", "lastModified", "trendingScore"], "default": "downloads"},
       "limit": {"type": "integer", "default": 10}}, [], category="models")
def hf_search_models(query: str = "", author: str = "", filter: str = "", sort: str = "downloads", limit: int = 10):
    params = {"sort": sort or "downloads", "direction": "-1", "limit": max(1, min(int(limit or 10), 40))}
    if query:
        params["search"] = query
    if author:
        params["author"] = author
    if filter:
        params["filter"] = filter
    code, data, r = get_json(f"{HF}/api/models", params=params, headers=_headers())
    if code != 200 or data is None:
        raise ToolError(f"HF search HTTP {code}: {r.text[:200]}")
    return {"results": [{"repo": m.get("id"), "downloads": m.get("downloads"), "likes": m.get("likes"),
                         "updated": m.get("lastModified"), "pipeline": m.get("pipeline_tag"),
                         "gated": m.get("gated"), "url": f"{HF}/{m.get('id')}"} for m in data]}


@tool("hf_list_files",
      "List files in a Hugging Face repo with sizes and ready-to-use download URLs and suggested ComfyUI folder. "
      "Use 'path' to look inside a subfolder and 'match' to filter names (e.g. 'Q4_K_M', 'fp8').",
      {"repo": {"type": "string", "description": "e.g. 'Comfy-Org/Qwen-Image_ComfyUI'"},
       "path": {"type": "string", "default": ""}, "match": {"type": "string", "default": ""},
       "revision": {"type": "string", "default": "main"}, "models_only": {"type": "boolean", "default": True}},
      ["repo"], category="models")
def hf_list_files(repo: str, path: str = "", match: str = "", revision: str = "main", models_only: bool = True):
    repo = repo.strip().strip("/").replace(f"{HF}/", "")
    rev = revision or "main"
    url = f"{HF}/api/models/{repo}/tree/{quote(rev, safe='')}" + (f"/{quote(path.strip('/'))}" if path else "")
    code, data, r = get_json(url, params={"recursive": "true", "expand": "false"}, headers=_headers(), timeout=60)
    if code == 401 or code == 403:
        raise ToolError(f"Repo {repo} is gated/private (HTTP {code}). Accept the licence on the HF page and set HF_TOKEN.")
    if code != 200 or not isinstance(data, list):
        raise ToolError(f"HF HTTP {code} for {repo}: {r.text[:200]}")
    files = []
    for e in data:
        if e.get("type") != "file":
            continue
        p = e.get("path", "")
        if models_only and not p.lower().endswith(MODEL_EXT):
            continue
        if match and match.lower() not in p.lower():
            continue
        size = (e.get("lfs") or {}).get("size") or e.get("size")
        files.append({"path": p, "size": human_size(size), "size_bytes": size,
                      "sha256": (e.get("lfs") or {}).get("oid"),
                      "download_url": f"{HF}/{repo}/resolve/{rev}/{quote(p)}",
                      "suggested_folder": guess_folder(p)})
    files.sort(key=lambda f: f["path"])
    total = len(files)
    return {"repo": repo, "count": total, "files": files[:80], "truncated": total > 80,
            "note": "Gated repos need HF_TOKEN + accepting the licence on the website."}


@tool("hf_model_info",
      "Hugging Face repo details: gated status, licence, tags, base model, and the start of the model card (README).",
      {"repo": {"type": "string"}}, ["repo"], category="models")
def hf_model_info(repo: str):
    repo = repo.strip().strip("/").replace(f"{HF}/", "")
    code, data, r = get_json(f"{HF}/api/models/{repo}", headers=_headers())
    if code != 200 or not data:
        raise ToolError(f"HF HTTP {code}: {r.text[:200]}")
    card = data.get("cardData") or {}
    from .net import session
    readme = ""
    rr = session().get(f"{HF}/{repo}/raw/main/README.md", headers=_headers(), timeout=30)
    if rr.status_code == 200:
        readme = rr.text[:5000]
    return {"repo": repo, "gated": data.get("gated"), "private": data.get("private"), "downloads": data.get("downloads"),
            "likes": data.get("likes"), "tags": (data.get("tags") or [])[:25], "license": card.get("license"),
            "base_model": card.get("base_model"), "pipeline": data.get("pipeline_tag"),
            "updated": data.get("lastModified"), "readme_start": readme}
