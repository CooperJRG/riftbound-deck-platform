# Image Generation Prompt Pack: Skeuomorphic 90s/2000s UI

Date: 2026-02-17  
Status: Required asset specification

## Generation Rules (Apply To Every Prompt)

Base style:
- Photorealistic material textures.
- Neutral softbox lighting; no dramatic cinematic color grading.
- Clean, production-ready source assets for UI compositing.

Always include:
- No text
- No logos
- No watermarks
- No people
- No brand marks

Preferred export:
- PNG for assets with transparency.
- JPG or PNG for full-scene backgrounds.
- sRGB color space.

## Core Assets (Required)

## A01 - Main Desk Background (Desktop)

- Filename: `bg_desk_main_3840x2160.jpg`
- Dimensions: `3840 x 2160` (16:9)
- Prompt:
  - `top-down modern desktop scene, warm walnut wood desk with subtle grain, classic early-2000s premium software vibe, center area intentionally clean for UI placement, soft warm ambient light, slight vignetting on corners, photorealistic texture detail, no objects in center safe area, high clarity`
- Negative prompt:
  - `text, logos, watermark, people, keyboard, mouse, monitor, clutter, exaggerated bokeh, cartoon, illustration`
- Notes:
  - Keep center 55% area visually quiet for UI content.

## A02 - Main Desk Background (Laptop Fallback)

- Filename: `bg_desk_main_1920x1200.jpg`
- Dimensions: `1920 x 1200` (16:10)
- Prompt:
  - `same composition as A01, warm walnut desktop, clean center workspace, soft vintage desktop software atmosphere, photorealistic, minimal clutter, smooth tonal transitions`
- Negative prompt:
  - `text, logos, watermark, people, heavy props, cartoon look`

## A03 - Seamless Walnut Texture

- Filename: `tx_walnut_seamless_2048.png`
- Dimensions: `2048 x 2048` (1:1 tileable)
- Prompt:
  - `seamless walnut wood texture tile, medium-dark brown, subtle natural pores and grain, evenly lit, photorealistic, no directional hotspot, texture scan quality`
- Negative prompt:
  - `text, seams, perspective distortion, knots dominating center, scratches, dirt`

## A04 - Seamless Dark Leather Panel Texture

- Filename: `tx_leather_dark_seamless_2048.png`
- Dimensions: `2048 x 2048` (1:1 tileable)
- Prompt:
  - `seamless dark brown leather texture, fine grain, premium desk pad material, soft matte finish, evenly lit, photorealistic`
- Negative prompt:
  - `text, seams, folds, wrinkles, embossing, logos, stitching`

## A05 - Seamless Brushed Aluminum Texture

- Filename: `tx_aluminum_brushed_seamless_2048.png`
- Dimensions: `2048 x 2048` (1:1 tileable)
- Prompt:
  - `seamless brushed aluminum texture, subtle horizontal brush lines, cool silver-gray, clean industrial finish, evenly lit, photorealistic`
- Negative prompt:
  - `text, seams, rust, scratches, fingerprints, glare hotspot`

## A06 - Seamless Parchment/Paper Texture

- Filename: `tx_paper_warm_seamless_2048.png`
- Dimensions: `2048 x 2048` (1:1 tileable)
- Prompt:
  - `seamless warm off-white parchment paper texture, light fiber detail, slightly aged but clean, even soft lighting, photorealistic`
- Negative prompt:
  - `text, stains, torn edges, heavy blotches, seams`

## A07 - Glass Highlight Overlay Strip

- Filename: `ov_gloss_strip_2048x512.png`
- Dimensions: `2048 x 512` (transparent PNG)
- Prompt:
  - `transparent glossy highlight strip for UI panel overlay, soft white-to-transparent curved gradient, subtle specular sheen, no background`
- Negative prompt:
  - `text, color tint, hard edge, noise, banding`
- Notes:
  - Must include alpha transparency.

## A08 - Card Frame Overlay (Vertical)

- Filename: `ov_card_frame_768x1024.png`
- Dimensions: `768 x 1024` (3:4, transparent PNG)
- Prompt:
  - `transparent fantasy-tech card frame overlay, early-2000s collectible card game UI style, beveled metallic border, subtle inset shadow, top title bar area and bottom stat panel area, clean center cutout for artwork, high-detail but not ornate`
- Negative prompt:
  - `text, numbers, logos, watermark, character art, opaque center`
- Notes:
  - Center must remain transparent for card art insertion.

## A09 - Card Back Texture

- Filename: `card_back_skeuo_768x1024.png`
- Dimensions: `768 x 1024` (3:4)
- Prompt:
  - `collectible card back design, symmetrical, classic 2000s tcg aesthetic, deep navy and bronze tones, embossed ornamental geometry, no text, high detail, print-ready`
- Negative prompt:
  - `logos, letters, watermark, characters, asymmetrical composition`

## A10 - Metal Bezel Corner Pack

- Filename: `ui_bezel_corners_1024x1024.png`
- Dimensions: `1024 x 1024` (transparent PNG sprite sheet)
- Prompt:
  - `transparent UI bezel corner ornaments, brushed metal with soft highlights, four corner variants for panel framing, subtle shadowing, no background`
- Negative prompt:
  - `text, logos, rust, grunge, opaque background`
- Notes:
  - Prefer a sprite sheet with corners in each quadrant.

## A11 - Button Surface Texture (Primary)

- Filename: `tx_button_amber_1024x256.png`
- Dimensions: `1024 x 256`
- Prompt:
  - `skeuomorphic glossy amber button surface texture strip, soft vertical gradient, subtle bevel lighting, premium early-2000s software button style`
- Negative prompt:
  - `text, icon, logo, heavy reflections, noise`

## A12 - Button Surface Texture (Secondary Cool)

- Filename: `tx_button_slate_1024x256.png`
- Dimensions: `1024 x 256`
- Prompt:
  - `skeuomorphic cool slate-blue button surface texture strip, gentle bevel, satin sheen, classic desktop utility style`
- Negative prompt:
  - `text, icon, logo, harsh glare, noisy artifacts`

## Optional Polish Assets

## P01 - Fine Dust/Imperfection Overlay

- Filename: `ov_micro_dust_2048x2048.png`
- Dimensions: `2048 x 2048` (transparent PNG)
- Prompt:
  - `extremely subtle transparent dust and micro-speck overlay for realistic materials, almost imperceptible, clean and controlled`
- Negative prompt:
  - `heavy dirt, stains, text, scratches, high contrast spots`

## P02 - Inner Shadow Vignette Overlay

- Filename: `ov_inner_vignette_2048x2048.png`
- Dimensions: `2048 x 2048` (transparent PNG)
- Prompt:
  - `transparent inner vignette overlay, soft dark edges with clear center, suitable for panel depth effect, no background`
- Negative prompt:
  - `banding, hard edge, center darkening, text`

## P03 - Embossed Divider Strip

- Filename: `ui_divider_emboss_2048x128.png`
- Dimensions: `2048 x 128` (transparent PNG)
- Prompt:
  - `transparent embossed divider strip for classic software panel sections, subtle highlight and shadow ridge, clean and minimal`
- Negative prompt:
  - `text, icon, heavy ornament, background fill`

## Asset Placement Notes

Suggested folder:
- `web/assets/skeuo/`

Recommended mapping:
- Background scene: page body background layer.
- Seamless textures: panel and module surfaces via CSS backgrounds.
- Card frame overlay: card tile/popup mask layer.
- Gloss/vignette overlays: pseudo-elements for depth.
- Button textures: primary/secondary button backgrounds.

## Acceptance Checklist

1. No generated asset contains text, logos, or watermarks.
2. Seamless textures tile cleanly at 100%, 150%, and 200% zoom.
3. Transparent assets preserve alpha correctly.
4. Card frame overlay center is truly transparent.
5. Background safe area remains readable behind UI.

