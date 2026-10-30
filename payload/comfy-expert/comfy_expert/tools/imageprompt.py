"""Prompt Artist: image -> detailed analysis, best model family (from the user's own checkpoints) and ready prompts.

The image is sent to a vision-capable llama-server (OpenAI-style image_url). By default that is the helper's own
llama-server (start-llama.bat loads the model's mmproj so it can see); if it cannot see images, the optional
fallback (e.g. the llama router on port 8081) is used."""
from __future__ import annotations

import base64
import io
import json
import re
import struct
from pathlib import Path

import requests

from . import tool, ToolError
from ..config import APP_DIR, PKG_DIR, load_config

from ..safety import with_safety_rule

SYSTEM_FILE = PKG_DIR / "prompts" / "prompt_artist.md"
REFINE_FILE = PKG_DIR / "prompts" / "prompt_refine.md"
FIXING_FILE = PKG_DIR / "knowledge" / "prompt_fixing.md"
UPLOADS = APP_DIR / "cache" / "uploads"
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
             ".bmp": "image/bmp", ".gif": "image/gif"}
MAX_IMAGE_BYTES = 25 * 2**20

# first match wins; names are matched lower-case
FAMILY_RULES: list[tuple[str, str]] = [
    (r"noob", "NoobAI-XL"),
    (r"pony|pdxl|autismmix", "Pony (SDXL)"),
    (r"animagine", "Animagine XL"),
    (r"illustrious|^wai|[_\-.]wai|ilxl|novaanimexl|nova.?orange|hassakuxl|prefectious|oneobsession|\bil[_\-]", "Illustrious-XL"),
    (r"chroma", "Chroma"),
    (r"flux", "Flux"),
    (r"qwen.?rapid|rapid.?aio|qwen.?image.?edit|qwen.?edit|qwen_edit", "Qwen-Image-Edit"),
    (r"qwen.?image", "Qwen-Image"),
    (r"z.?image", "Z-Image"),
    (r"wan2|wan_2|wan-2", "Wan video"),
    (r"sd3|sd_3|stable.?diffusion.?3", "SD3"),
    (r"realistic_?vision|v1-5|sd15|sd_15|sd1\.5|dreamshaper_\d|epicrealism_|majicmix|chilloutmix|meinamix|counterfeit|anything.?v\d", "SD 1.5"),
    (r"xl|juggernaut|realvis|zavy", "SDXL"),
]


def classify(filename: str) -> str:
    over = {k.lower(): v for k, v in ((load_config().get("vision") or {}).get("family_overrides") or {}).items()}
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower() in over:
        return over[name.lower()]
    low = name.lower()
    for pat, fam in FAMILY_RULES:
        if re.search(pat, low):
            return fam
    return "unknown family"


def inventory() -> dict:
    """{'checkpoints': {family: [files]}, 'loras': {family: [files]}} from the user's model folders."""
    from .comfy import model_index
    idx = model_index(force=True)
    out: dict[str, dict[str, list[str]]] = {"checkpoints": {}, "loras": {}}
    for folder in ("checkpoints", "diffusion_models", "unet"):
        for e in idx.get(folder, []):
            out["checkpoints"].setdefault(classify(e["rel"]), []).append(e["rel"])
    for e in idx.get("loras", []):
        out["loras"].setdefault(classify(e["rel"]), []).append(e["rel"])
    for sec in out.values():
        for k in sec:
            sec[k] = sorted(set(sec[k]), key=str.lower)
    return out


def inventory_text(inv: dict) -> str:
    lines = []
    for title, key in (("Checkpoints / diffusion models", "checkpoints"), ("LoRAs", "loras")):
        lines.append(f"**{title}:**")
        if not inv.get(key):
            lines.append("- (none found)")
        for fam, files in sorted(inv.get(key, {}).items()):
            lines.append(f"- {fam}: " + ", ".join(f"`{f}`" for f in files))
    return "\n".join(lines)


def _lessons_text(family: str = "", checkpoint: str = "") -> str:
    from . import lessons
    try:
        return lessons.as_text(lessons.relevant(family, checkpoint, 10))
    except Exception:                       # a broken lessons file must never stop Prompt Artist
        return "(none yet)"


def system_prompt(inv: dict | None = None, lessons_text: str | None = None) -> str:
    return with_safety_rule(SYSTEM_FILE.read_text(encoding="utf-8")
            .replace("{{LESSONS}}", lessons_text if lessons_text is not None else _lessons_text())
            .replace("{{INVENTORY}}", inventory_text(inv if inv is not None else inventory())))


def family_conventions() -> str:
    """The verified per-family section of the Prompt Artist prompt (shared with fix mode)."""
    t = SYSTEM_FILE.read_text(encoding="utf-8")
    m = re.search(r"## Family conventions[^\n]*\n(.*?)(?=\n## )", t, re.S)
    return m.group(1).strip() if m else ""


def refine_system_prompt(inv: dict | None = None, lessons_text: str | None = None) -> str:
    fixing = FIXING_FILE.read_text(encoding="utf-8").split("\n", 2)[-1] if FIXING_FILE.is_file() else ""
    return with_safety_rule(REFINE_FILE.read_text(encoding="utf-8")
            .replace("{{FAMILY_CONVENTIONS}}", family_conventions())
            .replace("{{FIXING}}", fixing.strip())
            .replace("{{LESSONS}}", lessons_text if lessons_text is not None else _lessons_text())
            .replace("{{INVENTORY}}", inventory_text(inv if inv is not None else inventory())))


# ---------------------------------------------------------------- image facts (no Pillow needed)
def image_info(p: Path) -> dict:
    """Width, height and JPEG EXIF orientation read from the file header."""
    d = p.read_bytes()[: 4 * 2**20]
    info: dict = {"width": 0, "height": 0, "orientation": 1}
    try:
        if d[:8] == b"\x89PNG\r\n\x1a\n":
            info["width"], info["height"] = struct.unpack(">II", d[16:24])
        elif d[:2] == b"\xff\xd8":
            i = 2
            while i + 4 < len(d):
                if d[i] != 0xFF:
                    i += 1
                    continue
                mk = d[i + 1]
                if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
                    i += 2
                    continue
                ln = struct.unpack(">H", d[i + 2:i + 4])[0]
                seg = d[i + 4:i + 2 + ln]
                if mk == 0xE1 and seg[:6] == b"Exif\x00\x00":
                    info["orientation"] = _exif_orientation(seg[6:])
                if mk in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    info["height"], info["width"] = struct.unpack(">HH", seg[1:5])
                    break
                i += 2 + ln
        elif d[:4] == b"RIFF" and d[8:12] == b"WEBP":
            if d[12:16] == b"VP8X":
                info["width"] = 1 + int.from_bytes(d[24:27], "little")
                info["height"] = 1 + int.from_bytes(d[27:30], "little")
            elif d[12:16] == b"VP8L":
                b = int.from_bytes(d[21:25], "little")
                info["width"], info["height"] = (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
            elif d[12:16] == b"VP8 ":
                info["width"], info["height"] = struct.unpack("<HH", d[26:30])
                info["width"] &= 0x3FFF
                info["height"] &= 0x3FFF
        elif d[:3] == b"GIF":
            info["width"], info["height"] = struct.unpack("<HH", d[6:10])
        elif d[:2] == b"BM":
            w, h = struct.unpack("<ii", d[18:26])
            info["width"], info["height"] = w, abs(h)
    except (struct.error, IndexError):
        pass
    return info


def _exif_orientation(t: bytes) -> int:
    try:
        e = "<" if t[:2] == b"II" else ">"
        off = struct.unpack(e + "I", t[4:8])[0]
        n = struct.unpack(e + "H", t[off:off + 2])[0]
        for k in range(n):
            ent = t[off + 2 + 12 * k: off + 14 + 12 * k]
            if struct.unpack(e + "H", ent[:2])[0] == 0x0112:
                return struct.unpack(e + "H", ent[8:10])[0]
    except (struct.error, IndexError):
        pass
    return 1


def image_note(p: Path) -> str:
    """One line for the model: real size, aspect ratio and whether the photo is shown rotated."""
    i = image_info(p)
    w, h, o = i["width"], i["height"], i["orientation"]
    if not (w and h):
        return ""
    if o in (5, 6, 7, 8):
        w, h = h, w
    note = f"Image size {w}x{h} (aspect {w / h:.2f}, {'portrait' if h > w else 'landscape' if w > h else 'square'})."
    if o in (6, 8, 5, 7):
        note += (" The file's EXIF orientation says it is displayed rotated 90°, so you may see it sideways."
                 " Describe it upright.")
    elif o in (3, 4):
        note += " The file's EXIF orientation says it is displayed upside down. Describe it upright."
    return note


def _resolve_link(prompt: dict, val, depth: int = 0):
    """Follow a [node_id, slot] link in an API prompt to a literal string (primitive / string nodes)."""
    if not isinstance(val, list) or depth > 4:
        return val
    n = prompt.get(str(val[0])) or {}
    ins = n.get("inputs", {}) or {}
    if "string_a" in ins and "string_b" in ins:      # StringConcatenate and similar
        a, b = _resolve_link(prompt, ins["string_a"], depth + 1), _resolve_link(prompt, ins["string_b"], depth + 1)
        delim = ins.get("delimiter", "")
        return delim.join(x for x in (a, b) if isinstance(x, str)) if isinstance(delim, str) else None
    for k in ("text", "string", "value", "prompt", "text_a", "Text"):
        if k in n.get("inputs", {}):
            return _resolve_link(prompt, n["inputs"][k], depth + 1)
    return None


def generation_metadata(p: Path) -> dict:
    """The settings a ComfyUI PNG was made with (its embedded API prompt): models, LoRAs, prompts, sampler, size."""
    from .wfcore import _png_text_chunks
    if p.suffix.lower() != ".png":
        return {}
    try:
        prompt = json.loads(_png_text_chunks(p.read_bytes()).get("prompt") or "{}")
    except ValueError:
        return {}
    if not isinstance(prompt, dict) or not prompt:
        return {}
    out: dict = {"models": [], "loras": [], "samplers": [], "size": "", "texts": {}}
    for nid, n in prompt.items():
        if not isinstance(n, dict):
            continue
        ct, ins = n.get("class_type", ""), n.get("inputs", {}) or {}
        for k in ("ckpt_name", "unet_name", "model_name"):
            if isinstance(ins.get(k), str) and ins[k].lower().endswith((".safetensors", ".gguf", ".ckpt", ".sft")):
                out["models"].append(ins[k])
        if isinstance(ins.get("lora_name"), str):
            sm = ins.get("strength_model", ins.get("strength", 1))
            if not (isinstance(sm, (int, float)) and sm == 0):
                out["loras"].append(f"{ins['lora_name']} @ {sm}")
        if "stop_at_clip_layer" in ins:
            out["clip_skip"] = ins["stop_at_clip_layer"]
        if "CLIPTextEncode" in ct and ct not in out.setdefault("encoders", []):
            out["encoders"].append(ct)
        if all(k in ins for k in ("steps", "cfg", "sampler_name")):
            out["samplers"].append({k: ins.get(k) for k in ("steps", "cfg", "sampler_name", "scheduler", "denoise")})
            for role in ("positive", "negative"):
                link = ins.get(role)
                if isinstance(link, list):
                    src = prompt.get(str(link[0])) or {}
                    txt = _resolve_link(prompt, (src.get("inputs") or {}).get("text", (src.get("inputs") or {}).get("prompt")))
                    if isinstance(txt, str) and role not in out["texts"]:
                        out["texts"][role] = txt.strip()
        if "width" in ins and "height" in ins and "Latent" in ct and not out["size"]:
            out["size"] = f"{ins['width']}x{ins['height']}"
    if not any((out["models"], out["samplers"], out["texts"])):
        return {}
    return out


def metadata_text(meta: dict) -> str:
    if not meta:
        return ""
    lines = []
    if meta.get("models"):
        lines.append("Model: " + ", ".join(dict.fromkeys(meta["models"])))
    if meta.get("loras"):
        lines.append("LoRAs: " + ", ".join(meta["loras"]))
    for role in ("positive", "negative"):
        if meta.get("texts", {}).get(role) is not None:
            lines.append(f"{role.title()} prompt: {meta['texts'][role][:3000]}")
    for i, smp in enumerate(meta.get("samplers", [])[:3]):
        lines.append(("Sampler: " if i == 0 else "Second pass: ") + ", ".join(f"{k} {v}" for k, v in smp.items()))
    if meta.get("size"):
        lines.append("Size: " + meta["size"])
    if "clip_skip" in meta:
        lines.append(f"CLIPSetLastLayer: {meta['clip_skip']}")
    if meta.get("encoders"):
        works = any("BREAK" in e for e in meta["encoders"])
        lines.append("Text encoder: " + ", ".join(meta["encoders"])
                     + (" (BREAK splits sections here)" if works else " (BREAK is an ordinary word here, not a section split)"))
    return "\n".join(lines)


def resolve_image(path: str) -> Path:
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        raise ToolError("No image given. Upload an image first (Prompt Artist button) or give its full path.")
    p = Path(raw)
    cands = [p]
    if not p.is_absolute():
        cands.append(UPLOADS / raw)
        cfg = load_config()
        if cfg.comfy_root:
            cands += [cfg.comfy_root / "output" / raw, cfg.comfy_root / "input" / raw]
    for c in cands:
        if c.is_file():
            if c.suffix.lower() not in IMAGE_EXT:
                raise ToolError(f"'{c.name}' is not an image ({', '.join(IMAGE_EXT)}).")
            if c.stat().st_size > MAX_IMAGE_BYTES:
                raise ToolError(f"'{c.name}' is larger than {MAX_IMAGE_BYTES // 2**20} MB - save a smaller copy first.")
            return c
    raise ToolError(f"Image '{raw}' not found.")


def data_url(p: Path) -> str:
    data, mime = p.read_bytes(), IMAGE_EXT[p.suffix.lower()]
    if p.suffix.lower() == ".webp":          # llama.cpp's image loader can't read WebP
        try:
            from PIL import Image
        except ImportError as e:
            raise ToolError("WebP images can't be read by the vision model - save it as PNG or JPG and upload that.") from e
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(buf, "PNG")
        data, mime = buf.getvalue(), "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def build_messages(image: Path, notes: str = "", inv: dict | None = None, lessons_text: str | None = None) -> list[dict]:
    ask = "Analyse this image and write the best prompt to recreate it."
    note = image_note(image)
    if note:
        ask += "\n" + note
    meta = metadata_text(generation_metadata(image))
    if meta:
        ask += ("\nThis PNG has an embedded ComfyUI workflow (what was ASKED for and which model made it; the picture may "
                "differ, so prompt what it SHOWS):\n" + meta)
    if notes.strip():
        ask += "\nUser notes: " + notes.strip()
    return [{"role": "system", "content": system_prompt(inv, lessons_text)},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url(image)}},
                                         {"type": "text", "text": ask}]}]


def build_refine_messages(result: Path, reference: Path | None = None, previous: str = "", note: str = "",
                          inv: dict | None = None, lessons_text: str | None = None, history: str = "") -> list[dict]:
    """Fix mode: RESULT image (+ optional REFERENCE), the prompt/settings that were used and the user's note."""
    content: list[dict] = []
    if reference is not None:
        content += [{"type": "text", "text": "REFERENCE image (what the user wanted):"},
                    {"type": "image_url", "image_url": {"url": data_url(reference)}}]
    content += [{"type": "text", "text": "RESULT image (what the user generated):"},
                {"type": "image_url", "image_url": {"url": data_url(result)}}]
    parts = []
    meta = metadata_text(generation_metadata(result))
    if meta:
        parts.append("Settings read from the RESULT PNG's embedded ComfyUI workflow (what was actually used):\n" + meta)
    if previous.strip():
        parts.append("Prompt and settings suggested earlier in this chat:\n" + previous.strip())
    if history.strip():
        parts.append("Earlier fix attempts in this chat that did NOT solve it:\n" + history.strip())
    if not meta and not previous.strip():
        parts.append("The prompt that was used is unknown. Infer it from the image, and ask the user to paste it if "
                     "the diagnosis depends on it.")
    parts.append("User's note: " + (note.strip() or "(none) - find the defects yourself."))
    parts.append("Diagnose and fix it in the required format.")
    content.append({"type": "text", "text": "\n\n".join(parts)})
    return [{"role": "system", "content": refine_system_prompt(inv, lessons_text)}, {"role": "user", "content": content}]


def _root(base: str) -> str:
    base = base.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def can_see(base: str, timeout: float = 5) -> bool | None:
    """True/False from llama-server /props 'modalities'; None when unknown (server down or older build)."""
    try:
        j = requests.get(_root(base) + "/props", timeout=timeout).json()
    except Exception:
        return None
    mod = j.get("modalities")
    if isinstance(mod, dict) and "vision" in mod:
        return bool(mod["vision"])
    return None


def endpoints() -> list[dict]:
    """Vision endpoints to try, in order."""
    cfg = load_config()
    v, llm = cfg.get("vision") or {}, cfg["llm"]
    eps = [{"base_url": (v.get("base_url") or llm["base_url"]).rstrip("/"), "model": v.get("model") or llm.get("model") or "",
            "api_key": llm.get("api_key") or "local", "label": "main"}]
    if v.get("fallback_base_url"):
        eps.append({"base_url": v["fallback_base_url"].rstrip("/"), "model": v.get("fallback_model") or "",
                    "api_key": llm.get("api_key") or "local", "label": "fallback"})
    return eps


def pick_endpoint() -> dict:
    eps = endpoints()
    for ep in eps:
        if can_see(ep["base_url"]) is not False:   # True, or unknown -> try it
            return ep
    raise ToolError("The AI brain at " + eps[0]["base_url"] + " cannot see images (no vision projector loaded). "
                    "Close the 'AI brain' window and start it again with start-llama.bat (it loads the mmproj file), "
                    "or set vision.fallback_base_url in config.yaml.")


def request_body(ep: dict, messages: list[dict], stream: bool) -> dict:
    v = load_config().get("vision") or {}
    body = {"messages": messages, "temperature": v.get("temperature", 0.6), "max_tokens": v.get("max_tokens", 3500),
            "stream": stream}
    if ep.get("model"):
        body["model"] = ep["model"]
    if not v.get("thinking", False):
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


@tool("image_to_prompt",
      "Prompt Artist: look at an IMAGE (uploaded file or full path) and return a detailed analysis, the best model family "
      "to recreate it (Pony / Illustrious / NoobAI / Animagine / SDXL / SD1.5 / Qwen / Flux, preferring checkpoints the user has), "
      "ready-to-paste positive + negative prompts, settings and a runner-up prompt. Uses a vision model.",
      {"image": {"type": "string", "description": "image path (png/jpg/webp), e.g. the 'Image file:' path from an upload"},
       "notes": {"type": "string", "default": "", "description": "optional wishes, e.g. 'make it explicit' or 'prefer Pony'"}},
      ["image"], category="image")
def image_to_prompt(image: str, notes: str = ""):
    img = resolve_image(image)
    inv = inventory()
    ep = pick_endpoint()
    body = request_body(ep, build_messages(img, notes, inv), stream=False)
    timeout = (load_config().get("vision") or {}).get("timeout", 600)
    try:
        r = requests.post(ep["base_url"] + "/chat/completions", json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {ep['api_key']}"})
    except requests.RequestException as e:
        raise ToolError(f"Vision model not reachable at {ep['base_url']}: {e}") from e
    if r.status_code != 200:
        raise ToolError(f"Vision model HTTP {r.status_code}: {r.text[:400]}")
    msg = r.json()["choices"][0]["message"]
    return {"image": str(img), "vision_endpoint": ep["base_url"], "answer": (msg.get("content") or "").strip(),
            "installed_models": inv}
