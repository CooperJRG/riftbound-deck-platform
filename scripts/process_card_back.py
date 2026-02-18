#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _shift_bool(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    h, w = mask.shape
    out = np.zeros_like(mask)
    ys = slice(max(0, dy), h + min(0, dy))
    xs = slice(max(0, dx), w + min(0, dx))
    src_y = slice(max(0, -dy), h - max(0, dy))
    src_x = slice(max(0, -dx), w - max(0, dx))
    out[ys, xs] = mask[src_y, src_x]
    return out


def _shift_rgb(arr: np.ndarray, dy: int, dx: int) -> np.ndarray:
    h, w, _ = arr.shape
    out = np.zeros_like(arr)
    ys = slice(max(0, dy), h + min(0, dy))
    xs = slice(max(0, dx), w + min(0, dx))
    src_y = slice(max(0, -dy), h - max(0, dy))
    src_x = slice(max(0, -dx), w - max(0, dx))
    out[ys, xs] = arr[src_y, src_x]
    return out


def _clean_alpha(alpha: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    brightness = rgb.astype(np.uint16).sum(axis=2)
    fringe = (alpha <= 36) & (alpha > 0) & (brightness >= 680)
    alpha = alpha.copy()
    alpha[fringe] = 0

    alpha_im = Image.fromarray(alpha, mode="L")
    eroded = np.array(alpha_im.filter(ImageFilter.MinFilter(3)))
    feather = np.array(Image.fromarray(eroded, mode="L").filter(ImageFilter.GaussianBlur(0.85)))

    # Keep interior fully opaque; only feather the silhouette edge.
    final_alpha = feather
    final_alpha[alpha >= 245] = 255
    final_alpha[(alpha <= 6)] = 0
    return final_alpha.astype(np.uint8)


def _decontaminate_edge_colors(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    known = alpha >= 176
    target = (alpha > 0) & (alpha < 176)
    unknown = target & (~known)

    directions = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    )

    for _ in range(18):
        if not np.any(unknown):
            break
        sum_rgb = np.zeros_like(out, dtype=np.uint32)
        sum_count = np.zeros(alpha.shape, dtype=np.uint16)

        for dy, dx in directions:
            k = _shift_bool(known, dy, dx)
            c = _shift_rgb(out, dy, dx)
            sum_rgb += c.astype(np.uint32) * k[..., None]
            sum_count += k.astype(np.uint16)

        can_fill = unknown & (sum_count > 0)
        if not np.any(can_fill):
            break
        out[can_fill] = (sum_rgb[can_fill] / sum_count[can_fill, None]).astype(np.uint8)
        known[can_fill] = True
        unknown = target & (~known)

    return out


def clean_card_back(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    arr = np.array(rgba)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    cleaned_alpha = _clean_alpha(alpha, rgb)
    cleaned_rgb = _decontaminate_edge_colors(rgb, cleaned_alpha)

    out = np.dstack([cleaned_rgb, cleaned_alpha]).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


def _hue_shift_rgba(im: Image.Image, hue_degrees: float) -> Image.Image:
    rgba = np.array(im.convert("RGBA")).astype(np.uint8)
    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    alpha = rgba[:, :, 3:4]

    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    diff = mx - mn

    h = np.zeros_like(mx)
    s = np.where(mx == 0, 0, diff / np.maximum(mx, 1e-8))
    v = mx

    mask = diff != 0
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]

    idx = mask & (mx == r)
    h[idx] = ((g[idx] - b[idx]) / diff[idx]) % 6
    idx = mask & (mx == g)
    h[idx] = ((b[idx] - r[idx]) / diff[idx]) + 2
    idx = mask & (mx == b)
    h[idx] = ((r[idx] - g[idx]) / diff[idx]) + 4
    h = h / 6.0

    h = (h + (hue_degrees / 360.0)) % 1.0

    c = v * s
    x = c * (1 - np.abs(((h * 6) % 2) - 1))
    m = v - c

    z = np.zeros_like(h)
    hp = h * 6

    out_rgb = np.zeros_like(rgb)
    conds = [
        (0 <= hp) & (hp < 1),
        (1 <= hp) & (hp < 2),
        (2 <= hp) & (hp < 3),
        (3 <= hp) & (hp < 4),
        (4 <= hp) & (hp < 5),
        (5 <= hp) & (hp < 6),
    ]
    vals = [
        (c, x, z),
        (x, c, z),
        (z, c, x),
        (z, x, c),
        (x, z, c),
        (c, z, x),
    ]
    for cond, (rc, gc, bc) in zip(conds, vals):
        out_rgb[:, :, 0] = np.where(cond, rc, out_rgb[:, :, 0])
        out_rgb[:, :, 1] = np.where(cond, gc, out_rgb[:, :, 1])
        out_rgb[:, :, 2] = np.where(cond, bc, out_rgb[:, :, 2])
    out_rgb = (out_rgb + m[:, :, None]) * 255.0
    out_rgb = np.clip(out_rgb, 0, 255).astype(np.uint8)

    out = np.dstack([out_rgb, alpha])
    return Image.fromarray(out, mode="RGBA")


def _apply_subtle_noise(im: Image.Image, *, strength: float, rng: random.Random) -> Image.Image:
    arr = np.array(im.convert("RGBA")).astype(np.int16)
    h, w, _ = arr.shape
    noise = rng.normalvariate(0.0, 1.0)
    # Use deterministic numpy RNG from python RNG seed to keep reproducible outputs.
    np_rng = np.random.default_rng(int((noise + 10) * 1_000_000) & 0xFFFFFFFF)
    grain = np_rng.normal(0.0, strength, size=(h, w, 1))
    alpha_mask = (arr[:, :, 3:4] > 0).astype(np.int16)
    arr[:, :, :3] = arr[:, :, :3] + (grain * alpha_mask).astype(np.int16)
    arr[:, :, :3] = np.clip(arr[:, :, :3], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


def _apply_vignette(im: Image.Image, *, amount: float, rng: random.Random) -> Image.Image:
    arr = np.array(im.convert("RGBA")).astype(np.float32)
    h, w, _ = arr.shape
    y = np.linspace(-1.0, 1.0, h, dtype=np.float32)
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    radius = np.sqrt(xx * xx + yy * yy)
    edge = np.clip((radius - 0.52) / 0.58, 0.0, 1.0)
    power = 1.2 + rng.random() * 1.0
    v = 1.0 - (amount * np.power(edge, power))
    alpha_mask = (arr[:, :, 3:4] > 0).astype(np.float32)
    arr[:, :, :3] *= (v[:, :, None] * alpha_mask + (1.0 - alpha_mask))
    arr[:, :, :3] = np.clip(arr[:, :, :3], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


@dataclass(frozen=True)
class VariantSpec:
    brightness: float
    contrast: float
    color: float
    sharpness: float
    hue_shift_deg: float
    noise_strength: float
    vignette: float


def make_variant(base: Image.Image, *, rng: random.Random) -> Image.Image:
    spec = VariantSpec(
        brightness=rng.uniform(0.975, 1.035),
        contrast=rng.uniform(0.97, 1.05),
        color=rng.uniform(0.985, 1.03),
        sharpness=rng.uniform(0.96, 1.06),
        hue_shift_deg=rng.uniform(-2.4, 2.4),
        noise_strength=rng.uniform(1.8, 3.4),
        vignette=rng.uniform(0.04, 0.085),
    )

    im = _hue_shift_rgba(base, spec.hue_shift_deg)
    im = ImageEnhance.Brightness(im).enhance(spec.brightness)
    im = ImageEnhance.Contrast(im).enhance(spec.contrast)
    im = ImageEnhance.Color(im).enhance(spec.color)
    im = ImageEnhance.Sharpness(im).enhance(spec.sharpness)
    im = _apply_subtle_noise(im, strength=spec.noise_strength, rng=rng)
    im = _apply_vignette(im, amount=spec.vignette, rng=rng)
    return im


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean alpha edges on a card-back PNG and generate subtle visual variants."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input RGBA PNG path.",
    )
    parser.add_argument(
        "--output-dir",
        default="images/processed/card_backs",
        help="Output directory.",
    )
    parser.add_argument(
        "--variants",
        type=int,
        default=12,
        help="Number of non-identical variants to generate.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260217,
        help="Random seed for reproducible variants.",
    )
    parser.add_argument(
        "--export-768x1024",
        action="store_true",
        help="Also export resized clean + variants at 768x1024.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    in_path = Path(args.input).resolve()
    out_dir = Path(args.output_dir).resolve()
    var_dir = out_dir / "variants"
    var_resized_dir = out_dir / "variants_768x1024"
    out_dir.mkdir(parents=True, exist_ok=True)
    var_dir.mkdir(parents=True, exist_ok=True)
    if args.export_768x1024:
        var_resized_dir.mkdir(parents=True, exist_ok=True)

    src = Image.open(in_path).convert("RGBA")
    clean = clean_card_back(src)

    clean_path = out_dir / "card_back_clean.png"
    clean.save(clean_path, optimize=True)

    if args.export_768x1024:
        clean.resize((768, 1024), Image.LANCZOS).save(out_dir / "card_back_clean_768x1024.png", optimize=True)

    rng = random.Random(args.seed)
    for idx in range(1, max(1, int(args.variants)) + 1):
        v = make_variant(clean, rng=rng)
        v_path = var_dir / f"card_back_variant_{idx:02d}.png"
        v.save(v_path, optimize=True)
        if args.export_768x1024:
            v.resize((768, 1024), Image.LANCZOS).save(
                var_resized_dir / f"card_back_variant_{idx:02d}_768x1024.png",
                optimize=True,
            )

    print(f"Input: {in_path}")
    print(f"Clean: {clean_path}")
    print(f"Variants: {max(1, int(args.variants))} -> {var_dir}")
    if args.export_768x1024:
        print(f"Resized variants: {var_resized_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

