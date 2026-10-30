# Image model families for prompting (Prompt Artist reference)
Exact prompt syntax, tags and sampler settings per family, with what each family does well and badly. Checked against official model cards and creator pages in October 2026 (sources at the end of each section). ComfyUI names first, A1111 names in brackets: euler_ancestral (Euler a), dpmpp_2m + karras (DPM++ 2M Karras). Clip skip 2 in ComfyUI = `CLIPSetLastLayer` stop_at_clip_layer -2.

## Pony Diffusion V6 XL (SDXL architecture)
- **Positive starts with the full score chain**: `score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up,`. `score_9` alone is much weaker (a training quirk that was never fixed). Do not add masterpiece / best quality / hd. The model does not need them.
- **Source tags**: `source_anime`, `source_cartoon`, `source_furry`, `source_pony`. **Rating tags**: `rating_safe`, `rating_questionable`, `rating_explicit`.
- Then Danbooru or e621 tags, or short natural language (it was trained on both). Order: score chain, source, rating, count/character/series, then the rest.
- **Negative**: not needed by design. Use it only for unwanted things, e.g. `score_4, score_5, score_6, 3d, monochrome, signature, watermark`.
- **Settings**: euler_ancestral, normal, 25 steps, CFG 6-8 (7), **clip skip 2 is required** (without it you get blobs), about 1 MP SDXL buckets.
- **Quirks**: it makes pseudo-signatures that are hard to remove (inpaint them). Artist names barely work because they were hashed in training, so use style LoRAs instead. `BREAK` in creator prompts is an A1111 feature, and in this setup it also works in **H1 06 - Prompt Artist (paste prompt, BREAK works)**, whose prompt boxes use `CLIPTextEncodeBREAK` from ComfyUI-ppm (each section is encoded on its own and joined with `ConditioningConcat`, like A1111). Core ComfyUI `CLIPTextEncode` (H1 01-05) does not split on it, so BREAK is just an ordinary word there: remove it. See "BREAK sections" below.
- **Best at**: western cartoon, furry/anthro, pony, explicit content, a huge LoRA library, stable anatomy in explicit poses. **Worst at**: photorealism (base model), characters from 2024 onwards, artist styles, and text.
- **Popular merges** (same score/source/rating syntax): AutismMix SDXL (confetti = better hands and a more stable anime style; _pony = better LoRA compatibility; CFG 7-8, clip skip 2, no negatives needed, add `3d` to the negative for a flatter anime look). Pony Realism v2.2 (photo style: `score_9, score_8_up, score_7_up`, negative `score_4, score_5, score_6`, at least 30 steps, CFG 6-7, clip skip 2, above 1024 px, use `female/male` rather than woman/man, weights ≤ 1.5, avoid dpmpp_2m karras).
- Sources: https://civitai.com/models/257749/pony-diffusion-v6-xl ; https://civarchive.com/models/288584 ; https://huggingface.co/TheImposterImposters/PonyRealism-v2.2MainVAE

## Illustrious-XL (OnomaAI, SDXL architecture, Danbooru2023)
- **v0.1** (ckpt `Illustrious-XL-v0.1`): the untuned base, with **no default style** on purpose. It is mainly a base for LoRAs and merges. Tags only. Euler a, 20-28 steps, CFG 5-7.5, 1 MP (1024x1024, 832x1216, 896x1152, 1216x832). Quality tags: `masterpiece`, `best quality`, `good quality`, `average quality`, `bad quality`, `worst quality`. Card negative: `worst quality, comic, multiple views, bad quality, low quality, lowres, displeasing, very displeasing, bad anatomy, bad hands, scan artifacts, monochrome, greyscale, signature, twitter username, jpeg artifacts, 2koma, 4koma, guro, extra digits, fewer digits`. Don't stack composition tags that conflict (close-up + cowboy shot + upside-down). Use one: portrait / upper body / cowboy shot / full body.
- **v1.0**: native 1536x1536 (512-1536, also 1248x1824), tags plus natural language. **v1.1 / v2.0**: multi-level captions, so natural-language sentences combined with tags work better for scenes with several objects. CFG about 4.5-7.5 (5.5), 20-30 steps, Euler a.
- **Best at**: anime characters (large Danbooru coverage up to 2023), artist-style tags, clean anime rendering, NSFW. **Worst at**: photorealism, text, and characters after the dataset cutoff (use a LoRA).
- Sources: https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0 ; https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.0 ; https://arxiv.org/abs/2409.19946

## WAI-illustrious-SDXL (popular Illustrious merge; the user has v17.0 `waiIllustriousSDXL_v170`)
- **Positive**: tags first, then **quality tags at the END**: `masterpiece, best quality, amazing quality`. The page's snippet starts with a leading comma, which means "append". Don't pile on more quality or aesthetic tags, because that makes the image blurrier.
- **Negative**: `bad quality, worst quality, worst detail, sketch, censor`. Keep it short, because long negatives reduce quality.
- **Ratings**: `general`, `sensitive`, `nsfw`, `explicit`. To make a character look older: `(mature female:1.2)` or `(aged up:1.2)` at the start.
- **Settings v17**: euler_ancestral, 15-30 steps (25), CFG 5-7, at least 1024 px (examples use 1024x1344; 832x1216 is fine). VAE is baked in. Hires fix 1.5x, 20 steps, R-ESRGAN 4x+ Anime6B, denoise 0.35-0.5 (v17 hires fix often repairs hands and feet). Clip skip is not required (1 or 2 both work).
- **Best at**: a polished, consistent anime look out of the box, character accuracy, NSFW. **Worst at**: realism, and a strong default style that can override subtle artist styles (lower CFG or add artist tags early).
- Sources: https://civarchive.com/models/827184?modelVersionId=2883731 ; https://huggingface.co/LyliaEngine/waiIllustriousSDXL_v170

## NoobAI-XL (Laxhar, Illustrious-based, Danbooru + e621)
- **Prefix**: `masterpiece, best quality, newest, absurdres, highres,` (optionally `very awa` = top-5% aesthetic; `worst aesthetic` goes in the negative). **Year tags**: `year 2024`. **Period tags**: newest (2021-24), recent (2018-20), mid (2014-17), early (2011-13), old (2005-10). **Ratings**: `general`, `sensitive`, `nsfw`, `explicit`.
- **Negative**: `nsfw, worst quality, old, early, low quality, lowres, signature, username, logo, bad hands, mutated hands` (drop `nsfw` for adult content). Add `mammal, anthro, furry, ambiguous form, feral, semi-anthro` for human-only pictures, because e621 data leaks in.
- **Epsilon versions** (eps 1.0/1.1): euler_ancestral, CFG 5-7, 28 steps.
- **V-prediction versions** (file names with vpred): **euler (not ancestral)**, CFG 3.5-5.5 (card: 4-5), 28-40 steps. In ComfyUI add `ModelSamplingDiscrete` sampling=v_prediction, zsnr on if the creator says so. `RescaleCFG` about 0.7 fixes oversaturation. Wrong sampling gives grey, washed-out or fried images.
- Resolutions: 768x1344, 832x1216, 896x1152, 1024x1024, 1152x896, 1216x832, 1344x768.
- **Best at**: the widest character and artist coverage, furry plus anime, lighting and colour (v-pred). **Worst at**: getting v-pred settings wrong, which ruins everything.
- Sources: https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0 ; NoobAI-XL user manual (Laxhar, 2024-11-28)

## Animagine XL 4.0 (Cagliostro Lab)
- **Strict order**: `1girl/1boy/1other, character, series, rating, general tags, artist tags, quality tags`. Quality tags go **at the END**: `masterpiece, high score, great score, absurdres`. Quality tags at the front stop artist tags from working. Always include the series tag after the character tag. Ratings: `safe`, `sensitive`, `nsfw`, `explicit`. Year tags: `year 2016`.
- **Negative**: `lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, fewer digits, cropped, worst quality, low quality, low score, bad score, average score, signature, watermark, username, blurry`.
- **Settings**: euler_ancestral, CFG 4-7 (5), 25-28 steps (28).
- Sources: https://huggingface.co/cagliostrolab/animagine-xl-4.0 ; https://cagliostrolab.net/posts/optimizing-animagine-xl-40-in-depth-guideline-and-update

## SD 1.5 realistic (the user has `Realistic_Vision_V5.1_fp16-no-ema`)
- **Positive**: `RAW photo, <subject in natural language>, 8k uhd, dslr, soft lighting, high quality, film grain, Fujifilm XT3`.
- **Negative**: `(deformed iris, deformed pupils, semi-realistic, cgi, 3d, render, sketch, cartoon, drawing, anime:1.4), text, cropped, out of frame, worst quality, low quality, jpeg artifacts, ugly, duplicate, morbid, mutilated, extra fingers, mutated hands, poorly drawn hands, poorly drawn face, mutation, deformed, blurry, dehydrated, bad anatomy, bad proportions, extra limbs, cloned face, disfigured, gross proportions, malformed limbs, missing arms, missing legs, extra arms, extra legs, fused fingers, too many fingers, long neck`.
- **Settings**: euler_ancestral or dpmpp_2m karras, 20-30 steps, CFG 3.5-7, native 512x768 / 768x512 (bigger = duplicated bodies; use hires fix 1.5-2x at denoise 0.3-0.45). Clip skip 1. The 77-token CLIP chunk limit means the first 75 tokens matter most.
- **Best at**: photo portraits on low VRAM, with a large LoRA library. **Worst at**: hands, complex multi-person scenes, prompt following, anime characters. SD 1.5 LoRAs (e.g. `8ctopus`) only work here.
- Sources: https://huggingface.co/SG161222/Realistic_Vision_V5.1_noVAE

## SDXL realistic fine-tunes (Juggernaut XL, RealVisXL, CyberRealistic XL...)
- Natural-language sentences first (subject, clothing, action, setting, light, lens/camera), then short detail phrases. Weights `(word:1.2)` work. Negative: `cartoon, anime, 3d render, painting, illustration, lowres, blurry, deformed hands, watermark, text`.
- dpmpp_2m(_sde) karras, 25-40 steps, CFG 3-6. Lightning/Hyper/DMD2 variants: 4-8 steps, CFG 1-2.
- Best at realistic people on 16 GB VRAM. Weaker than Flux/Qwen at prompt following and text.

## Flux.1 (Black Forest Labs)
- **dev**: guidance-distilled. Natural-language paragraph, **no negative prompt** (KSampler CFG 1, `FluxGuidance` 3.5), euler + simple, 20-50 steps (28 is a good minimum), about 1 MP. **schnell**: 4 steps, guidance 0, prompt ≤ 256 tokens. **Krea dev**: photographic aesthetic; guidance 3.5-5 (4.5), 28-32 steps, 1024-1280 px.
- Best at realism, text and prompt following. Worst at NSFW (censored base) and named anime characters. Doesn't understand tag soup or weights.
- Sources: https://huggingface.co/docs/diffusers/api/pipelines/flux ; https://github.com/krea-ai/flux-krea

## Chroma (Chroma1-HD, Flux-schnell based, uncensored)
- Natural-language sentences **in both positive and negative** (real CFG, so negatives work): e.g. negative `low quality, ugly, unfinished, out of focus, deformed, blurry, smudged, restricted palette, flat colors`.
- euler + beta, 26 steps, CFG 3.5-3.8 (40 steps / CFG 3 for best quality), 1024-1152 px, under 2 MP. CFG above 4.5 burns the image.
- Sources: https://huggingface.co/lodestones/Chroma1-HD

## Qwen-Image / Qwen-Image-Edit (Alibaba)
- **Qwen-Image t2i**: long descriptive English (or Chinese). Text in quotes renders as text. The card adds `, Ultra HD, 4K, cinematic composition.` to the end. 50 steps, true CFG 4, negative `" "` if none. Sizes: 1328x1328, 1664x928, 928x1664, 1472x1104, 1104x1472, 1584x1056, 1056x1584. Lightning LoRA: 4/8 steps, CFG 1.
- **Qwen-Image-Edit 2511** (the user has the Q4_K_M GGUF plus Lightning 4/8-step LoRAs): give it the reference image and an **instruction** ("Turn this into a realistic photo of an adult woman; keep the pose, outfit, hair colour and background"). Name what must stay the same. 4 or 8 steps CFG 1 with Lightning, otherwise about 40 steps CFG 3-4.
- **Qwen-Image-Edit Rapid AIO NSFW v23** (the user has `Qwen-Rapid-NSFW-v23_Q4_K`): all-in-one edit + t2i. 4 steps, CFG 1, euler_ancestral + beta, no negative. For t2i, leave the image input of TextEncodeQwenImageEditPlus empty.
- Best at prompt following, multiple subjects, text, and anime → real conversion. Worst at Danbooru tags and artist styles.
- Sources: https://huggingface.co/Qwen/Qwen-Image ; https://civarchive.com/models/2803528

## Resolution buckets
- **SDXL family** (Pony, Illustrious, NoobAI, Animagine, SDXL): 1024x1024, 1152x896, 896x1152, 1216x832, 832x1216, 1344x768, 768x1344, 1536x640, 640x1536. Pick the one closest to the reference aspect ratio. Illustrious ≥ v1.0 and WAI also handle up to about 1536.
- **SD 1.5**: 512x512, 512x768, 768x512, 640x448. Use hires fix for anything bigger.

## BREAK sections for 2+ people (Pony, Illustrious/WAI, NoobAI, Animagine, SD 1.5)
For tag-based CLIP families (Pony, Illustrious/WAI, NoobAI, Animagine, SD 1.5) and an image with 2+ people, write the Positive in sections separated by `BREAK`, each `BREAK` on its own line:
1. **Shared section first**: the family prefix where the family wants it at the start (Pony score chain + source + rating; NoobAI prefix), the head count (`2girls`, `1girl, 1boy`, `2boys`, `multiple girls`), `adult`, the shared action or interaction (`hug`, `holding hands`, `sitting together`), the scene/background and the camera/framing.
2. `BREAK`, then **one section per person**, left to right (or main person first), each starting with who it is (`girl on left`, `man on right`, `woman in front`) and holding ONLY that person: `mature female` / `mature male`, distinct hair colour and style, eye colour, body, every garment, pose and role. Give each person clearly different colours so they cannot blend; never repeat another person's colours.
3. Optional final `BREAK` + **shared ending**: lighting, colour/style tags, and for Illustrious/WAI/Animagine the quality tags (they still go at the very END of the prompt).
For ONE person BREAK is optional (at most one section for the person, one for scene/style). Never use BREAK in the Negative, or for Qwen, Flux or Chroma (sentence prompts).
`BREAK` only works in **H1 06 - Prompt Artist (paste prompt, BREAK works)**: its prompt boxes use the ComfyUI-ppm `CLIPTextEncodeBREAK` node, which encodes each section on its own (its own 75-token chunk) and joins them with ConditioningConcat, like BREAK in A1111/Forge. In H1 01-05 or any plain `CLIPTextEncode`, BREAK is just an ordinary word, so remove it there (or merge the sections into one line).
Example (WAI, two people):
```text
2girls, adult, multiple girls, holding hands, walking, park, autumn, full body
BREAK
girl on left, mature female, long hair, black hair, red eyes, white blouse, black skirt, smile
BREAK
girl on right, mature female, short hair, blonde hair, blue eyes, green dress, open mouth, waving
BREAK
sunlight, depth of field, masterpiece, best quality, amazing quality
```

## Which H1 workflow to paste into (the user's H1 workflows)
- **H1 06 - Prompt Artist (paste prompt, BREAK works)** is the default: paste the Positive and Negative exactly as written. Illustrious/WAI prompts work as they are (checkpoint `waiIllustriousSDXL_v170`). For a Pony prompt, first switch its checkpoint to `ponyDiffusionV6XL_v6StartWithThisOne` and set the "LoRA - Anatomy Helper" strength to 0 (Pony needs its own LoRAs).
- **H1 01 - Make a character** for one reusable character: paste only the content tags (no quality tags, no score chain, no BREAK); that workflow adds its own quality tags.
- **H1 02 - Group picture of 2-3 characters** for 2-3 people with regional prompts: one tag line per person (each person's section without BREAK) in its LEFT / RIGHT / CENTRE boxes, and the shared section in SCENE; it adds the quality tags itself.
- In H1 03, H1 04, H1 05 BREAK is an ordinary word: remove it.
