# Fixing a bad generation (symptom -> cause -> fix)
Use this when the user shows a result that went wrong. Compare it with the reference or the user's intent, name each defect, its most likely cause, and the smallest fix. Change one or two things at a time so it is clear what worked.

| Symptom | Likely cause | Fix |
|---|---|---|
| Wrong hair/eye/clothing colour, colour bleeding onto other items | colour tag weak, too far back, or colours bleed between nearby tags | move the tag forward, weight it `(red eyes:1.2)`, separate the colours, add the wrong colour to the negative |
| With 2+ people: hair/eye colours or outfits swapped or blended between people | all people in one tag run, so the text encoder mixes them | rewrite as BREAK sections (shared section, then `BREAK` + one section per person with clearly different colours) and run it in H1 06; or use H1 02 (one box per person) |
| BREAK did nothing, or the word BREAK seems to be drawn/ignored | prompt pasted into H1 01-05 or a plain `CLIPTextEncode`, where BREAK is an ordinary word; or written as `break` (lower case) | paste it into H1 06 (ComfyUI-ppm `CLIPTextEncodeBREAK`), keep BREAK in capitals; in H1 01-05 delete the BREAK lines |
| Feature missing (accessory, tail, prop) | tag missing, wrong Danbooru name, or buried late in a long prompt | use the exact Danbooru tag, move it forward, weight 1.1-1.3 |
| Wrong character look | missing series tag, unescaped brackets, character unknown to the model | `name \(series\)` plus the series tag; describe the appearance tags; use a character LoRA; Illustrious/NoobAI know more characters than Pony |
| Style not matching (too generic) | WAI/Pony default style dominates; artist tag at the end; quality tags at the front (Animagine) | artist tag right after the character; lower CFG (5); style LoRA; Illustrious base + artist |
| Blurry, washed-out, low detail | too many quality tags or a long negative (WAI); CFG too low; resolution too small | trim the quality/negative tags to the family's defaults; CFG +1; use a proper bucket plus hires fix 1.5x at denoise 0.35-0.5 |
| Oversaturated / burnt / harsh contrast | CFG too high; v-pred run with eps settings; too many weights above 1.3 | lower CFG (WAI 5, Pony 6, NoobAI-vpred 4); `RescaleCFG` 0.7; `ModelSamplingDiscrete` v_prediction for vpred; reduce weights |
| Grey, foggy or noisy image on NoobAI vpred | missing v_prediction sampling | `ModelSamplingDiscrete` v_prediction (+ zsnr if the creator says so), euler not ancestral |
| "Blobs", melted mess on Pony | clip skip 1 | `CLIPSetLastLayer` -2 |
| Pony looks low quality | score chain shortened to `score_9` | use the full chain `score_9, score_8_up, ... score_4_up` |
| Bad hands/fingers | SDXL weakness, small hands in frame, low resolution | hires fix or a face/hand detailer (Impact Pack FaceDetailer with a hand_yolov8 detector), inpaint the hand at 0.4-0.5 denoise, `bad hands, extra digits, fewer digits` in the negative (Illustrious/Animagine), a pose that hides the hands |
| Bad small face / eyes in a wide shot | face too small for the latent | FaceDetailer (Impact Pack) or hires fix 1.5-2x; `detailed eyes` |
| Duplicate people, stretched bodies | resolution too far from the model's native size (SD 1.5 above 768, SDXL above 1.5 MP) | use a native bucket, then upscale |
| Extra people when one was wanted | missing `solo`, or plural tags | add `1girl, solo`; `multiple girls, 2girls` in the negative |
| Wrong framing / camera | conflicting composition tags, or none | exactly one framing tag (cowboy shot / full body / upper body / portrait) plus one angle (from below / from above / dutch angle) |
| Unwanted text, signature, watermark | Pony pseudo-signatures; text in the data | `signature, watermark, artist name, text` in the negative; inpaint it out |
| Censor bars / mosaic | `censored` training data | `censored, mosaic censoring, bar censor` in the negative; add `uncensored` |
| Character looks younger than intended | anime style defaults | `adult, mature female`, `(aged up:1.2)` (WAI), taller/curvier body tags |
| Too realistic / 3D-looking anime | 2.5D merge or realism tags | `3d, realistic` in the negative; `anime coloring, flat color` |
| LoRA overpowering or broken | LoRA strength too high, wrong family | strength 0.6-0.8; check that the LoRA's base model matches the checkpoint |
| Prompt ignored when it's long | SD 1.5 77-token chunks; key tags too late | put key tags first and trim filler; in H1 06 split it into BREAK sections so each person/topic gets its own chunk |
| Pose impossible to get | the model can't follow complex poses | ControlNet OpenPose/depth from the reference, or Qwen-Image-Edit with the reference |

## When prompt fixes are not enough
- Local defects (a hand, a face, an object): inpaint with the same checkpoint (`SetLatentNoiseMask` or `InpaintModelConditioning`, denoise 0.4-0.6), or a detailer pass (Impact Pack FaceDetailer + Ultralytics bbox detector).
- Composition and pose: ControlNet (OpenPose, depth, lineart) or IPAdapter for the style.
- Wrong family for the job: switch (see prompt_family_decision).
