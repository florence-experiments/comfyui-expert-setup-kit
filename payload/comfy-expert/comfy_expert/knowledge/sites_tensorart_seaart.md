# Tensor.Art and SeaArt.ai

Both are Civitai-like model sites with online generators. Neither has a public model API for downloading, and many models are "online-only" (creator disabled download).

## Tensor.Art (tensor.art)
- Model page: `https://tensor.art/models/<numeric id>`. Shows base model, versions, trigger words, recommended settings; a Download button appears only if the creator allows it (login required).
- Many Tensor.Art models are copies of Civitai models; search the same name on Civitai/CivArchive/Hugging Face.
- archive_get_page(url) can read CivArchive's copy of a Tensor.Art model (`https://civitaiarchive.com/tensorart/models/...`) including mirror files; model_archive_search(platform="tensorart") searches them.
- fetch_url on tensor.art pages often fails (JavaScript app / bot protection) - use the archive or web_search.

## SeaArt.ai (seaart.ai)
- Model page: `https://www.seaart.ai/models/detail/<hex id>`. Large library of checkpoints/LoRAs, many re-uploads. Downloads need login and are often disabled.
- The mirror list notes SeaArt is a good place to find backups of models/LoRAs removed from Civitai.
- model_archive_search(platform="seaart") + archive_get_page for archived SeaArt entries.

## Workflow for both
1. Get the model name + base model from the page (or the user).
2. Look for the same model on Civitai (civitai_search_models -> falls back to CivArchive in the UK) and Hugging Face (hf_search_models).
3. If only on Tensor.Art/SeaArt: tell the user to download it manually in the browser (logged in), then put it in the right models folder. Never invent a direct link.
