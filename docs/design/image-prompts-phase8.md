# SupplyLens image prompts (Phase 8)

Use these in ChatGPT image generation. Save the results in the repo at `design/source-assets/supplylens/` and let the
coding session integrate them (WP-ART). In the repo, keep a copy of this file at `docs/design/image-prompts-phase8.md`.

## Which images and why

| ID | File name | Where it shows | Size | Background |
|---|---|---|---|---|
| A02 | `sl-import-data.png` | Data admission, no batches yet (withheld today, D-040) | 1024×1024 | transparent |
| A13 | `sl-empty-suppliers.png` | Supplier market, no suppliers (withheld today) | 1024×1024 | transparent |
| A16 | `sl-empty-value-study.png` | Value, nothing measured yet (withheld today) | 1024×1024 | transparent |
| A17 | `sl-empty-extraction.png` | Policies › Extracted terms, nothing extracted yet (new in Phase 8) | 1024×1024 | transparent |
| A18 | `sl-assistant-ready.png` | Status assistant drawer, first use (new in Phase 8) | 1024×1024 | transparent |
| D01 | `deck-title.png` | Title slide | 1536×864 (or 1536×1024, crop to 16:9) | opaque, light |
| D02 | `deck-outcome-a.png` | Section divider: optimise operations | 1536×864 | opaque, light |
| D03 | `deck-outcome-b.png` | Section divider: supply chain and logistics | 1536×864 | opaque, light |
| D04 | `deck-outcome-c.png` | Section divider: responsible AI | 1536×864 | opaque, light |
| D05 | `deck-outcome-d.png` | Section divider: generative AI | 1536×864 | opaque, light |
| D06 | `deck-closing.png` | Closing slide, UAE context | 1536×864 | opaque, light |

Do **not** generate: charts, graphs, architecture diagrams, screenshots, dashboards, maps, data, or people. Use real
screenshots, charts from the metrics files, and Mermaid diagrams for those.

## How to do it in ChatGPT (step by step)

1. Open a **new chat** for each batch (A-series in one chat, D-series in another).
2. Attach 3 style references from `design/source-assets/supplylens/`: `sl-empty-research.png`,
   `sl-forecast-setup.png`, `sl-policy-change.png`. First message: *"These are my style references. Match their style,
   materials, colours and lighting exactly in every image I ask for."*
3. For each image, paste the **style block** below, then the **asset prompt**. One image per message.
4. Ask for the size in the table and a **transparent PNG** for the A-series. Transparency support differs between
   image models. If you get a solid background, reply: *"Same image, fully transparent background, PNG."* If it is still
   solid, ask for a flat `#F4F8F6` background and remove it with a background-removal tool, then check the edges.
5. Check the image against the acceptance list. If it fails, say exactly what is wrong (for example *"remove the lines
   on the paper; the sheets must be blank"*) and regenerate.
6. Save with the exact file name from the table. Put A-series files in `design/source-assets/supplylens/` and D-series
   files in `docs/course/images/`.
7. Approve the images as the owner, then tell the coding session to run WP-ART.
8. Add one line to `docs/course/ai-use-statement.md`: which images were generated with ChatGPT and that you checked them.
   This is required by the school's academic-integrity policy.

## Style block (paste before every A-series prompt)

```text
Style: soft 3D clay render matching the attached references. Isometric three-quarter view from above. Matte surfaces,
rounded edges, soft studio light from the upper left, a gentle soft contact shadow. Palette only: deep teal #0F6B55,
mint #63C9A8, pale mint #DCEFE8, off-white #F4F8F6, light grey brushed metal. Simple shapes, few objects, calm and
clean. No text, letters, numbers, logos, symbols of currency, people, faces, hands, charts, graphs, tables, maps,
screens or user-interface elements. Transparent background. One object group centred within the middle 70 % of the
canvas with empty space around it. It must still read clearly when shown as a small 96 px icon. 1024×1024 PNG.
```

## A-series prompts (app empty states)

### A02 — Import data (`sl-import-data.png`)

```text
[style block]
Subject: an empty deep-teal intake tray seen from above, its clean pale-mint interior completely empty. Two or three
blank off-white sheets float just above the tray, shown by their edges only, perfectly blank with no lines, grid,
writing or chart. A short mint upward arrow stands beside the tray. Meaning: nothing has been imported yet, upload
here. No boxes, no cartons, no kraft brown.
```

### A13 — Empty suppliers (`sl-empty-suppliers.png`)

```text
[style block]
Subject: three small separate building blocks (simple teal and off-white supplier buildings with closed doors) standing
apart on a pale-mint ground. Each has a short mint connector stub pointing towards the others, but the stubs do NOT
meet and there are no lines between the buildings. Nothing in the doorways, no cartons, no vehicles. Meaning: no
supplier network recorded yet.
```

### A16 — Value study, nothing measured (`sl-empty-value-study.png`)

```text
[style block]
Subject: a neutral light-grey metal balance scale on a deep-teal base, both pans completely empty and perfectly level.
Beside it, an empty off-white ledger board with a blank surface. No coins, no cartons, no arrows, no kraft brown.
Meaning: nothing has been measured yet; it is not a comparison or a judgement.
```

### A17 — Nothing extracted yet (`sl-empty-extraction.png`)

```text
[style block]
Subject: one blank off-white document sheet standing upright on a small deep-teal reading stand, perfectly blank with
no lines or writing. A light-grey metal inspection lens leans against the stand. In front, three small empty pale-mint
slots on a teal base, like empty field holders, all empty. No cartons, no kraft brown. Meaning: no contract fields
have been extracted yet.
```

### A18 — Status assistant, first use (`sl-assistant-ready.png`)

```text
[style block]
Subject: a rounded, empty mint speech-bubble shape (no dots, no marks inside) resting on a small deep-teal base. Next to
it, a tiny two-shelf storage rack in teal and light-grey metal with one small plain kraft carton on the lower shelf.
Meaning: ask a question about an order or stock. Calm and friendly, not cartoonish.
```

## D-series prompts (presentation slides)

Paste this style block before every D-series prompt instead of the A-series one.

```text
Style: soft 3D clay miniature diorama matching the attached references, isometric three-quarter view from above, matte
materials, rounded edges, soft daylight from the upper left, gentle shadows, shallow depth of field. Palette: deep teal
#0F6B55, mint #63C9A8, pale mint #DCEFE8, off-white #F4F8F6, light grey metal, small accents of kraft brown for cartons
only. Background: a smooth, very light off-white to pale-mint gradient, opaque. Leave the LEFT 40 % of the image empty
and calm for slide text; place the subject in the right 60 %. No text, letters, numbers, logos, flags, people, faces,
charts, graphs, maps, screens or user-interface elements. 16:9, 1536×864.
```

### D01 — Title slide (`deck-title.png`)

```text
[deck style block]
Subject: a miniature open-roof warehouse with three clean rack modules holding a few plain cartons, and one large
light-grey metal inspection lens in the foreground looking into the warehouse. A fine mint path links the racks to a
small loading door. Generic architecture, elegant negative space.
```

### D02 — Outcome A, optimise operations (`deck-outcome-a.png`)

```text
[deck style block]
Subject: a miniature receiving floor: three small workstation blocks in a row joined by a smooth mint conveyor path,
with plain cartons moving along it in an orderly sequence, and a small teal scheduling board with blank sliding tiles
(no marks). Feeling: order, flow and efficiency.
```

### D03 — Outcome B, supply chain and logistics (`deck-outcome-b.png`)

```text
[deck style block]
Subject: a small unbranded teal delivery van leaving a miniature warehouse block along a gently curving mint road that
reaches three tiny off-white house blocks. A few plain cartons wait at the warehouse door. A single small green leaf
shape near the road suggests lower emissions. No people, no road signs, no logos.
```

### D04 — Outcome C, responsible AI (`deck-outcome-c.png`)

```text
[deck style block]
Subject: a deep-teal approval box with two separate key locks on its front and two light-grey metal keys, one in each
lock (two people must agree), beside a smooth rounded teal shield shape with a soft mint check mark groove. Calm,
trustworthy, no warning colours.
```

### D05 — Outcome D, generative AI (`deck-outcome-d.png`)

```text
[deck style block]
Subject: a blank off-white document sheet on a small teal stand with a light-grey inspection lens over one area; three
fine mint threads run from that area to a rounded empty mint speech-bubble shape, showing that the answer comes from
the document. The sheet and the bubble are completely blank.
```

### D06 — Closing, UAE context (`deck-closing.png`)

```text
[deck style block]
Subject: a miniature modern warehouse on a warm pale-sand base next to a small generic traditional wind-tower building
block (barjeel style, simple off-white clay), with one low mint palm-like plant. Warm late-afternoon light. Generic
architecture only: no real landmarks, no flags, no skyline of a specific city.
```

## Acceptance list (check every image)

- [ ] No text, letters, numbers, logos, people, charts, tables, maps or screens anywhere (zoom in to check).
- [ ] Matches the reference style: clay, matte, the teal/mint palette, same light direction.
- [ ] A-series: background really transparent (all four corners fully transparent), PNG, 1024×1024.
- [ ] A-series: subject inside the middle 70 %; still clear when shrunk to 96 px.
- [ ] A-series: reads well on both light `#F4F8F6` and dark `#0D1517` backgrounds (place it on both to check).
- [ ] The image says what its state means (empty means empty: no data, stock or network shown when there is none).
- [ ] D-series: left 40 % calm enough for slide text; 16:9; no fake data.
- [ ] Saved with the exact file name; generation noted in the AI-use statement.

Quick check you can run in the repo (Python with Pillow):

```python
from PIL import Image
for f in ["sl-import-data.png", "sl-empty-suppliers.png", "sl-empty-value-study.png",
          "sl-empty-extraction.png", "sl-assistant-ready.png"]:
    im = Image.open(f"design/source-assets/supplylens/{f}").convert("RGBA")
    w, h = im.size
    corners = [im.getpixel(p)[3] for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]]
    print(f, im.size, "corners alpha:", corners, "OK" if (w, h) == (1024, 1024) and max(corners) == 0 else "CHECK")
    for name, bg in [("light", (244, 248, 246, 255)), ("dark", (13, 21, 23, 255))]:
        canvas = Image.new("RGBA", im.size, bg); canvas.alpha_composite(im)
        canvas.resize((96, 96)).save(f"/tmp/{f[:-4]}-{name}-96.png")
```
