# ComfyUI basics: workflow files and formats

## Two JSON formats
ComfyUI saves workflows in two different JSON shapes. Always check which one you have (summarize_workflow reports `format`).

**UI format** (what "Save" / drag-and-drop uses, also embedded in PNGs as `workflow`):
```json
{"last_node_id": 9, "last_link_id": 9,
 "nodes": [{"id": 3, "type": "KSampler", "pos": [863, 186], "size": [315, 262], "mode": 0,
            "inputs": [{"name": "model", "type": "MODEL", "link": 1}, ...],
            "outputs": [{"name": "LATENT", "type": "LATENT", "links": [7], "slot_index": 0}],
            "widgets_values": [156680208700286, "randomize", 20, 8, "euler", "normal", 1]}],
 "links": [[1, 4, 0, 3, 0, "MODEL"]],
 "groups": [{"title": "Prompts", "bounding": [x, y, w, h]}],
 "definitions": {"subgraphs": [...]}, "extra": {...}, "version": 0.4}
```
- `links` entries: `[link_id, origin_node_id, origin_slot, target_node_id, target_slot, TYPE]` (subgraphs store links as objects with the same fields).
- `mode`: 0 = active, 2 = muted (never runs), 4 = bypassed (inputs passed straight through by type).
- `widgets_values` is a **positional list**. The order is the node's widget order from `/object_info` (`input_order`, required then optional, widget-type inputs only). Extra hidden values:
  - after an INT `seed`/`noise_seed` (anything with control_after_generate) comes `"randomize"|"fixed"|"increment"|"decrement"`;
  - after LoadImage's `image` comes an upload placeholder value;
  - V3 "dynamic combo" widgets are followed by the chosen option's child widgets (named `combo.child`).
- Newer frontends put widget inputs in `inputs[]` too (with a `widget` key) so they can be linked.
- `groups` are just coloured boxes; a node belongs to a group if its `pos` is inside `bounding`.
- `definitions.subgraphs`: reusable sub-workflows. A node whose `type` is a UUID is an instance of a subgraph. Official templates use these a lot.

**API format** (what "Export (API)" writes and what POST /prompt accepts; also in PNGs as `prompt`):
```json
{"3": {"class_type": "KSampler",
       "inputs": {"seed": 1, "steps": 20, "cfg": 8, "sampler_name": "euler", "scheduler": "normal",
                  "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]},
       "_meta": {"title": "KSampler"}}}
```
- Links are `[source_node_id_as_string, output_slot]`. Widgets are named. No positions, groups, notes, reroutes or muted nodes.
- The API format can't be re-opened with the layout; keep the UI version as the "source of truth" and convert.

## Frontend-only nodes
`Reroute`, `Note`, `MarkdownNote`, `PrimitiveNode`, rgthree "Fast Groups Muter/Bypasser", "Label (rgthree)", group nodes: they exist only in the UI and are removed when converted to API. `PrimitiveNode` feeds its value into the widget it is linked to. Do NOT report them as missing nodes.

## The server API (default http://127.0.0.1:8188)
- `GET /object_info` - every installed node: inputs (required/optional, types, combo lists = the model files ComfyUI can see), outputs, category, python module. **This is the ground truth for node names.**
- `GET /system_stats` - version, python, torch, devices, VRAM.
- `POST /prompt {"prompt": <API json>, "client_id": "..."}` - queue a job; returns `prompt_id` or `node_errors`.
- `GET /history/{prompt_id}` - result / errors; `GET /queue`; `POST /interrupt`; `GET /view?filename=...` for outputs.
- `GET /models/<folder>` lists model files of a folder in newer versions.

## Where things live (portable Windows build)
- `ComfyUI_windows_portable\python_embeded\python.exe` - ComfyUI's own Python. **Never pip-install other tools into it.** Custom node requirements are installed with it: `python_embeded\python.exe -m pip install -r ComfyUI\custom_nodes\<pack>\requirements.txt`.
- `ComfyUI\custom_nodes\` - node packs (git folders). `ComfyUI\models\<folder>\` - models. `ComfyUI\input\`, `ComfyUI\output\`.
- `ComfyUI\user\default\workflows\` - workflows saved from the UI. `extra_model_paths.yaml` (next to main.py) adds more model folders.
- Official templates (Workflow > Browse Templates) ship in `python_embeded\Lib\site-packages\comfyui_workflow_templates_json\templates\` - list_official_templates reads them. They are current, tested and contain model download links (`node.properties.models`).

## Node names: the golden rule
Node `type`/`class_type` must match an installed node's internal name exactly (case-sensitive, spaces matter, e.g. `CheckpointLoaderSimple`, `UltralyticsDetectorProvider`, `Power Lora Loader (rgthree)`). Display names in the menu can differ. Always confirm with comfy_node_info; if missing, find_node_pack tells you which GitHub pack provides it.
