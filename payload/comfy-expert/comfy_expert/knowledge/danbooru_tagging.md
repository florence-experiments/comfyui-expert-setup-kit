# Danbooru tagging guide (for anime SDXL families)
How to write tag prompts that Pony, Illustrious, WAI, NoobAI and Animagine understand. Tags are real Danbooru tags (check https://danbooru.donmai.us/wiki_pages/tag_groups). Prompts are lowercase and comma-separated.

## Spaces vs underscores, brackets
- Write tags with **spaces**: `long hair`, `looking at viewer`. Illustrious/NoobAI/Animagine were trained on space-separated tags; Pony accepts both. Keep underscores only in emoticon tags (`^_^`, `>_<`) and Pony meta tags (`score_9`, `source_anime`, `rating_safe`).
- Character tags have the form `name (series)` on Danbooru (`rem_(re:zero)`). In a ComfyUI/A1111 prompt, brackets mean weight, so **escape them**: `rem \(re:zero\)`, `hatsune miku`, `artoria pendragon \(fate\)`. Add the series tag too: `re:zero kara hajimeru isekai seikatsu`, `fate/grand order`.
- Weights: `(tag:1.2)`; valid range about 0.5-1.5. Above 1.4 it distorts. `[tag]` and `((tag))` also work in ComfyUI but are less precise.

## Tag order (most important first)
1. Family prefix (Pony score chain / NoobAI quality prefix; Illustrious-WAI and Animagine put quality LAST).
2. Count: `1girl`, `2girls`, `1boy`, `1other`, `multiple girls`, `no humans`, plus `solo` / `solo focus`.
3. Character, then series. 4. Artist (bare name, no "by", no "artist:"), or put it before the quality tags in Animagine.
5. General tags: hair (length, colour, style), eyes, face/expression, body, clothing top-down, accessories, pose/action, composition/camera, background, lighting, colour/style, rating.
6. Quality/meta tags at the end where the family wants them.

## Two or more people: BREAK sections
- With 2+ people, tags for one person's hair, eyes and clothes bleed onto the others. Split the positive with `BREAK` (on its own line): a **shared section** first (family prefix such as the Pony score chain, head count `2girls` / `1girl, 1boy`, `adult`, the shared action, scene, camera), then `BREAK` + **one section per person** (`girl on left` / `man on right`, `mature female` / `mature male`, distinct hair and eye colours, clothes, pose, role), then an optional `BREAK` + **shared ending** (lighting, style, and Illustrious/WAI/Animagine quality tags last). One person: BREAK is optional.
- `BREAK` must be in capitals. It works in H1 06 (ComfyUI-ppm `CLIPTextEncodeBREAK`, like A1111/Forge). In H1 01-05 or a plain `CLIPTextEncode` it is an ordinary word: remove it there. In H1 02 put each person's section in its own LEFT / RIGHT / CENTRE box instead (no BREAK).
- Never use BREAK in the negative.

## Category cheat sheet
- **Hair**: very long hair, long hair, medium hair, short hair; blonde/brown/black/white/grey/pink/blue/red/silver/multicolored/streaked/gradient hair; ponytail, twintails, side ponytail, braid, hair bun, double bun, bob cut, hime cut, ahoge, sidelocks, hair between eyes, blunt bangs, swept bangs, hair over one eye, hair ornament, hairclip, hair ribbon.
- **Eyes/face**: blue eyes, red eyes, heterochromia, slit pupils, glowing eyes, half-closed eyes, closed eyes, one eye closed, smile, grin, smirk, open mouth, closed mouth, blush, tears, frown, pout, :d, :o, tongue out, fang, looking at viewer, looking away, looking back, looking to the side.
- **Body**: (use only what is visible) breast size tags, curvy, muscular, muscular female, slim, abs, wide hips, thick thighs, dark skin, pale skin, tan, tanlines, freckles, mole under eye, animal ears, cat ears, fox ears, tail, horns, wings, elf, pointy ears.
- **Clothing**: name each garment with its colour: white shirt, collared shirt, black jacket, open jacket, serafuku, school uniform, pleated skirt, miniskirt, dress, sundress, kimono, maid, bikini, one-piece swimsuit, leotard, bodysuit, armor, thighhighs, pantyhose, zettai ryouiki, boots, high heels, gloves, elbow gloves, choker, necklace, earrings. State changes too: open clothes, clothes lift, skirt lift, off shoulder, wet clothes, see-through, torn clothes, partially undressed, nude, completely nude.
- **Pose/action**: standing, sitting, kneeling, lying, on back, on stomach, squatting, leaning forward, arms up, arms behind back, hand on hip, hands on own chest, outstretched arm, v, peace sign, holding (object), walking, running, jumping, dancing, from behind, spread legs, crossed legs.
- **Composition/framing**: portrait, upper body, cowboy shot (mid-thigh up), full body, close-up, feet out of frame, head out of frame, wide shot, very wide shot. **Camera**: from above, from below, from side, from behind, dutch angle, pov, straight-on, profile, three-quarter view, fisheye, foreshortening, depth of field, blurry background, bokeh, motion blur, chromatic aberration. Use one framing tag only.
- **Background**: simple background, white background, gradient background, outdoors, indoors, sky, cloud, night, starry sky, city, cityscape, street, classroom, bedroom, bathroom, beach, ocean, forest, field, flower field, cherry blossoms, ruins, cafe, scenery.
- **Lighting**: sunlight, dappled sunlight, backlighting, rim light, sunset, golden hour, light rays, god rays, lens flare, dark, night, moonlight, neon lights, cinematic lighting, dramatic lighting, soft lighting, glowing, shadow.
- **Style/medium**: anime coloring, cel shading, flat color, sketch, lineart, monochrome, greyscale, limited palette, watercolor (medium), oil painting (medium), traditional media, pixel art, realistic, photorealistic, 3d, 1990s (style), retro artstyle, chibi, comic, manga.
- **Text/marks**: speech bubble, english text, signature, watermark, artist name, web address. These go in the negative unless wanted.

## Ratings by family
- Pony: rating_safe / rating_questionable / rating_explicit. Illustrious, WAI, NoobAI: general / sensitive / nsfw / explicit. Animagine: safe / sensitive / nsfw / explicit.
- general = fully clothed, no sexual focus. sensitive = swimsuits, cleavage, suggestive. nsfw/questionable = nudity. explicit = sexual acts or exposed genitals.

## Common negatives
- Pony: optional. `score_4, score_5, score_6` plus unwanted things only.
- WAI: `bad quality, worst quality, worst detail, sketch, censor` (short).
- Illustrious base: `worst quality, bad quality, low quality, lowres, displeasing, very displeasing, bad anatomy, bad hands, extra digits, fewer digits, jpeg artifacts, signature, watermark, multiple views`.
- NoobAI: `worst quality, old, early, low quality, lowres, signature, username, logo, bad hands, mutated hands`.
- Animagine: the card negative (see image_model_families).
- Add only what you saw go wrong: `censored, mosaic censoring` for uncensored output; `3d, realistic` for a flat anime look; `monochrome, greyscale` for colour.
