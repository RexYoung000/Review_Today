# Body texture production

Built-in imagegen; edit target `../../motion/sprite.png` (the V3 temporary source). No CLI/API key used. Selected output copied as `body-source.png`. Eyes/fragment are code-native SVG parts, constructed to follow the temporary reference's proportions.

Selected prompt:

> Animation layer edit: erase ONLY the two white eye shapes and their pupils, and fill those small holes with matching opaque teal. The original image already has true transparent alpha. KEEP THAT ALPHA AND EVERY OUTLINE PIXEL UNCHANGED. This is NOT background removal: do not regenerate or feather the outline. Output RGBA PNG with sharp antialiased original edge, fully opaque body, and completely invisible exterior. Exact same original framing and aspect ratio. Absolutely no glow, halo, haze, shadow, background, checkerboard, new face or change to silhouette. Preserve the attached character, just remove its eyes.

The model did not satisfy the requested alpha channel: inspected output is 1254×1254 RGB. An earlier output contained a baked checkerboard; a second had unwanted halo/shape drift, both rejected. The selected opaque texture is used only inside the measured mesh hull, never as a transparent full-image sprite. We did not silently claim alpha preservation or pixel-identical reconstruction. Body source pixels are unchanged after generation; mesh geometry/UVs determine the visible area.
