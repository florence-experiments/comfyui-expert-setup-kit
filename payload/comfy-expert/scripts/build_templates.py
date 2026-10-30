"""Builds comfy_expert/templates/*.json from the bundled node definitions, then validates them.

Run:  python scripts/build_templates.py
Every template is made with the same edit engine the agent uses, so links/widgets are always consistent.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfy_expert.tools import wfcore  # noqa: E402

OI = json.loads((Path(__file__).resolve().parents[1] / "comfy_expert/data/object_info_bundled.json").read_text())
OUT = Path(__file__).resolve().parents[1] / "comfy_expert/templates"

NEG_REAL = ("cartoon, anime, illustration, painting, 3d render, cgi, doll, plastic skin, airbrushed, deformed, bad anatomy, "
            "extra fingers, blurry, lowres, watermark, text, jpeg artifacts")
POS_REAL = ("RAW photo of a 25 year old woman with freckles standing in a sunlit cafe, natural skin texture, detailed eyes, "
            "soft window light, 85mm lens, shallow depth of field, photorealistic")


class B:
    def __init__(self, meta):
        self.wf = {"last_node_id": 0, "last_link_id": 0, "nodes": [], "links": [], "groups": [], "config": {},
                   "extra": {"comfy_expert": meta, "ds": {"scale": 0.8, "offset": [0, 0]}}, "version": 0.4}

    def n(self, t, pos, title=None, **w):
        return wfcore.make_node(self.wf, t, OI, w or None, pos, title)["id"]

    def c(self, a, slot, b, inp):
        wfcore._add_link(self.wf, a, slot, b, inp)

    def group(self, title, x, y, w, h, color="#3f789e"):
        self.wf["groups"].append({"title": title, "bounding": [x, y, w, h], "color": color, "font_size": 24, "flags": {}})

    def note(self, text, pos):
        nid = self.wf["last_node_id"] + 1
        self.wf["nodes"].append({"id": nid, "type": "MarkdownNote", "pos": pos, "size": [440, 260], "flags": {}, "order": 0,
                                 "mode": 0, "inputs": [], "outputs": [], "properties": {}, "widgets_values": [text],
                                 "title": "Read me (ComfyUI Expert template)"})
        self.wf["last_node_id"] = nid


def sdxl_base(b, latent_from_image=False, ckpt="juggernautXL_ragnarok.safetensors"):
    ck = b.n("CheckpointLoaderSimple", [0, 200], ckpt_name=ckpt)
    pos = b.n("CLIPTextEncode", [420, 100], "Positive prompt", text=POS_REAL)
    neg = b.n("CLIPTextEncode", [420, 400], "Negative prompt", text=NEG_REAL)
    b.c(ck, 1, pos, "clip")
    b.c(ck, 1, neg, "clip")
    ks = b.n("KSampler", [880, 200], seed=123456789, control_after_generate="randomize", steps=30, cfg=4.5,
             sampler_name="dpmpp_2m_sde", scheduler="karras", denoise=1.0)
    b.c(ck, 0, ks, "model")
    b.c(pos, 0, ks, "positive")
    b.c(neg, 0, ks, "negative")
    dec = b.n("VAEDecode", [1240, 200])
    b.c(ks, 0, dec, "samples")
    b.c(ck, 2, dec, "vae")
    return ck, pos, neg, ks, dec


def t_txt2img():
    b = B({"title": "SDXL text-to-image (realistic defaults)",
           "use_for": "Any SDXL / Pony / Illustrious checkpoint. Swap ckpt_name, prompts, size and sampler settings.",
           "needs": ["checkpoints: any SDXL-family checkpoint (default: juggernautXL_ragnarok.safetensors, Civitai model 133005)"],
           "edit_hints": "node ids: 1 checkpoint, 2 positive, 3 negative, 4 KSampler, 5 VAEDecode, 6 EmptyLatentImage, 7 SaveImage. "
                         "Add a LoRA: add_node LoraLoader, connect ckpt MODEL/CLIP into it and its outputs to KSampler.model and both CLIPTextEncode.clip."})
    ck, pos, neg, ks, dec = sdxl_base(b)
    lat = b.n("EmptyLatentImage", [420, 700], width=832, height=1216, batch_size=1)
    b.c(lat, 0, ks, "latent_image")
    sv = b.n("SaveImage", [1500, 200], filename_prefix="sdxl_txt2img")
    b.c(dec, 0, sv, "images")
    b.group("Model", -20, 120, 380, 200)
    b.group("Prompts", 400, 20, 440, 620, "#8A8")
    b.note("SDXL txt2img. Realistic SDXL: CFG 3.5-6, 25-35 steps, dpmpp_2m_sde + karras, 832x1216 / 1024x1024. "
           "Pony: start prompt with score_9, score_8_up, score_7_up. Illustrious: danbooru tags, CFG 4-6.", [0, -320])
    return b.wf


def t_img2img():
    b = B({"title": "SDXL image-to-image",
           "use_for": "Restyle or refine an existing picture (e.g. anime -> realistic). denoise 0.45-0.7 keeps the composition.",
           "needs": ["checkpoints: SDXL-family checkpoint", "input image in ComfyUI/input"],
           "edit_hints": "KSampler.denoise controls how much changes (0.3 subtle, 0.55 balanced, 0.75 strong)."})
    ck, pos, neg, ks, dec = sdxl_base(b)
    b.wf["nodes"][[n["id"] for n in b.wf["nodes"]].index(ks)]["widgets_values"][-1] = 0.55
    li = b.n("LoadImage", [0, 600], image="example.png")
    sc = b.n("ImageScaleToTotalPixels", [300, 600], upscale_method="lanczos", megapixels=1.0)
    b.c(li, 0, sc, "image")
    enc = b.n("VAEEncode", [600, 650])
    b.c(sc, 0, enc, "pixels")
    b.c(ck, 2, enc, "vae")
    b.c(enc, 0, ks, "latent_image")
    sv = b.n("SaveImage", [1500, 200], filename_prefix="sdxl_img2img")
    b.c(dec, 0, sv, "images")
    b.note("img2img: the picture is scaled to ~1 megapixel (SDXL native), encoded, then partially re-noised. "
           "Lower denoise = closer to the original.", [0, -320])
    return b.wf


def t_inpaint():
    b = B({"title": "SDXL inpaint (works with normal checkpoints)",
           "use_for": "Repaint a masked area. Draw the mask in ComfyUI: right-click the Load Image node > Open in MaskEditor.",
           "needs": ["checkpoints: SDXL-family checkpoint (an *inpainting* checkpoint works even better)", "input image with mask"],
           "edit_hints": "denoise 0.6-0.9. VAEEncode + SetLatentNoiseMask keeps the unmasked area unchanged."})
    ck, pos, neg, ks, dec = sdxl_base(b)
    b.wf["nodes"][[n["id"] for n in b.wf["nodes"]].index(ks)]["widgets_values"][-1] = 0.8
    li = b.n("LoadImage", [0, 600], "Load image (paint mask in MaskEditor)", image="example.png")
    enc = b.n("VAEEncode", [420, 700])
    b.c(li, 0, enc, "pixels")
    b.c(ck, 2, enc, "vae")
    gm = b.n("GrowMask", [420, 850], expand=8, tapered_corners=True)
    b.c(li, 1, gm, "mask")
    m = b.n("SetLatentNoiseMask", [700, 750])
    b.c(enc, 0, m, "samples")
    b.c(gm, 0, m, "mask")
    b.c(m, 0, ks, "latent_image")
    sv = b.n("SaveImage", [1500, 200], filename_prefix="sdxl_inpaint")
    b.c(dec, 0, sv, "images")
    b.note("Inpaint: only the masked (grown by 8px) area is re-generated. Describe what should appear in the masked area.", [0, -320])
    return b.wf


def t_facedetailer_upscale():
    b = B({"title": "SDXL txt2img + FaceDetailer + 2x model upscale",
           "use_for": "Sharper realistic faces and a bigger final image.",
           "needs": ["custom nodes: ComfyUI-Impact-Pack + ComfyUI-Impact-Subpack (install via ComfyUI-Manager)",
                     "ultralytics/bbox/face_yolov8m.pt (https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt)",
                     "upscale_models/4x-UltraSharp.pth (https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.pth)",
                     "checkpoints: SDXL-family checkpoint"],
           "edit_hints": "FaceDetailer denoise 0.35-0.5 for realistic faces; ImageScaleBy 0.5 after a 4x model = 2x total."})
    ck, pos, neg, ks, dec = sdxl_base(b)
    lat = b.n("EmptyLatentImage", [420, 700], width=832, height=1216, batch_size=1)
    b.c(lat, 0, ks, "latent_image")
    det = b.n("UltralyticsDetectorProvider", [880, 600], model_name="bbox/face_yolov8m.pt")
    fd = b.n("FaceDetailer", [1240, 400], guide_size=512, guide_size_for=True, max_size=1024, seed=42,
             control_after_generate="randomize", steps=20, cfg=4.5, sampler_name="dpmpp_2m_sde", scheduler="karras",
             denoise=0.4, feather=5, noise_mask=True, force_inpaint=True, bbox_threshold=0.5, bbox_dilation=10,
             bbox_crop_factor=3.0, sam_detection_hint="center-1", sam_dilation=0, sam_threshold=0.93,
             sam_bbox_expansion=0, sam_mask_hint_threshold=0.7, sam_mask_hint_use_negative="False", drop_size=10,
             wildcard="", cycle=1)
    b.c(dec, 0, fd, "image")
    b.c(ck, 0, fd, "model")
    b.c(ck, 1, fd, "clip")
    b.c(ck, 2, fd, "vae")
    b.c(pos, 0, fd, "positive")
    b.c(neg, 0, fd, "negative")
    b.c(det, 0, fd, "bbox_detector")
    up = b.n("UpscaleModelLoader", [1240, 900], model_name="4x-UltraSharp.pth")
    iu = b.n("ImageUpscaleWithModel", [1640, 700])
    b.c(up, 0, iu, "upscale_model")
    b.c(fd, 0, iu, "image")
    hs = b.n("ImageScaleBy", [1960, 700], upscale_method="lanczos", scale_by=0.5)
    b.c(iu, 0, hs, "image")
    sv = b.n("SaveImage", [2260, 400], filename_prefix="sdxl_face_upscaled")
    b.c(hs, 0, sv, "images")
    pv = b.n("PreviewImage", [1640, 200], "Before FaceDetailer")
    b.c(dec, 0, pv, "images")
    b.note("FaceDetailer finds faces with YOLO, re-draws each at guide_size and pastes back. Then a 4x ESRGAN-type model "
           "upscales and ImageScaleBy 0.5 brings it to 2x. On 16 GB this is fine for SDXL.", [0, -320])
    return b.wf


def t_ipadapter():
    b = B({"title": "SDXL + IPAdapter character reference (PLUS FACE)",
           "use_for": "Keep the same face/character from a reference photo while changing scene and outfit.",
           "needs": ["custom nodes: ComfyUI_IPAdapter_plus (cubiq)",
                     "ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors (h94/IP-Adapter, sdxl_models/)",
                     "clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors (= h94/IP-Adapter models/image_encoder/model.safetensors, renamed)",
                     "checkpoints: SDXL-family checkpoint", "reference image in ComfyUI/input"],
           "edit_hints": "IPAdapter.weight 0.5-0.8 (higher = more like the reference, less prompt freedom); end_at 0.8 gives the prompt more control."})
    ck, pos, neg, ks, dec = sdxl_base(b)
    lat = b.n("EmptyLatentImage", [420, 700], width=832, height=1216, batch_size=1)
    b.c(lat, 0, ks, "latent_image")
    ul = b.n("IPAdapterUnifiedLoader", [0, 500], preset="PLUS FACE (portraits)")
    b.c(ck, 0, ul, "model")
    ref = b.n("LoadImage", [0, 700], "Reference face", image="example.png")
    ip = b.n("IPAdapter", [420, 900], weight=0.7, start_at=0.0, end_at=0.85, weight_type="standard")
    b.c(ul, 0, ip, "model")
    b.c(ul, 1, ip, "ipadapter")
    b.c(ref, 0, ip, "image")
    b.c(ip, 0, ks, "model")   # replaces the direct checkpoint -> KSampler link
    sv = b.n("SaveImage", [1500, 200], filename_prefix="sdxl_ipadapter")
    b.c(dec, 0, sv, "images")
    b.note("IPAdapter injects the reference face into the model. Use a clear, front-facing, well-lit reference crop. "
           "Unified Loader finds the right ipadapter + clip_vision files by their standard names.", [0, -320])
    return b.wf


def t_qwen_edit():
    b = B({"title": "Qwen-Image-Edit 2511 (GGUF, 4-step Lightning) - 16 GB VRAM friendly",
           "use_for": "Edit a photo with an instruction (change clothes, style, background, anime -> photo). Natural-language prompts.",
           "needs": ["custom nodes: ComfyUI-GGUF (city96)",
                     "unet/qwen-image-edit-2511-Q4_K_M.gguf (unsloth/Qwen-Image-Edit-2511-GGUF, 12.3 GB; Q3_K_M 9.2 GB if VRAM is tight)",
                     "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors (Comfy-Org/Qwen-Image_ComfyUI split_files/text_encoders, 8.7 GB)",
                     "vae/qwen_image_vae.safetensors (Comfy-Org/Qwen-Image_ComfyUI split_files/vae)",
                     "loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors (lightx2v/Qwen-Image-Edit-2511-Lightning)"],
           "edit_hints": "With the Lightning LoRA: steps 4, cfg 1. Without it (remove node, reconnect): steps 30-40, cfg 3-4. "
                         "Structure follows the official ComfyUI 2511 template (FluxKontextMultiReferenceLatentMethod index_timestep_zero)."})
    un = b.n("UnetLoaderGGUF", [0, 100], unet_name="qwen-image-edit-2511-Q4_K_M.gguf")
    ms = b.n("ModelSamplingAuraFlow", [340, 100], shift=3.1)
    b.c(un, 0, ms, "model")
    cn = b.n("CFGNorm", [640, 100], strength=1.0)
    b.c(ms, 0, cn, "model")
    lo = b.n("LoraLoaderModelOnly", [940, 100], lora_name="Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", strength_model=1.0)
    b.c(cn, 0, lo, "model")
    cl = b.n("CLIPLoader", [0, 300], clip_name="qwen_2.5_vl_7b_fp8_scaled.safetensors", type="qwen_image")
    va = b.n("VAELoader", [0, 450], vae_name="qwen_image_vae.safetensors")
    li = b.n("LoadImage", [0, 600], "Image to edit", image="example.png")
    sc = b.n("FluxKontextImageScale", [340, 650])
    b.c(li, 0, sc, "image")
    pos = b.n("TextEncodeQwenImageEditPlus", [640, 300], "Edit instruction (positive)",
              prompt="Turn this into a realistic photograph of a real adult woman, natural skin texture, real fabric, soft daylight. Keep pose, outfit and composition.")
    neg = b.n("TextEncodeQwenImageEditPlus", [640, 600], "Negative (leave empty)", prompt="")
    for t in (pos, neg):
        b.c(cl, 0, t, "clip")
        b.c(va, 0, t, "vae")
        b.c(sc, 0, t, "image1")
    rp = b.n("FluxKontextMultiReferenceLatentMethod", [1000, 300], reference_latents_method="index_timestep_zero")
    rn = b.n("FluxKontextMultiReferenceLatentMethod", [1000, 600], reference_latents_method="index_timestep_zero")
    b.c(pos, 0, rp, "conditioning")
    b.c(neg, 0, rn, "conditioning")
    enc = b.n("VAEEncode", [640, 850])
    b.c(sc, 0, enc, "pixels")
    b.c(va, 0, enc, "vae")
    ks = b.n("KSampler", [1300, 250], seed=42, control_after_generate="randomize", steps=4, cfg=1.0,
             sampler_name="euler", scheduler="simple", denoise=1.0)
    b.c(lo, 0, ks, "model")
    b.c(rp, 0, ks, "positive")
    b.c(rn, 0, ks, "negative")
    b.c(enc, 0, ks, "latent_image")
    dec = b.n("VAEDecode", [1650, 250])
    b.c(ks, 0, dec, "samples")
    b.c(va, 0, dec, "vae")
    sv = b.n("SaveImage", [1900, 250], filename_prefix="qwen_edit_2511")
    b.c(dec, 0, sv, "images")
    b.note("Qwen-Image-Edit 2511 GGUF. 16 GB VRAM: Q4_K_M or Q3_K_M unet; the 8.7 GB text encoder is offloaded to RAM after encoding. "
           "Prompts are plain English instructions. Add image2/image3 for multi-reference edits.", [0, -320])
    return b.wf


# Verified download links (checked with hf_list_files / civitai_get_model when the templates were built).
# Stored the same way official ComfyUI templates do it (node.properties.models), so ComfyUI's
# "missing models" dialog can offer the downloads too.
MODEL_LINKS = {
    "juggernautXL_ragnarok.safetensors": ("https://civitai.com/api/download/models/1759168", "checkpoints"),
    "bbox/face_yolov8m.pt": ("https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt", "ultralytics/bbox"),
    "4x-UltraSharp.pth": ("https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.pth", "upscale_models"),
    "qwen-image-edit-2511-Q4_K_M.gguf": ("https://huggingface.co/unsloth/Qwen-Image-Edit-2511-GGUF/resolve/main/qwen-image-edit-2511-Q4_K_M.gguf", "unet"),
    "qwen_2.5_vl_7b_fp8_scaled.safetensors": ("https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", "text_encoders"),
    "qwen_image_vae.safetensors": ("https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors", "vae"),
    "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors": ("https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", "loras"),
}


def attach_links(wf):
    for n in wf["nodes"]:
        for v in n.get("widgets_values") or []:
            if isinstance(v, str) and v in MODEL_LINKS:
                url, d = MODEL_LINKS[v]
                n.setdefault("properties", {}).setdefault("models", []).append(
                    {"name": v.rsplit("/", 1)[-1], "url": url, "directory": d})


TEMPLATES = {"sdxl_txt2img": t_txt2img, "sdxl_img2img": t_img2img, "sdxl_inpaint": t_inpaint,
             "sdxl_facedetailer_upscale": t_facedetailer_upscale, "sdxl_ipadapter_character": t_ipadapter,
             "qwen_image_edit_2511_gguf": t_qwen_edit}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for name, fn in TEMPLATES.items():
        wf = fn()
        attach_links(wf)
        v = wfcore.validate(wf, OI, "bundled")
        errs = [i for i in v["issues"] if i["level"] == "error"]
        warns = [i for i in v["issues"] if i["level"] == "warn"]
        api = wfcore.ui_to_api(wf, OI)
        va = wfcore.validate(api, OI, "bundled")
        api_errs = [i for i in va["issues"] if i["level"] == "error"]
        print(f"{name}: nodes={len(wf['nodes'])} errors={len(errs)} warns={len(warns)} api_errors={len(api_errs)} "
              f"models_to_download={[m['file'] for m in v['missing_models']]}")
        for e in errs + warns + api_errs:
            print("   ", e)
        bad += len(errs) + len(api_errs)
        (OUT / f"{name}.json").write_text(json.dumps(wf, indent=1), encoding="utf-8")
    sys.exit(1 if bad else 0)
