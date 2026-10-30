# ComfyUI Expert

A local helper that turns your own llama.cpp model into a **ComfyUI expert with real tools**. It runs on your PC, opens a chat page in your browser, and can:

- **read and explain your workflows** (JSON files or PNGs with an embedded workflow);
- **remake a workflow in another style** (for example anime → realistic): it works on a copy, checks every node and setting, and saves a *new* file;
- **find real models** on Civitai, Hugging Face, Tensor.Art, SeaArt, CivArchive and the mirrors from the civitai-mirror-list, with exact file names, sizes, hashes and links;
- **download models** into the right ComfyUI folder, with resume and size/hash checks, but only after you click **Yes**;
- **fix red/missing nodes** by finding the custom-node pack that provides them;
- **build workflows from verified templates** (6 of its own, plus ComfyUI's official templates installed with your ComfyUI);
- **troubleshoot** errors, black images and out-of-memory problems on your graphics card (AMD, NVIDIA or Intel);
- **compare models** across sites.

It looks things up instead of guessing. This matters because local models tend to invent node names and download links. Every node type is checked against your running ComfyUI (or a built-in list from ComfyUI 0.34 when ComfyUI is off). Every model name and link comes from a real search. Before an answer is shown, a **self-check** looks for links, file names and node names that no tool confirmed. If it finds any, it asks the model to verify them, and anything still unconfirmed is marked **⚠ Not verified**.

> **Honest note:** the helper is only as smart as the model you give it. The tools stop most made-up facts, but planning a good remake needs a capable model. **Recommended: Qwen3.8 27B (Q4_K_M or better) with `-c 32768` or more.** Gemma-4 26B-A4B and Qwen3.8-Flash-Next work too and are faster. Small models (3-8B) can call tools but make poor plans. On the build machine a 3B test model managed simple tasks only.

---

## Safety: what it will and won't do

- **Read-only by default.** Reading workflows, searching and checking cost nothing and change nothing.
- **Three actions need your Yes:** saving a workflow, downloading a file, and sending a test generation to ComfyUI. Each one runs as a dry run first ("this is what I would do"). Then you get **Yes / No** buttons in the chat, or a `y/N` prompt in the terminal.
- **Your existing workflow files are never changed.** New workflows always go into a `generated` subfolder (inside your first workflow folder), and an existing file is never overwritten.
- Downloads only go into your models folder (`checkpoints`, `loras`, `vae`, ...). They resume if interrupted and are checked against the expected size and SHA256.
- It **never installs anything into ComfyUI's `python_embeded`** and never installs custom nodes. It tells you how to install them with ComfyUI-Manager.
- NSFW is fine for adults, but **characters are always adults**. One fixed rule is built into the code and cannot be switched off: nothing sexual involving anyone under 18.
- The web page only listens on `127.0.0.1`, so other computers can't open it.
- If an action would fail anyway (for example saving a draft that doesn't exist), the dry run catches it and you are **not** asked. If the model keeps repeating the same tool call, the helper stops it and makes it answer.

---

## Install on Windows (about 5 steps)

1. **Install Python 3.10 or newer** from <https://www.python.org/downloads/windows/> and tick *"Add python.exe to PATH"*. This is separate from ComfyUI's own Python, which the helper doesn't touch.
2. **Unzip** the app somewhere, for example `D:\AI\comfy-expert`. (The ComfyUI Expert Setup Kit does steps 1-5 for you.)
3. Double-click **`setup.bat`** (not needed when you used the setup kit). It creates a private environment (`.venv`), installs what it needs, creates `config.yaml` and `.env`, and runs a check.
4. Open **`config.yaml`** in Notepad and check the folders. Set your ComfyUI folder, extra model folders and workflow folders. Put API keys in `.env` if you have them (optional, see below).
5. **Start llama-server** (see the next section), start ComfyUI as usual (optional but recommended), then double-click **`run.bat`**. Your browser opens at **<http://127.0.0.1:7860>**.

Other launchers:
- `run-cli.bat` starts the same assistant in a terminal window.
- `run-mcp.bat` starts the MCP server for OpenHands and other agent apps (see below).
- `.venv\Scripts\python.exe -m comfy_expert doctor` checks llama-server, ComfyUI, folders and keys.

## Starting llama-server

The helper talks to llama-server's OpenAI-style API at `http://127.0.0.1:8080/v1` (change `llm.base_url` in `config.yaml` if you use another port). Two flags matter:

- `--jinja` is **required**. Without it tool calling doesn't work.
- `-c 32768` or more. Workflows and search results are big, and a smaller context makes the model forget.

```bat
llama-server.exe -m D:\AI\LLM\Qwen3.8-27B-Q4_K_M.gguf --jinja -c 32768 -ngl 99 -fa on -ctk q8_0 -ctv q8_0 --port 8080
```

The setup kit writes `start-llama.bat` (Windows) or `start-llama.sh` (Linux) for you.

**VRAM sharing:** a 27B Q4 model needs about 16-17 GB, which is a whole 16 GB card. ComfyUI needs the GPU too. Pick one of these:
- Lower `-ngl` (for example `-ngl 40`) so part of the model sits in system RAM. This is slower but works next to ComfyUI.
- For the MoE models (Gemma-4 26B-A4B, Qwen3.8-Flash-Next), use `--n-cpu-moe 30` (try values from 20 to 40). This keeps the expert weights in RAM with little loss of speed.
- Or stop llama-server while you generate big images or videos.

The helper finds the loaded model name on its own (from `/v1/models`) and warns you in the sidebar if the context is too small.

## Using it

Type in plain English, or use the quick-start buttons on the left. Examples:

- *"Explain my workflow `portrait_v3.json`."*
- *"Look at my workflow `anime_girl.json` and recreate it with more realistic characters. Produce a refreshed workflow and pick the models I need to download."*
- *"My workflow has red nodes: FaceDetailer, UltralyticsDetectorProvider. What do I install?"*
- *"Wan 2.2 i2v runs out of memory on my 16 GB card. What should I change?"*
- *"Find the 3 best realistic SDXL checkpoints, compare them, and show download links."*
- *"Build me an inpainting workflow from a template using juggernautXL_ragnarok."*

You can drag a workflow `.json` or `.png` onto the page to upload it. Every tool the assistant uses appears as a small line you can click to open, showing exactly what it looked up and what came back. When it wants to save, download or queue something, a yellow box with **Yes, do it / No** appears.

### How a remake works
1. **Summarize** the workflow: model family, checkpoint, LoRAs, prompts, sampler, sizes, missing nodes and models.
2. **Propose** a plan: what to swap, remove and add, the new settings and the new prompts.
3. **Look up real models** for the new style (Civitai/CivArchive, Hugging Face), with exact file names, sizes and hashes, and check what you already have on disk.
4. **Edit a copy** (a "draft"). Your file stays as it is.
5. **Validate** the draft against your installed nodes: wrong node names, broken links, bad values and missing models. It fixes any errors.
6. **Save** it as a new file in `generated\` after you click Yes, then offer the downloads (each needs a Yes too).

In ComfyUI, open the new file with *Workflow → Open* or drag it onto the window.

## Prompt Artist: picture -> expert prompt (and "Fix my result")

Give it any picture (anime, illustration, render or photo) and it writes a detailed, ready-to-paste prompt.

1. Start the AI brain (`start-llama.bat`, which loads the vision add-on `--mmproj` when your model has one) and `run.bat`.
2. In the chat page, click **🎨 Prompt Artist: image → prompt** in the sidebar, or drag a picture onto the page. PNG, JPG, WEBP, BMP and GIF all work.
3. Optional: type a wish when it asks (for example "make it Pony" or "make her outfit red").
4. You get back:
   - **1 Image analysis**: subject, style and Danbooru tags, plus its confidence and which model probably made the picture.
   - **2 Best model**: Pony, Illustrious/WAI, NoobAI, Animagine, SDXL, SD 1.5, Flux, Chroma or Qwen-Image, using your installed checkpoints first.
   - **3 Prompt**: positive, negative and settings (sampler, steps, CFG, size, clip skip).
   - **4 Runner-up**: a prompt for a second model family.
   - **5 Tips**.

**Fixing a picture that came out wrong**

1. Generate the picture in ComfyUI.
2. Click **🔧 Fix my result** and pick the picture. A ComfyUI PNG is best, because the prompt and settings are inside it.
3. Say what is wrong, for example "should be two girls" or "hair came out blue".
4. It compares your result with the original picture and finds the cause of each problem. It then gives a corrected prompt, a list of the changes, and what to try next (weights, inpaint, FaceDetailer, or another model).
5. Click **✅ This fixed it** or **❌ Still wrong**.
   - **✅ This fixed it** makes each tentative lesson *confirmed*. Confirmed lessons are used first in every new chat.
   - **❌ Still wrong** marks the lessons as failed so they are not suggested again. Upload the next try and it continues from there.

Lessons are saved in `data\prompt_lessons.json`, one per model family. Duplicates are merged and the file keeps at most 200 lessons. Click **📚 What it has learned** to see them. If the main server cannot see images, Prompt Artist uses `vision.fallback_*` in `config.yaml`, for example a second server with a vision model.

## Saved chats

Every chat is saved on your PC as you go, so you can close the app or the browser tab and come back later.

- **Where:** `data\chats\` in this folder. Each chat is one `.json` file, and its pictures and uploaded workflows are kept in a folder with the same name.
- **The list:** the **💬 Saved chats** panel on the left shows your chats, newest first, grouped by day. Type in **🔍 Search chats** to find one by its title or by any words in it. Click **☰** to hide or show the panel.
- **Open:** click a chat. You see the whole conversation again, with thumbnails, and the assistant remembers it, so you can say things like "here's what the workflow you made produced".
- **New:** click **＋ New chat**. It is saved when you send the first message. The title is made from that first message.
- **Rename:** click ✏️ (or double-click the title), type a new name, then press Enter.
- **Delete:** click 🗑 and confirm. The chat and its pictures are securely erased: each file is overwritten with random bytes and then deleted. You can't undo this.
- When you start the app, the chat you used last opens again.
- Very long chats: the assistant only sends the newest part of a long chat to the model, so it fits the model's memory (`-c` in `start-llama.bat`). The whole chat stays saved on disk.
- Chats from before this feature (in `cache\sessions\`) were copied into the list once, the first time the new version started. The old files are not changed.

## Civitai in blocked countries (e.g. the UK), and other sites

**Civitai blocks visitors from some countries (e.g. the UK)**, including its API and downloads. The helper notices this and switches on its own to **CivArchive** (civitaiarchive.com). CivArchive has the same model data plus **mirror links**, mostly Hugging Face copies. Mirror file names can differ from the original. The helper uses the SHA256 from Civitai to check that a mirror really is the same file. Tensor.Art and SeaArt have no public download API, so the helper reads their archived pages and tells you when you must download something yourself in the browser. The full list of alternatives is in the knowledge pack (`sites_mirrors`), taken from the civitai-mirror-list.

## Keys (optional) in `.env`

| Key | What for | Where to get it |
|---|---|---|
| `HF_TOKEN` | gated Hugging Face repos (e.g. original Flux.1-dev) | huggingface.co → Settings → Access Tokens (read) |
| `CIVITAI_API_KEY` | login-only Civitai downloads (where Civitai is available) | civitai.com → Account settings → API Keys |
| `GITHUB_TOKEN` | more GitHub searches per minute | github.com → Settings → Developer settings → Tokens |

Keys are sent only to their own site and never to the model or into the chat.

## What's inside

```
comfy-expert/
  run.bat  setup.bat  run-cli.bat  run-mcp.bat  (start-llama.bat is written by the setup kit)
  config.example.yaml  .env.example  requirements.txt  README.md
  comfy_expert/
    agent.py        - the chat loop (tool calling, playbook router, self-check, Yes/No gating)
    cli.py          - terminal chat and subcommands (chat, ask, tools, tool, doctor, web, mcp)
    mcp_server.py   - MCP server (stdio / streamable HTTP / SSE)
    web/            - the browser chat page (FastAPI on 127.0.0.1:7860)
    tools/          - 36 tools: ComfyUI, workflows, Prompt Artist (image -> prompt, lessons), Civitai/CivArchive, Hugging Face, web/GitHub search, downloads, knowledge
    knowledge/      - the knowledge pack (markdown) + 7 playbooks
    templates/      - 6 validated starter workflows
    data/           - built-in node list from ComfyUI 0.34 (used when ComfyUI is not running)
  scripts/          - template builder, knowledge-pack node-name checker
  tests/            - automated tests
```

**Knowledge pack topics:**
- comfyui_basics, core_nodes, model_families, samplers_settings, pipelines, anime_to_realistic, prompts_guide, model_folders
- amd_rocm_16gb, troubleshooting
- sites_civitai, sites_huggingface, sites_tensorart_seaart, sites_mirrors

**Playbooks:**
- explain_workflow, remake_workflow, find_models, fix_missing_nodes, build_from_template, troubleshoot, compare_models

**Templates:**
- `sdxl_txt2img`, `sdxl_img2img`, `sdxl_inpaint`
- `sdxl_facedetailer_upscale` (needs Impact Pack + Impact Subpack)
- `sdxl_ipadapter_character` (needs ComfyUI_IPAdapter_plus)
- `qwen_image_edit_2511_gguf` (needs ComfyUI-GGUF; useful for "make this anime picture realistic")

Each template carries its verified model download links.

**Command line examples:**
```bat
.venv\Scripts\python.exe -m comfy_expert tools                       & rem list tools
.venv\Scripts\python.exe -m comfy_expert tool summarize_workflow "{\"source\": \"my.json\"}"
.venv\Scripts\python.exe -m comfy_expert ask "which sampler for Z-Image Turbo?"
```

---

## MCP server (for OpenHands, Claude Desktop, LM Studio and other agent apps)

The same 36 tools are offered over the **Model Context Protocol**, using the official Python `mcp` SDK. The knowledge pack and playbooks are available both as tools (`kb_search`, `kb_read`, `get_playbook`) and as MCP resources (`comfy-expert://kb/<topic>`, `comfy-expert://playbook/<name>`). In the MCP version, the three "action" tools (`write_workflow`, `download_file`, `comfy_queue_test`) are **dry runs unless called with `confirm=true`**. Keep the agent app's own confirmation mode on.

| Transport | Start | Address |
|---|---|---|
| stdio | `.venv\Scripts\python.exe -m comfy_expert mcp` | the app starts the command itself |
| Streamable HTTP (recommended) | `run-mcp.bat` (binds 127.0.0.1:8765; add `--host 0.0.0.0` for Docker) | `http://127.0.0.1:8765/mcp`, from Docker `http://host.docker.internal:8765/mcp` |
| SSE (older apps) | `run-mcp.bat --transport sse --host 0.0.0.0` | `http://host.docker.internal:8765/sse` |

**`host.docker.internal`:** inside a Docker container, `127.0.0.1` means the container itself, not your PC. Docker Desktop provides the name `host.docker.internal`, which points to your Windows PC. That's why the MCP server and llama-server must listen on `0.0.0.0` (all network cards) instead of `127.0.0.1` when used from Docker. When you do that, set a token (`MCP_TOKEN=...` in `.env`) and don't open port 8765 or 8080 in your router. Windows Firewall may ask once; allow *Private networks* only.

### Using with OpenHands on Windows

1. **Install Docker Desktop** with the **WSL 2** backend (Docker Desktop → Settings → General → *Use the WSL 2 based engine*). Make sure `docker run hello-world` works in PowerShell.
2. **Start llama-server so Docker can reach it**: add `--host 0.0.0.0` to your command (keep `--jinja -c 32768` or more; OpenHands needs at least ~22k context, and 32768 is recommended).
3. **Start the MCP server**: double-click `run-mcp.bat`. It should say `... on http://127.0.0.1:8765/mcp - from Docker use http://host.docker.internal:8765/mcp`.
4. **Start OpenHands** (PowerShell, one line):
   ```powershell
   docker run -it --rm --pull=always -e AGENT_SERVER_IMAGE_REPOSITORY=ghcr.io/openhands/agent-server -e AGENT_SERVER_IMAGE_TAG=1.26.0-python -e LOG_ALL_EVENTS=true -v /var/run/docker.sock:/var/run/docker.sock -v ~/.openhands:/.openhands -p 3000:3000 --add-host host.docker.internal:host-gateway --name openhands-app docker.openhands.dev/openhands/openhands:1.8
   ```
   Then open <http://localhost:3000>. Image tags change often; if this one fails, copy the current command from docs.openhands.dev.
5. **Connect your local model**: Settings → LLM → *Advanced*:
   - **Custom Model:** `openai/<model name>`. Use the name llama-server reports at `http://127.0.0.1:8080/v1/models`, or start llama-server with `--alias qwen27b` and use `openai/qwen27b`.
   - **Base URL:** `http://host.docker.internal:8080/v1`
   - **API Key:** any dummy text, e.g. `local-llm` (llama-server ignores it unless you started it with `--api-key`).
6. **Add the MCP server**: Customize → MCP Servers → *Add custom server* → **SHTTP**:
   - **URL:** `http://host.docker.internal:8765/mcp`
   - **Authentication:** *Bearer token* with your `MCP_TOKEN` (or *None* if you didn't set one)
   - **Timeout:** 300 seconds, because downloads and searches can be slow.

   OpenHands saves this in `~/.openhands/settings.json`. Older guides use a `config.toml` `[mcp]` section, which was removed in 2026. If you use the **OpenHands CLI** instead of the web app, use `openhands mcp add` or `~/.openhands/mcp.json` with the stdio command:
   ```json
   {"mcpServers": {"comfyui-expert": {"command": "C:\\path\\to\\comfy-expert\\.venv\\Scripts\\python.exe",
                                      "args": ["-m", "comfy_expert", "mcp"],
                                      "env": {"COMFY_EXPERT_CONFIG": "C:\\path\\to\\comfy-expert\\config.yaml"}}}}
   ```
7. In the OpenHands chat, try: *"Use the comfyui-expert tools: summarize my workflow X and propose a realistic remake."*

**Reality check:** OpenHands sends a very long system prompt and many tools, so it needs a strong model with a large context. **The 27B Qwen with `-c 32768` (better 65536) is the realistic minimum.** Smaller models get lost. For day-to-day ComfyUI work the built-in chat page (`run.bat`) is simpler and works better with local models, because its prompts and playbooks are made for this job.

---

## Troubleshooting

- **"Cannot reach llama-server"**: start llama-server first, and check the port in `config.yaml` (`llm.base_url`).
- **The model answers but never uses tools**: start llama-server with `--jinja`. Some GGUFs need a newer llama.cpp build for tool calling.
- **"Context too small" / answers get confused in long chats**: use a bigger `-c`, or press **+ New chat**.
- **ComfyUI shows "not running"**: everything still works with the built-in node list from ComfyUI 0.34, but your custom nodes are only known when ComfyUI is running. Start it for the best checks.
- **Workflows with subgraphs**: can be read, explained and edited, but the helper can't convert them for a test run. Open them in ComfyUI and use *Export (API)* if needed.
- **Downloads from Civitai fail**: expected in countries where Civitai is blocked. Use the mirror links it offers, or a Hugging Face copy.

## Known limits

- Answer quality depends on the local model (see the note at the top).
- When ComfyUI is off, some checks are warnings instead of errors, because the built-in node list may differ from your installed versions.
- The workflow tools read settings and prompts, not pixels. Prompt Artist can look at pictures only when the model has a vision add-on (mmproj).
- Tensor.Art/SeaArt-only models with downloads switched off have to be downloaded by hand in the browser.
- Web search uses DuckDuckGo through the `ddgs` package and can be rate-limited. You can set your own SearXNG in `config.yaml`.
- Test generations (`comfy_queue_test`) convert the workflow for ComfyUI's API. A few unusual nodes (3D, painter, some frontend-only widgets) may not convert perfectly. Run those in ComfyUI directly.
- Small models tend to batch steps that depend on each other (edit → validate → save in one go) and to loop on searches. The helper catches both, but the job may then end with "ask me to continue". A 27B model rarely does this.

---

Built by Florence for the community.
