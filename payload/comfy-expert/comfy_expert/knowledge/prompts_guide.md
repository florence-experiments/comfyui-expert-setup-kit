# Prompting by family

- **SD1.5 / SDXL realistic**: natural sentence + comma details. Subject, clothing, pose, setting, light, camera. Weighting `(word:1.2)` works in CLIPTextEncode. Keep under ~75-150 tokens per idea; long prompts get diluted.
- **Pony**: `score_9, score_8_up, score_7_up, source_real|source_anime, rating_*,` then tags. Negative `score_4, score_5, score_6`.
- **Illustrious / NoobAI**: Danbooru tags, quality tags at the front (`masterpiece, best quality, amazing quality, very aesthetic, absurdres`), negative `worst quality, low quality, bad anatomy, ...`. Some NoobAI need `newest` / year tags.
- **Flux.1 / Chroma / Qwen-Image / Z-Image**: plain descriptive English, full sentences, put the main subject first; text in "quotes" renders as text. Flux ignores negatives at cfg 1.
- **Qwen-Image-Edit / Flux Kontext**: an instruction: "Change X to Y, keep the face, pose and background the same." Name what must stay.
- **Wan video**: describe subject + motion + camera ("slow dolly in", "handheld"), 1-3 sentences. Negative prompts help at cfg > 1.

## Adult content policy for this helper
NSFW is allowed (user's own hobby) but every character must be an adult. Always state adult ages in prompts for realistic people. Never write or keep prompts sexualising minors or child-like characters; rewrite them as adults or refuse.

## Useful realism words
skin texture, pores, subsurface scattering, natural light, soft shadows, golden hour, overcast, rim light, 35mm / 50mm / 85mm, f/1.8 bokeh, film grain, Kodak Portra 400, candid, DSLR, editorial photo, color graded.
