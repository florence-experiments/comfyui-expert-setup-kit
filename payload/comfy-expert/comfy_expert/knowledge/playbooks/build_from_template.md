# Playbook: build a new workflow from a template
1. list_templates() - this helper's verified templates (sdxl_txt2img, sdxl_img2img, sdxl_inpaint, sdxl_facedetailer_upscale, sdxl_ipadapter_character, qwen_image_edit_2511_gguf). Each lists use_for / needs / edit_hints.
2. For other model families (Flux, Wan video, Z-Image, Qwen-Image, HiDream, ControlNet...) use list_official_templates(match) - the official ComfyUI templates installed with the user's ComfyUI. Load with "official:<name>".
3. summarize_workflow(template) to see node ids and settings.
4. Decide the changes (models from the user's disk via list_local_models, or found online; prompts; size; sampler per kb samplers_settings).
5. edit_workflow(template, ops) -> draft. Typical ops: set_widget on ckpt/unet/lora/prompt/size/steps; add_node LoraLoader + connect; set_title; add_note with instructions.
6. Validate (included in the edit result). Fix errors. Check comfy_node_info for any node you add.
7. write_workflow(draft_id, filename, confirm=false) -> show -> on yes confirm=true. Mention needed downloads (plan_downloads).
