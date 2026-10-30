# Playbook: compare models across Civitai / Hugging Face / Tensor.Art / SeaArt
1. Pin down the need: style (photoreal, anime, semi-real), family, content (NSFW allowed for adults), hardware (16 GB AMD).
2. Gather candidates from each source:
   - Civitai (or CivArchive fallback): civitai_search_models with base_models + sort "Most Downloaded"/"Highest Rated"; civitai_get_model for details; civitai_images(withMeta) for real settings.
   - Hugging Face: hf_search_models, hf_model_info (licence, gated, base_model), hf_list_files (sizes, quant variants).
   - Tensor.Art / SeaArt: model_archive_search(platform=...), archive_get_page(url) - and say downloads may be disabled there.
3. Build a comparison table: name, source(s), family/base, version/date, size(s), downloads/likes, licence/gated, recommended settings, VRAM fit on 16 GB, download availability in the UK (Civitai blocked -> mirrors?).
4. Recommend with reasons (quality for the use case, fit, availability). Mark anything not verified as "not checked".
5. Offer next steps: download (plan_downloads -> confirm), or plug into a workflow (remake / build_from_template).
