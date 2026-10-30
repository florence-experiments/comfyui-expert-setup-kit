# Model families (what they are, how they load, what they need)
Settings here are good starting points, not laws. Check the model's own page (civitai_get_model / hf_model_info) - creators usually list their recommended sampler, CFG, steps and clip skip. The official ComfyUI templates (list_official_templates) are the best reference wiring for every modern family.

## SD 1.5
- 512x512 / 512x768 native. Checkpoint 2-4 GB in models/checkpoints. LoRAs for "SD 1.5" only.
- CFG 6-8, 20-30 steps, dpmpp_2m karras. Anime models often clip skip 2.
- Old but huge LoRA library. Not compatible with SDXL LoRAs/ControlNets.

## SDXL 1.0 (and realistic SDXL fine-tunes)
- Native ~1 megapixel: 1024x1024, 832x1216, 896x1152, 1216x832, 1344x768. Checkpoint ~6.5 GB (fp16), in checkpoints.
- Wiring: CheckpointLoaderSimple -> CLIPTextEncode x2 -> KSampler -> VAEDecode. EmptyLatentImage.
- Realistic fine-tunes (e.g. Juggernaut XL, RealVisXL, epiCRealism XL, ZavyChroma XL, CyberRealistic XL - look them up, don't assume versions): CFG 3-6, 25-40 steps, dpmpp_2m_sde / dpmpp_2m + karras, or the creator's choice.
- Lightning/Hyper/Turbo/DMD2 variants: 4-8 steps, CFG 1-2, sampler as stated on the page (often euler / lcm / dpmpp_sde with sgm_uniform).
- LoRAs marked "SDXL 1.0" work on SDXL fine-tunes; Pony and Illustrious LoRAs usually only work well on their own family.

## Pony Diffusion V6 XL (SDXL architecture)
- Base model "Pony" on Civitai. Prompts start with `score_9, score_8_up, score_7_up` (+ `source_anime`, `source_real`, `rating_safe/questionable/explicit`). Clip skip 2. CFG 6-8, euler a / dpmpp_2m, 25 steps.
- Realistic Pony merges exist (search Civitai baseModel Pony + "realistic"), but Pony LoRAs are the reason to keep Pony.

## Illustrious XL / NoobAI-XL (SDXL architecture, anime)
- Base models "Illustrious" / "NoobAI" on Civitai. Danbooru-tag prompts (`1girl, solo, ...`), quality tags like `masterpiece, best quality, amazing quality`. CFG 4-7, euler a, 20-30 steps; some NoobAI versions are v-prediction (need the right sampling setting - read the page).
- These are anime-first. For realism you either use a realistic Illustrious merge or switch the base family (see anime_to_realistic).

## Flux.1 (Black Forest Labs) dev / schnell / Kontext
- 12B diffusion transformer. Files: flux1-dev (diffusion_models, ~23 GB bf16 / ~12 GB fp8), text encoders clip_l + t5xxl (fp16 or fp8_e4m3fn_scaled) in text_encoders, VAE ae.safetensors.
- Wiring (official template): UNETLoader + DualCLIPLoader(type flux) + VAELoader, CLIPTextEncode -> FluxGuidance(3.5) -> KSampler cfg 1, euler, simple, 20 steps, EmptySD3LatentImage 1024x1024. Negative = ConditioningZeroOut (negatives do nothing at cfg 1).
- Schnell: 4 steps. Kontext (image editing): ReferenceLatent + FluxKontextImageScale, guidance 2.5.
- GGUF quants (city96/FLUX.1-dev-gguf etc.) Q4-Q8 fit 16 GB comfortably. Flux LoRAs only work on Flux.1.

## Flux.2
- Newer, larger family (dev ~32B). Text encoder mistral_3_small_flux2 (CLIPLoader type flux2), EmptyFlux2LatentImage, Flux2Scheduler, SamplerCustomAdvanced. Heavy: on 16 GB use fp8/GGUF and offloading. Use the official template.

## Chroma (Flux.1-schnell based, uncensored community model)
- CLIPLoader type chroma with t5xxl, ae VAE, ModelSamplingAuraFlow shift 1, CFGGuider cfg ~3.5, euler + beta, ~26 steps (official template), real negative prompts work. Good for realism and NSFW-capable.

## Qwen-Image (Alibaba, 20B MMDiT) and Qwen-Image 2512
- Excellent prompt following and text rendering, realistic or stylised. Files (Comfy-Org/Qwen-Image_ComfyUI): diffusion model qwen_image_*_fp8_e4m3fn (~19 GB) or GGUF (city96/Qwen-Image-gguf, QuantStack, unsloth), text encoder qwen_2.5_vl_7b_fp8_scaled (8.7 GB), VAE qwen_image_vae.
- Wiring: UNETLoader -> ModelSamplingAuraFlow(shift 3.1) -> KSampler; CLIPLoader type qwen_image; EmptySD3LatentImage ~1328x1328 or 1MP+. CFG ~2.5-4, 20-50 steps, euler simple. Lightning LoRA (lightx2v/Qwen-Image-Lightning): 4 or 8 steps at cfg 1.

## Qwen-Image-Edit (original, 2509, 2511)
- Instruction image editing: "make it a photo", "change her dress to red", multi-image with 2509+/2511 (image1..image3).
- Wiring (official 2511): UNETLoader/UnetLoaderGGUF -> ModelSamplingAuraFlow(3.1) -> CFGNorm(1) -> (optional Lightning LoRA) -> KSampler; TextEncodeQwenImageEditPlus for positive and negative (clip, vae, image1) -> FluxKontextMultiReferenceLatentMethod(index_timestep_zero) -> KSampler; LoadImage -> FluxKontextImageScale -> VAEEncode -> latent. 40 steps cfg ~3-4 without LoRA; 4 steps cfg 1 with Lightning 4-step.
- Official template `templates-image_to_real` uses Qwen-Image-Edit-2509 + "Anything2RealAlpha" LoRA for anime/illustration -> photo.
- GGUF: unsloth/Qwen-Image-Edit-2511-GGUF (Q3_K_M 9.2 GB ... Q4_K_M 12.3 GB ... Q8_0 20.3 GB), QuantStack/Qwen-Image-Edit-2509-GGUF.

## Z-Image (Tongyi, 6B) Turbo
- Fast realistic text-to-image: UNETLoader z_image_turbo, CLIPLoader qwen_3_4b (type lumina2, as in the official template), ae VAE, ModelSamplingAuraFlow shift 3, 1024x1024, 8 steps, cfg 1, res_multistep simple. Very good for realism on 16 GB.

## Wan 2.1 / 2.2 (video, also strong for realistic stills)
- Wan 2.2 14B uses TWO experts: high_noise model for the first half of the steps and low_noise for the rest (two KSamplerAdvanced: start 0 -> end N/2 with leftover noise, then N/2 -> end). ModelSamplingSD3 shift ~5-8. Text encoder umt5_xxl_fp8_e4m3fn_scaled (CLIPLoader type wan), VAE wan_2.1_vae.
- Lightx2v 4-step LoRAs (high + low variants): 4 steps, cfg 1. Without: ~20 steps each, cfg 3.5.
- Wan 2.2 5B TI2V: single model, wan2.2_vae, 20 steps cfg 5 uni_pc.
- On 16 GB: fp8 or GGUF (QuantStack/Wan2.2-*-GGUF) at Q4-Q6, 480p-720p, 81 frames; use VAEDecodeTiled if decode OOMs.

## Other names you may meet
SD3/3.5 (TripleCLIPLoader), HiDream, Lumina, AuraFlow, Kolors, PixArt, Hunyuan Image/Video, LTX-Video, Cosmos, HiDream-E1. Use list_official_templates and the model page before giving settings.

## How to tell the family of an unknown file
1. civitai_by_hash with the file's SHA256 (CivArchive works when Civitai is blocked).
2. Civitai "baseModel" field: "SD 1.5", "SDXL 1.0", "Pony", "Illustrious", "NoobAI", "Flux.1 D", "Flux.1 S", "Qwen", "Wan Video 14B t2v", etc.
3. File size: SD1.5 ~2-4 GB, SDXL ~6.5 GB, Flux/Qwen diffusion-only 12-40 GB, LoRA 10-800 MB.
