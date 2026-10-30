# Playbook: remake a workflow in a different style (e.g. anime -> realistic)
Never edit the original file. Work on a draft, validate, then save as a NEW file only after the user says yes.

1. **Summarize**: summarize_workflow(source). Note family, checkpoint, LoRAs (+ strengths), prompts, sampler, sizes, detailers/upscalers, anime_style_signals, missing nodes/models.
2. **Read the guide**: kb_read("anime_to_realistic") (and model_families / pipelines if needed).
3. **Propose a plan** to the user in a short list BEFORE editing: which route (same family realistic merge / SDXL realistic / Qwen-Image-Edit conversion / other), what gets removed, swapped, added, new settings, new prompts. Ask only if a real choice is needed (e.g. keep Pony LoRAs?). Otherwise proceed.
4. **Find real models**: for each new model/LoRA:
   - civitai_search_models(query, types, base_models, sort="Most Downloaded") (falls back to CivArchive in the UK) and/or hf_search_models.
   - civitai_get_model(model_id) -> pick version: exact filename, size, sha256, base_model, trigger words, recommended settings, mirror_urls.
   - Check it's not already on disk: list_local_models(folder_type, match).
   - Only use names/URLs returned by tools.
5. **Check node types**: comfy_node_info for every node type you will add (exact names + widget order). For new packs, find_node_pack.
6. **Edit a copy**: edit_workflow(source, ops) - e.g.
   - `{"op":"set_widget","node":4,"widget":"ckpt_name","value":"<exact filename>"}`
   - `{"op":"set_widget","node":6,"widget":"text","value":"<new positive>"}`
   - `{"op":"remove_node","node":12}` (reconnects pass-through automatically)
   - `{"op":"add_node","type":"FaceDetailer","ref":"fd","widgets":{...},"pos":[x,y]}` then `{"op":"connect","from":"$fd", "from_slot":0,"to":15,"to_input":"images"}`
   - `{"op":"add_note","text":"Changes made by ComfyUI Expert: ..."}`
   Edit the draft further with edit_workflow(draft_id, ops).
7. **Validate**: the edit result includes validation; fix every error (wrong widget name, missing link, type mismatch) and re-validate. Missing models are OK only if they are in the download plan.
8. **Save**: write_workflow(draft_id, filename="<original>_realistic", confirm=false) shows the dry-run; then the user confirms -> confirm=true. Report the saved path (in the 'generated' folder).
9. **Downloads**: plan_downloads([...]) with url, folder, filename, sha256, size -> show the table; download_file(...) only after the user says yes (one call per file).
10. **Optional test**: comfy_queue_test(source=draft or saved file) only if the user agrees and models are present.
11. **Report**: what changed (old -> new), models to download (name, size, folder, link), settings, and how to open the new file in ComfyUI.
