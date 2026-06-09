---
name: logo-to-keychain
description: Turn a logo, wordmark, or flat cartoon into a print-ready MULTI-COLOUR keychain — a watertight STL plus a Bambu Studio .3mf with each colour pre-assigned to a filament. Use when the user wants a keychain, charm, tag, badge, fridge magnet, or pendant from a logo/brand mark, or a mascot charm from a photo/cartoon. Uses direct geometric extrusion (NOT Meshy) so flat designs print clean and watertight.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
argument-hint: [logo-image-path]
---

# Logo → Keychain

Turn a brand logo (or a flat cartoon character) into a **print-ready, multi-colour keychain**. Output per design: a single-colour `.stl` and a **Bambu Studio `.3mf`** where every colour is already assigned to a filament (AMS multi-colour), plus a preview PNG.

**Why not Meshy?** Meshy image-to-3D is for *organic/sculptural* objects and prints rough (not watertight, no flat back). Flat logo/charm keychains should be **extruded** — exact edges, watertight, flat-backed, and cleanly separable into colours. (For sculptural figurines use the `meshy-3d-print` skill instead.)

## Engine

Everything runs through `scripts/keychain.py` (pure local Python, no API keys).

```
pip install numpy pillow opencv-python shapely trimesh manifold3d mapbox_earcut
```

## Two modes

### 1) logo mode — a logo/wordmark on a shaped tag
```bash
python scripts/keychain.py --mode logo \
  --image LOGO.png --style baseball --tagline "BESTGUY.AI" \
  --base-color "#141414" --logo-color "#F2F1ED" --accent-color "#D43122" \
  --width 70 --name mybrand --out ./keychains
```
- **Logo input:** a PNG with a transparent background is ideal; a clean white-background logo also works (white is keyed out automatically).
- **`--style`** (9): `baseball` (round patch + ring + arched tagline), `circle` (medallion), `tag` (rounded rectangle), `dogtag` (tall, top hole), `hexagon`, `shield`, `diecut` (the wordmark *is* the shape), `triangle`, `squircle`.
- **Colours:** `--base-color` (plate + loop), `--logo-color` (raised logo), `--accent-color` (ring / tagline / triangle). Use the brand's palette.
- **`--tagline`** optional; arched on `baseball`/`circle`, straight on the rest.

### 2) mascot mode — a flat cartoon → layered charm
First make a **flat, bold, 3–4 solid-colour cartoon** on a pure-white background (the `gpt2-image` skill in edit mode on a photo works great: "flat vector cartoon mascot, thick black outline, EXACTLY four flat colours, no gradients, pure white background"). Then:
```bash
python scripts/keychain.py --mode mascot \
  --image cartoon.png --palette "#141414,#5F632F,#EBD6AA,#D43122" \
  --width 70 --name mascot --out ./keychains
```
It keys out the white background, k-means-clusters the flat colours, snaps them to `--palette` (first = darkest/base layer), and builds a layered charm (base silhouette + each colour raised on top). Speckle smaller than ~3 mm² is dropped automatically.

## Recommended flow when a user asks for a keychain

1. **Get the logo.** Ask for a transparent PNG (or grab it from their site/store). If only a busy/coloured image exists, isolate the mark first.
2. **Pick palette + style.** Default to the brand colours. If unsure which shape, build a few styles or use `AskUserQuestion`. To offer a **chooser set**, run several `--style` values and montage the previews.
3. **Build**, then **show the preview PNG** and confirm before they print.
4. **Hand over** the `.3mf` (open in Bambu Studio — colours pre-assigned to filaments 1/2/3 in the order base, logo, accent) and the `.stl`.

## Print notes (tell the user)
- Prints **flat, back down, no supports** (loop hole is vertical; relief rises from the plate).
- Defaults: 3 mm base + 2 mm relief = 5 mm total. 0.2 mm layers (0.12 for crisp small text), ~15 % infill.
- In Bambu set AMS slots in the file's colour order; the parts are pre-tagged to filaments. (Single-extruder: add a colour change at the base-top Z in Preview.)
- Scale freely in the slicer — geometry is watertight.

## Tips learned
- Keep small text bold and ≥ ~0.8 mm stroke at final size, or it won't print cleanly.
- For 3-colour designs put each colour on a **separate part** (this skill does) — never rely on height-based colour when colours share a Z.
- The loop is unioned into the base with a through-hole so the whole thing is one piece and needs no supports.

See `examples/` for a 10-style showcase, a 2-colour logo charm, and a mascot charm.
