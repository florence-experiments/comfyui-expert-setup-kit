"""Prompt Artist: image -> prompt, fix mode and the lessons store (no real model needed)."""
import json
import struct
import zlib

import pytest

from comfy_expert.agent import Agent, Session, route, _pa_family, _pa_prompt_section
from comfy_expert.tools import imageprompt, lessons, run_tool


def png_bytes(w=832, h=1216, text: dict | None = None) -> bytes:
    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    for k, v in (text or {}).items():
        out += chunk(b"tEXt", k.encode() + b"\x00" + v.encode())
    return out + chunk(b"IDAT", zlib.compress(b"\x00" * 10)) + chunk(b"IEND", b"")


def jpeg_rotated(w=4000, h=3000, orientation=6) -> bytes:
    tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0) + b"\x00" * 4
    app1 = b"Exif\x00\x00" + tiff
    sof = b"\x08" + struct.pack(">HH", h, w) + b"\x03" + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
            + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9")


COMFY_PROMPT = {
    "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "waiIllustriousSDXL_v170.safetensors"}},
    "4": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "masterpiece, best quality"}},
    "5": {"class_type": "StringConcatenate", "inputs": {"string_a": ["4", 0], "string_b": "octopus, reddish brown", "delimiter": ", "}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["5", 0], "clip": ["2", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad quality, blue", "clip": ["2", 1]}},
    "8": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "9": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["6", 0], "negative": ["7", 0], "seed": 1,
                                                "steps": 28, "cfg": 4.5, "sampler_name": "euler_ancestral",
                                                "scheduler": "normal", "denoise": 1.0, "latent_image": ["8", 0]}},
}

ANALYSIS = """### 1. Image analysis
- **Subject**: 1girl
### 2. Best model for this image
1. Illustrious - WAI
### 3. Prompt for Illustrious-XL (`waiIllustriousSDXL_v170.safetensors`)
**Positive**
```text
1girl, silver hair, masterpiece, best quality, amazing quality
```
**Negative**
```text
bad quality, worst quality
```
### 4. Runner-up: Pony
```text
score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up, source_anime, 1girl
```
"""

FIX = """### 1. What went wrong
| Defect | Root cause | Fix |
|---|---|---|
| hair is blue | colour tag too late | move it forward |
### 2. Corrected prompt (Illustrious-XL, `waiIllustriousSDXL_v170.safetensors`)
```text
1girl, (silver hair:1.2), masterpiece, best quality, amazing quality
```
### 3. Changelog
- ~ moved silver hair forward and weighted it
### Lessons
```lessons
[{"family": "Illustrious-XL", "checkpoint": "waiIllustriousSDXL_v170.safetensors", "symptom": "hair colour came out wrong", "cause": "colour tag placed late with no weight", "fix": "put the hair colour right after 1girl and weight it 1.2"}]
```"""


@pytest.fixture
def pa(offline_cfg, monkeypatch, tmp_path):
    lf = tmp_path / "lessons.json"
    monkeypatch.setattr(lessons, "path", lambda: lf)
    monkeypatch.setattr(imageprompt, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(imageprompt, "pick_endpoint", lambda: {"base_url": "http://vision.test/v1", "model": "vis",
                                                               "api_key": "local", "label": "main"})
    m = offline_cfg["models"]
    for f in ("checkpoints/waiIllustriousSDXL_v170.safetensors", "checkpoints/ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
              "checkpoints/Realistic_Vision_V5.1_fp16-no-ema.safetensors", "loras/Ultros_-_Final_Fantasy_IllustriousXL-000018.safetensors"):
        (m / f).write_bytes(b"x")
    ref = tmp_path / "ref.png"
    ref.write_bytes(png_bytes())
    res = tmp_path / "result.png"
    res.write_bytes(png_bytes(1024, 1024, {"prompt": json.dumps(COMFY_PROMPT)}))
    return {"ref": ref, "res": res, "lessons": lf}


class VisionAgent(Agent):
    def __init__(self, replies):
        super().__init__()
        self.replies, self.sent = list(replies), []

    def _vision_stream(self, ep, messages, turn=None):
        self.sent.append(messages)
        text = self.replies.pop(0)
        for i in range(0, len(text), 40):
            yield {"delta": text[i:i + 40]}
        yield {"message": {"role": "assistant", "content": text}}

    def _complete(self, messages, use_tools=True, body=None, base=None, turn=None):
        raise AssertionError("the main model must not be called")


def images_in(msgs):
    return [c for c in msgs[1]["content"] if c.get("type") == "image_url"]


@pytest.mark.parametrize("name,fam", [
    ("waiIllustriousSDXL_v170.safetensors", "Illustrious-XL"), ("Illustrious-XL-v0.1.safetensors", "Illustrious-XL"),
    ("ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "Pony (SDXL)"), ("noobaiXLNAIXL_vPred10Version.safetensors", "NoobAI-XL"),
    ("Realistic_Vision_V5.1_fp16-no-ema.safetensors", "SD 1.5"), ("Qwen-Rapid-NSFW-v23_Q4_K.gguf", "Qwen-Image-Edit"),
    ("qwen-image-edit-2511-Q4_K_M.gguf", "Qwen-Image-Edit"), ("flux1-dev-fp8.safetensors", "Flux"),
    ("animagine-xl-4.0.safetensors", "Animagine XL"), ("juggernautXL_ragnarok.safetensors", "SDXL"),
    ("Ultros_-_Final_Fantasy_IllustriousXL-000018.safetensors", "Illustrious-XL"), ("H1_manga_style.safetensors", "unknown family"),
])
def test_classify(name, fam):
    assert imageprompt.classify(name) == fam


def test_route_and_prompts(pa):
    assert route("Prompt Artist: analyse this image") == "image_to_prompt"
    inv = imageprompt.inventory()
    assert "waiIllustriousSDXL_v170.safetensors" in inv["checkpoints"]["Illustrious-XL"]
    for sp in (imageprompt.system_prompt(inv, "LESSON-X"), imageprompt.refine_system_prompt(inv, "LESSON-X")):
        assert "{{" not in sp and "LESSON-X" in sp and "ponyDiffusionV6XL" in sp and "score_9, score_8_up" in sp
    assert "Root cause" in imageprompt.refine_system_prompt(inv) and "FaceDetailer" in imageprompt.refine_system_prompt(inv)


def test_image_facts(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(jpeg_rotated())
    assert imageprompt.image_info(p) == {"width": 4000, "height": 3000, "orientation": 6}
    note = imageprompt.image_note(p)
    assert "3000x4000" in note and "rotated" in note
    q = tmp_path / "b.png"
    q.write_bytes(png_bytes(832, 1216))
    assert "832x1216" in imageprompt.image_note(q) and "portrait" in imageprompt.image_note(q)


def test_generation_metadata_follows_links(pa):
    meta = imageprompt.generation_metadata(pa["res"])
    assert meta["models"] == ["waiIllustriousSDXL_v170.safetensors"]
    assert meta["texts"]["positive"] == "masterpiece, best quality, octopus, reddish brown"
    assert meta["texts"]["negative"] == "bad quality, blue" and meta["size"] == "1024x1024"
    assert imageprompt.generation_metadata(pa["ref"]) == {}
    ask = imageprompt.build_messages(pa["res"], "", None, "")[1]["content"][1]["text"]
    assert "embedded ComfyUI workflow" in ask and "octopus, reddish brown" in ask
    assert "embedded" not in imageprompt.build_messages(pa["ref"], "", None, "")[1]["content"][1]["text"]


def test_answer_parsing():
    assert _pa_family(ANALYSIS) == ("Illustrious-XL", "waiIllustriousSDXL_v170.safetensors")
    assert _pa_family(FIX) == ("Illustrious-XL", "waiIllustriousSDXL_v170.safetensors")
    sec = _pa_prompt_section(ANALYSIS)
    assert "silver hair" in sec and "Runner-up" not in sec
    body, found = lessons.parse_block(FIX)
    assert "```lessons" not in body and "### Lessons" not in body and found[0]["symptom"] == "hair colour came out wrong"
    assert lessons.parse_block("text\n```lessons\n[{\"symptom\": \"a\", \"fix\": \"b\"}, {broken\n```")[1] == [{"symptom": "a", "fix": "b"}]


def test_analyse_then_fix_then_confirm_and_reuse(pa):
    a = VisionAgent([ANALYSIS, FIX])
    s = Session()
    evs = list(a.chat(s, f"Prompt Artist: analyse this image and write the best prompt to recreate it.\nImage file: {pa['ref']}"))
    fin = evs[-1]
    assert fin["type"] == "final" and fin["pa"]["mode"] == "analyse" and "silver hair" in fin["text"]
    assert len(images_in(a.sent[0])) == 1 and "832x1216" in json.dumps(a.sent[0][1])
    assert s.pa["reference"] == str(pa["ref"]) and s.pa["checkpoint"] == "waiIllustriousSDXL_v170.safetensors"

    evs = list(a.chat(s, f"Prompt Artist fix: here is the image I generated. What went wrong and how do I fix the prompt?\n"
                         f"Note: hair should be silver\nImage file: {pa['res']}"))
    fin = evs[-1]
    sent = json.dumps(a.sent[1][1])
    assert len(images_in(a.sent[1])) == 2                          # reference + result
    assert "octopus, reddish brown" in sent and "silver hair, masterpiece" in sent and "hair should be silver" in sent
    assert "Root cause" in a.sent[1][0]["content"]
    assert fin["pa"]["mode"] == "fix" and len(fin["pa"]["lessons"]) == 1
    assert "```lessons" not in fin["text"] and "tentative lesson" in fin["text"]
    assert not any("```lessons" in e.get("text", "") for e in evs if e["type"] == "delta")
    saved = json.loads(pa["lessons"].read_text())["lessons"]
    assert saved[0]["status"] == "tentative" and saved[0]["checkpoints"] == ["waiIllustriousSDXL_v170.safetensors"]

    evs = list(a.chat(s, "That fixed it."))                       # no model call (replies list is empty)
    assert "confirmed" in evs[-1]["text"]
    assert json.loads(pa["lessons"].read_text())["lessons"][0]["status"] == "confirmed"

    b = VisionAgent([ANALYSIS])                                     # a brand-new chat sees the lesson
    list(b.chat(Session(), f"Prompt Artist: analyse this image\nImage file: {pa['ref']}"))
    assert "confirmed x1" in b.sent[0][0]["content"] and "hair colour came out wrong" in b.sent[0][0]["content"]


def test_still_wrong_marks_failed_and_retries(pa):
    a = VisionAgent([ANALYSIS, FIX, FIX.replace("hair colour came out wrong", "hair colour still wrong after weighting")])
    s = Session()
    list(a.chat(s, f"Prompt Artist: analyse\nImage file: {pa['ref']}"))
    list(a.chat(s, f"Prompt Artist fix: what went wrong?\nImage file: {pa['res']}"))
    evs = list(a.chat(s, "Still wrong."))
    assert "won't suggest them again" in evs[-1]["text"]
    assert json.loads(pa["lessons"].read_text())["lessons"][0]["status"] == "failed"
    assert lessons.relevant("Illustrious") == []
    list(a.chat(s, f"Prompt Artist fix: still wrong\nImage file: {pa['res']}"))
    assert "did NOT solve it" in json.dumps(a.sent[2][1])


def test_fix_without_reference_uses_png_metadata(pa):
    a = VisionAgent([FIX])
    s = Session()
    evs = list(a.chat(s, f"Prompt Artist fix: it came out blue\nImage file: {pa['res']}"))
    assert evs[-1]["pa"]["mode"] == "fix" and len(images_in(a.sent[0])) == 1
    assert "embedded ComfyUI workflow" in json.dumps(a.sent[0][1])


def test_lessons_store_dedupe_cap_order(pa, monkeypatch):
    l1 = lessons.add({"family": "WAI-illustrious", "symptom": "hands have extra fingers", "cause": "small hands",
                      "fix": "FaceDetailer hand pass at denoise 0.4"})
    l2 = lessons.add({"family": "Illustrious-XL", "symptom": "extra fingers on the hands", "cause": "hands too small",
                      "fix": "hand detailer pass denoise 0.4"})
    assert l1["id"] == l2["id"] and l2["seen"] == 2 and l1["family"] == "Illustrious-XL"
    p = lessons.add({"family": "Pony", "symptom": "melted blobs", "cause": "clip skip 1", "fix": "CLIPSetLastLayer -2"})
    lessons.confirm([p["id"]])
    assert [l["id"] for l in lessons.relevant()][:2] == [p["id"], l1["id"]]       # confirmed first
    assert [l["id"] for l in lessons.relevant("ponyDiffusionV6XL_v6StartWithThisOne.safetensors")] == [p["id"]]
    assert lessons.add({"family": "Pony", "symptom": "", "fix": ""}) is None
    monkeypatch.setattr(lessons, "CAP", 3)
    for i in range(5):
        lessons.add({"family": "SDXL", "symptom": f"unique problem {i} zz{i}", "cause": f"c{i}", "fix": f"different fix {i} yy{i}"})
    items = lessons.load()
    assert len(items) == 3 and items[0]["id"] == p["id"]
    r = run_tool("prompt_lessons", {"family": "pony"})
    assert r["lessons"][0]["status"] == "confirmed"


def test_lessons_file_broken_does_not_break(pa):
    pa["lessons"].write_text("{not json")
    assert lessons.load() == [] and "(none yet)" in imageprompt.system_prompt()


def test_fixed_reply_without_pending_goes_to_model(pa):
    class Scripted(VisionAgent):
        def _complete(self, messages, use_tools=True, body=None, base=None, turn=None):
            yield {"message": {"role": "assistant", "content": "ok"}}
    a = Scripted([])
    evs = list(a.chat(Session(), "perfect, thanks"))
    assert evs[-1]["type"] == "final" and "pa" not in evs[-1]


def test_upload_accepts_images(pa, monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from comfy_expert.web import server
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "up")
    c = TestClient(server.create_app())
    r = c.post("/api/upload", files={"file": ("x.jpg", jpeg_rotated(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["kind"] == "image"
    wf = png_bytes(text={"workflow": "{}", "prompt": "{}"})
    assert c.post("/api/upload", files={"file": ("y.png", wf, "image/png")}).json()["kind"] == "image+workflow"
    assert c.post("/api/upload", files={"file": ("z.exe", b"x", "application/octet-stream")}).status_code == 400


def test_break_sections_and_h1_06_guidance(pa):
    inv = imageprompt.inventory()
    sp, rp = imageprompt.system_prompt(inv, ""), imageprompt.refine_system_prompt(inv, "")
    for text in (sp, rp, imageprompt.family_conventions()):
        assert "BREAK" in text and "H1 06" in text and "CLIPTextEncodeBREAK" in text
    assert "not in core ComfyUI" not in sp                              # the old "leave BREAK out" advice is gone
    assert "\nBREAK\n" in sp and "on its own line" in sp and "ordinary word" in sp
    assert "H1 01" in sp and "H1 02" in sp and "ponyDiffusionV6XL_v6StartWithThisOne" in sp
    assert "every character is an adult" in sp and "All characters are adults" in rp   # adult-only rules kept
    assert "quality tags go at the END" in sp                           # Illustrious/WAI rule kept
    kdir = imageprompt.PKG_DIR / "knowledge"
    for name in ("image_model_families.md", "danbooru_tagging.md", "prompt_family_decision.md",
                 "prompt_fixing.md", "playbooks/image_to_prompt.md"):
        t = (kdir / name).read_text(encoding="utf-8")
        assert "BREAK" in t and "H1 06" in t and "ordinary word" in t, name
    assert "leave it out" not in (kdir / "image_model_families.md").read_text(encoding="utf-8")


def test_metadata_encoders_from_png(pa, tmp_path):
    assert imageprompt.generation_metadata(pa["res"])["encoders"] == ["CLIPTextEncode"]
    brk = {**COMFY_PROMPT, "6": {"class_type": "CLIPTextEncodeBREAK", "inputs": {"text": "2girls\nBREAK\ngirl on left", "clip": ["2", 1]}},
           "7": {"class_type": "CLIPTextEncodeBREAK", "inputs": {"text": "bad quality", "clip": ["2", 1]}}}
    p = tmp_path / "break.png"
    p.write_bytes(png_bytes(1024, 1024, {"prompt": json.dumps(brk)}))
    meta = imageprompt.generation_metadata(p)
    assert meta["encoders"] == ["CLIPTextEncodeBREAK"] and meta["texts"]["positive"] == "2girls\nBREAK\ngirl on left"
    assert "BREAK splits sections" in imageprompt.metadata_text(meta)
    assert "ordinary word" in imageprompt.metadata_text(imageprompt.generation_metadata(pa["res"]))
