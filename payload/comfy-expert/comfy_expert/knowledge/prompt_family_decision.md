# Choosing a model family from an image (decision guide)
Use this guide to pick the family that will reproduce a reference image best, preferring checkpoints the user owns. Owned on this PC (October 2026): Pony V6 XL, Illustrious-XL v0.1, WAI-illustrious v17, Realistic Vision 5.1 (SD 1.5), Qwen-Image-Edit 2511 GGUF, Qwen Rapid AIO NSFW v23 GGUF. Always re-check with list_local_models.

| Image traits | First choice | Runner-up |
|---|---|---|
| Modern anime / gacha / light-novel art, a known anime or game character | WAI-illustrious (Illustrious) | Pony V6 (`source_anime`) |
| Specific Danbooru artist style | Illustrious / NoobAI (artist tags work) | WAI with a lower CFG plus the artist tag |
| Western cartoon / comic / Disney-like | Pony (`source_cartoon`) | Illustrious |
| Furry / anthro / feral / pony | Pony (`source_furry`/`source_pony`) | NoobAI (e621 data, not installed) |
| Explicit sex scene, anime | WAI/Illustrious (`explicit`) or Pony (`rating_explicit`); Pony is steadier on complex explicit poses | the other one |
| Semi-real / 2.5D / painterly CG | Illustrious/WAI + `realistic, 3d` tags, or Pony Realism (not installed) | Qwen-Image-Edit from the reference |
| Photo of a real-looking person | Realistic Vision 5.1 (SD 1.5, low VRAM) or Qwen Rapid AIO (better prompt following) | SDXL realistic / Flux (not installed) |
| Anime → realistic version of the same picture | Qwen-Image-Edit 2511 / Rapid AIO with the reference image | Illustrious → img2img with a realistic checkpoint |
| Image with readable text / signs / logos | Qwen (renders text) | Flux (not installed) |
| Monochrome manga / lineart / sketch | Illustrious/WAI + `monochrome, greyscale, lineart, manga` | Pony |
| Pixel art / chibi / very stylised | Illustrious + style tags (check LoRAs) | Pony |
| Multiple characters doing different things | Illustrious/WAI with BREAK sections (one per person) in H1 06, or Qwen (sentences) | Pony with BREAK sections in H1 06, or H1 02 (regional, one box per person) |
| Characters from 2024 onwards | a character LoRA on Illustrious; otherwise describe the appearance tag by tag | Qwen-Image-Edit with the reference |

2+ people with a tag-based family (Pony, Illustrious/WAI, NoobAI, Animagine, SD 1.5): write the positive as a shared section, then `BREAK` on its own line before each person's section (see danbooru_tagging). BREAK only works in H1 06 (ComfyUI-ppm `CLIPTextEncodeBREAK`); in H1 01-05 it is an ordinary word.

Workflow to paste into: **H1 06 - Prompt Artist (paste prompt, BREAK works)** by default (Illustrious/WAI as is; Pony after switching its checkpoint to `ponyDiffusionV6XL_v6StartWithThisOne` and the anatomy LoRA to 0). **H1 01** for one reusable character (content tags only; it adds its own quality tags). **H1 02** for 2-3 people (one tag line per person in its LEFT / RIGHT / CENTRE boxes, no BREAK).

Rules: name the exact checkpoint file; say "(not installed)" for anything else; mention LoRAs only when they clearly match (character/style/concept) and give their trigger words. SD 1.5 LoRAs need an SD 1.5 checkpoint, Pony LoRAs need Pony, Illustrious LoRAs work on Illustrious/WAI/NoobAI.
