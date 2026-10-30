# Turning an anime / illustrated workflow into a realistic one

All characters must be clearly adult (18+). If the source workflow or prompt suggests a minor (child, loli, shota, "young-looking", school-age cues), describe them as adults instead or refuse that part.

## 1. Find what makes it anime
summarize_workflow shows `anime_style_signals`, checkpoints, LoRAs and prompts. Typical anime parts:
- Checkpoint family Illustrious / NoobAI / Pony / Animagine / anime SD1.5 models (AnythingV5, Counterfeit, MeinaMix...).
- LoRAs for anime styles, "flat color", "cel shading", artists, line art.
- Prompt tags: `anime, manga, illustration, 2d, cel shading, flat color, lineart, chibi, masterpiece, best quality, 1girl, solo`, Danbooru-style tags, Pony `source_anime`.
- Settings: clip skip 2, high CFG 7+, euler_ancestral.

## 2. Pick the route (ask the user if unclear)
**A. Keep the same graph, swap to a realistic model of the same family** (least work):
- Pony graph -> a realistic Pony merge (Civitai baseModel "Pony", search "realistic") so Pony LoRAs keep working. Keep score tags, swap `source_anime` -> `source_real` / `photo`.
- Illustrious graph -> a realistic/semi-real Illustrious merge (baseModel "Illustrious", search "realistic"), or move to SDXL realistic (route B).
- SD1.5 anime -> SD1.5 realistic (Realistic Vision, epiCRealism, CyberRealistic) - but SDXL is better.
**B. Switch to an SDXL photoreal checkpoint** (best general option on 16 GB): swap ckpt, remove/replace anime LoRAs, rewrite prompts, adjust sampler (see below).
**C. Modern realistic models**: Flux.1 dev fine-tunes, Chroma, Qwen-Image, Z-Image Turbo, Wan 2.2 as image model. Needs a different graph - use list_official_templates + build from template, then move prompts/size over.
**D. Convert existing anime pictures to photos**: Qwen-Image-Edit (template `qwen_image_edit_2511_gguf`, or official `templates-image_to_real` with the Qwen-Image-Edit-2509 Anything2RealAlpha LoRA), or SDXL img2img denoise 0.55-0.7 + ControlNet depth/lineart/pose to keep the composition.

## 3. Changes for realism (SDXL route)
- **Checkpoint**: verified realistic SDXL checkpoint (civitai_search_models types=["Checkpoint"], base_models=["SDXL 1.0"], query "realistic"/"photo", sort "Most Downloaded"). Prefer models with many downloads and recent versions; read the model's recommended settings.
- **LoRAs**: remove anime style LoRAs. Character LoRAs trained on anime often pull back to anime - lower to 0.4-0.6 or replace with a realistic version of that character if one exists. Add optional realism helpers (skin detail / "add detail" / photo style LoRAs for SDXL) - verify each on Civitai.
- **Clip skip**: remove `CLIPSetLastLayer -2` (realistic SDXL models usually use the default -1) unless the model page says otherwise.
- **Sampler**: CFG 3.5-5.5, 25-35 steps, dpmpp_2m_sde karras (or the page's value). Lower CFG = more natural skin.
- **Resolution**: 832x1216 / 896x1152 portrait, 1024x1024 square.
- **Add FaceDetailer** (denoise 0.35-0.45) and an upscale stage - realistic faces at full-body distance need it.
- **Optional**: IPAdapter PLUS FACE with a reference photo for a consistent person.

## 4. Prompt rewrite (keep the content, change the medium)
- Remove: `anime, manga, illustration, 2d, cel shading, flat colors, lineart, masterpiece, best quality, absurdres, highres` style tags, artist tags, Danbooru counts like `1girl` (can keep as "a woman").
- Convert tags to natural description: `1girl, long silver hair, red eyes, school uniform` -> "photo of a 25-year-old woman with long silver hair and red contact lenses, wearing a navy blazer outfit".
- Add camera/photo language: "RAW photo, 85mm lens, f/1.8, natural window light, skin pores, film grain, candid".
- Make age explicit and adult: "a 25 year old woman", "an adult man in his 30s".
- Unrealistic anime features: huge eyes, impossible hair colours/proportions -> tone down ("vivid dyed hair", "cosplay wig" if the look must stay).
- Negative (SDXL): `anime, cartoon, illustration, painting, drawing, 3d render, cgi, doll, plastic skin, airbrushed, oversaturated, deformed, bad anatomy, extra fingers, lowres, watermark, text`.
- Pony realistic merges: keep `score_9, score_8_up, score_7_up`, add `source_real, photo`, negative `score_4, score_5, source_anime, source_cartoon`.

## 5. Checklist before saving
- [ ] Every new node type checked with comfy_node_info. Every model file looked up (Civitai / HF) with real filename, size and target folder.
- [ ] validate_workflow on the draft: no errors. Missing models are listed for download.
- [ ] Saved as a NEW file (write_workflow), original untouched.
