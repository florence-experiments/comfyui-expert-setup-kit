# Playbook: troubleshoot a failed generation / OOM / bad images
1. Ask for (or read) the exact error text from the ComfyUI console or the red node. comfy_status for GPU/VRAM/version info.
2. kb_search(error words) and kb_read("troubleshooting"); for memory issues kb_read("amd_rocm_16gb").
3. If a workflow is involved: validate_workflow(source) and summarize_workflow(source) - wrong family combos (SD1.5 LoRA in SDXL, wrong CLIP type), missing models, odd settings (CFG, steps, size).
4. For node-specific errors: comfy_node_info(type) and fetch_url the pack's GitHub README/issues (github_search, web_search with the error message).
5. Give the most likely cause first, then 2-3 concrete fixes in order (cheapest first), e.g. lower resolution / GGUF Q4 / VAEDecodeTiled / --reserve-vram 2 / stop llama-server GPU use.
6. If a fixed workflow copy helps: edit_workflow -> validate -> write_workflow (confirm).
