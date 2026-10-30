# Playbook: fix red / missing nodes (and missing models)
1. validate_workflow(source) -> errors "Node type X is not installed". Also summarize_workflow custom_or_missing_types.
2. Ignore frontend-only nodes (Note, MarkdownNote, Reroute, PrimitiveNode, rgthree fast groups) - they are fine.
3. For each missing type: find_node_pack(type) -> repo + title. If no match: comfy_node_info(type) for did_you_mean (renamed node?), then github_search / web_search with the exact type name.
4. Tell the user which packs to install and how: ComfyUI-Manager > Custom Nodes Manager > search title > Install (or "Install Missing Custom Nodes"), restart ComfyUI. Mention AMD caveats if the pack needs CUDA-only libraries (kb_read amd_rocm_16gb).
5. If a pack is dead/unsafe/AMD-incompatible: suggest an equivalent core/common node, and with the user's OK build a fixed copy with edit_workflow replace_node / add_node + connect, then validate.
6. Missing models: from validate_workflow missing_models -> find_models playbook. embedded_model_links in summarize_workflow are links stored by the workflow author (verify with hf_list_files / fetch_url before trusting).
7. Never write node packs or pip packages into ComfyUI yourself - give the user the steps.
