# Civitai (civitai.com) - API v1, keys, UK block, archives

## IMPORTANT: UK region block
Civitai blocks visitors from the United Kingdom (Online Safety Act) - the API answers `{"code":"REGION_BLOCKED"}` / HTTP 451 and downloads fail. This helper detects that and automatically uses **CivArchive (civitaiarchive.com)** for search/model info, plus **mirror URLs** (mostly Hugging Face copies) for the files. Options for the user:
1. Use the mirror_urls the tools return - always check the SHA256 matches the Civitai file hash (download_file does this when you pass sha256).
2. Set `network.proxy` / `HTTPS_PROXY_FOR_TOOLS` (or use a VPN) - only if legal for the user.
3. Search Hugging Face for the same model name (many creators upload there too).

## API v1 basics (base https://civitai.com/api/v1)
- `GET /models?query=&types=Checkpoint|LORA|...&baseModels=SDXL 1.0&sort=Most Downloaded|Highest Rated|Newest&period=AllTime|Year|Month|Week&nsfw=true&limit=20` - search (civitai_search_models).
- `GET /models/{modelId}` - model with all versions, files, trigger words (civitai_get_model).
- `GET /model-versions/{versionId}` and `GET /model-versions/by-hash/{sha256}` (civitai_get_version, civitai_by_hash).
- `GET /images?modelVersionId=&nsfw=&limit=&withMeta=true` - example images with their generation settings (civitai_images) - great for finding the settings creators really use.
- Download: `https://civitai.com/api/download/models/{versionId}` (redirects to the file). Some models need login: send `Authorization: Bearer <CIVITAI_API_KEY>` (download_file does this only for civitai.com).
- API key: civitai.com > Account settings > API Keys > Add. Put it in `.env` as `CIVITAI_API_KEY=...`. Never paste keys into chat.
- Docs: https://developer.civitai.com/docs/api/public-rest (old wiki: github.com/civitai/civitai/wiki/REST-API-Reference).

## Model types and base models
- types: Checkpoint, TextualInversion, Hypernetwork, AestheticGradient, LORA, LoCon, DoRA, Controlnet, Upscaler, MotionModule, VAE, Poses, Wildcards, Workflows, Detection, Other.
- baseModels strings include "SD 1.5", "SDXL 1.0", "Pony", "Illustrious", "NoobAI", "Flux.1 D", "Flux.1 S", "Flux.2 D", "Qwen", "Wan Video 2.2 T2V-A14B", "Wan Video 14B t2v/i2v 480p/720p", "Chroma", "HiDream", "ZImageTurbo" (names change - copy them from a real result).
- A version's `files[]` has name, sizeKB, type (Model/Pruned Model/Training Data/VAE/Config), metadata {fp, size, format}, hashes {SHA256, AutoV2...}, downloadUrl. Pick the primary Model file (safetensors, fp16 pruned for SDXL).

## Reading a model page well
- Version name + base model (must match the workflow family).
- "About this version" usually has recommended sampler / steps / CFG / clip skip / VAE / hires settings. civitai_images withMeta shows real settings.
- Trigger words for LoRAs. Recommended LoRA weight.
- Downloads, rating and date - prefer popular, recent versions. Check "Early Access" (paid/locked for a while).
- NSFW flags: the user allows NSFW, but characters must be adults.

## CivArchive (civitaiarchive.com) - the fallback
- Archive of Civitai (and Tensor.Art / SeaArt) model pages including deleted ones; search by name, Civitai URL or SHA256.
- `GET /api/search?q=...&platform=civitai|tensorart|seaart` and `GET /api/models/{id}?modelVersionId=` and `GET /api/sha256/{hash}` (used by model_archive_search, civitai_get_model fallback, civitai_by_hash fallback).
- Each file lists mirrors (Hugging Face repos, other hosts). Mirror filenames may differ - save under the name you want (download_file filename=) and verify sha256.
