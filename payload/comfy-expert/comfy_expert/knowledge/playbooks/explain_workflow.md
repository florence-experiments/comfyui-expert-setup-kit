# Playbook: explain a workflow
Goal: tell the user in plain words what their workflow does, using only facts from tools.

1. Find it: if the user gave a name, list_workflows(match=...) then use the exact path. PNG files with embedded workflows work too.
2. summarize_workflow(source). Use: model_family_guess, models/loras (found_locally), prompts, sampler_settings, image_sizes, groups, pipeline_order, custom_or_missing_types, subgraphs, embedded_model_links.
3. If something is unclear (an unknown node), comfy_node_info(type) - or find_node_pack if not installed.
4. Answer with:
   - One-line purpose ("SDXL portrait generator with FaceDetailer and 2x upscale").
   - The pipeline step by step following pipeline_order / groups (loader -> LoRAs -> prompts -> sampler -> detailer -> upscale -> save).
   - Models and LoRAs used (file names exactly as in the workflow) and whether each is on disk.
   - Key settings (steps, CFG, sampler, size, denoise).
   - Problems: missing nodes, missing models, muted/bypassed parts, odd settings. Offer validate_workflow for full checks.
5. Don't invent what a node does; if unsure, say so and offer to look it up.
