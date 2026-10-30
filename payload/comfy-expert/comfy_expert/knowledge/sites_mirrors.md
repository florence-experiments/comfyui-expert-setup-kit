# Civitai alternatives and mirrors
Source: github.com/airborne-commando/civitai-mirror-list (README fetched Oct 2026). Use these when Civitai is blocked (UK) or a model was removed.

## Model hosts / archives (most useful first)
- **civitaiarchive.com (CivArchive)** - community archive of Civitai models and files, lookup by name, SHA256 or Civitai link; lists mirrors. Built into this helper (model_archive_search, civitai_* fallbacks, civitai_by_hash).
- **Hugging Face** (huggingface.co) - official releases + many re-uploads of Civitai models (search the model name or the creator).
- **SeaArt.ai** - big library; the list recommends trying it first for backups of pulled models/LoRAs.
- **Tensor.Art** - Civitai-like, many models; downloads depend on the creator.
- **diffusionarc.com (civitarc.com)** - free archive for image-generation models (SD, Flux, ...).
- **ModelScope.cn** - Alibaba's Chinese "Hugging Face" (Qwen, Wan first releases).
- **liblib.art** and **shakker.ai** - Chinese model sites with unique LoRAs (language barrier).
- **PixAI.art**, **PromptHero** - mostly generation / prompt sharing.

## Tools (run them yourself, outside this helper)
- CivitAI-Model-grabber (github.com/Confuzu/CivitAI-Model-grabber) - bulk download by Civitai username.
- go-civitai-downloader (github.com/dreamfast/go-civitai-downloader) - archive Civitai content, torrent generation.
- Torrent search engines (btdig, damag) and stablebay.org are listed too - only use them where legal, and treat files from unknown sources with care: prefer `.safetensors` (never run untrusted `.ckpt`/`.pt`/`.bin` pickles), check SHA256 against the Civitai/CivArchive hash.

## Other resources listed
- Curated lists: awesome-stable-diffusion (doanbactam), awesome-diffusion-categorized, Awesome-Video-Diffusion-Models; r/StableDiffusion; Tensor.Art articles; fmhy.net.
- Image hosts that keep metadata (to share PNGs with embedded workflows): Turboimagehost, 8upload, Postimages, Imgbb, Gifyu (metadata retention can change - test first).

## Safety rules for mirrors
1. Same file = same SHA256. Get the hash from Civitai/CivArchive (`files[].sha256`) and pass it to download_file (it verifies and renames bad files to .badhash).
2. Filenames on mirrors often differ (e.g. `juggernautXL_ragnarokBy.safetensors`); save with the name the workflow expects or update the widget.
3. Prefer `.safetensors` and `.gguf`. Pickle formats (.ckpt/.pt/.pth/.bin) can contain code - only from trusted repos (e.g. official upscalers, Bingsu/adetailer).
