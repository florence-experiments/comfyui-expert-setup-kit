# Playbook: find and download models / LoRAs
1. Clarify target: type (checkpoint, LoRA, ControlNet, upscaler...), base family (SDXL/Pony/Illustrious/Flux/Qwen/Wan...), style, VRAM limit (16 GB AMD -> GGUF/fp8 for big models).
2. Search several sources:
   - civitai_search_models(query, types=[...], base_models=[...], sort="Most Downloaded" or "Highest Rated", period) - in the UK this uses CivArchive automatically.
   - hf_search_models(query, author/filter="gguf") for official / repackaged / GGUF files.
   - model_archive_search(query, platform="tensorart"|"seaart") for models from those sites.
   - web_search for news/comparisons when needed.
3. Open the best 2-4 candidates: civitai_get_model / hf_list_files / hf_model_info. Collect: exact filename, size, base model, version date, trigger words, recommended settings, licence/gated, sha256, download URL + mirrors.
4. Check disk: list_local_models(folder_type, match) - maybe it's already there.
5. Present a short comparison and recommend one. Every name/URL must come from a tool result.
6. Download only after explicit yes: plan_downloads(items) first (shows target folder, free space, existing files), then download_file(url, folder, filename, sha256, expected_size_bytes, confirm=true). In the UK prefer mirror_urls (verify sha256).
7. Gated HF repo / Civitai login-only: tell the user how to set HF_TOKEN / CIVITAI_API_KEY in .env (kb_read sites_huggingface / sites_civitai).
