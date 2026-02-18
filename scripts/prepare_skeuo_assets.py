#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
from typing import Iterable

from PIL import Image, ImageFilter


RESAMPLE = Image.Resampling.LANCZOS


@dataclass(frozen=True)
class AssetSpec:
    name: str
    sources: tuple[str, ...]
    output: str
    width: int
    height: int
    mode: str
    sharpen: bool = False
    refit_alpha_to_canvas: bool = False


CORE_SPECS: tuple[AssetSpec, ...] = (
    AssetSpec(
        name="desk-bg-16x10",
        sources=("images/bg_desk_main_1920x1200.png",),
        output="backgrounds/bg_desk_main_1920x1200.png",
        width=1920,
        height=1200,
        mode="cover",
        sharpen=True,
    ),
    AssetSpec(
        name="desk-bg-16x9",
        sources=("images/bg_desk_main_3840x2160.png",),
        output="backgrounds/bg_desk_main_3840x2160.png",
        width=3840,
        height=2160,
        mode="cover",
        sharpen=True,
    ),
    AssetSpec(
        name="walnut-tile",
        sources=("images/tx_walnut_seamless_2048.png",),
        output="textures/tx_walnut_seamless_2048.png",
        width=2048,
        height=2048,
        mode="resize",
        sharpen=True,
    ),
    AssetSpec(
        name="leather-tile",
        sources=("images/tx_leather_dark_seamless_2048.png",),
        output="textures/tx_leather_dark_seamless_2048.png",
        width=2048,
        height=2048,
        mode="resize",
        sharpen=True,
    ),
    AssetSpec(
        name="aluminum-tile",
        sources=("images/tx_aluminum_brushed_seamless_2048.png",),
        output="textures/tx_aluminum_brushed_seamless_2048.png",
        width=2048,
        height=2048,
        mode="resize",
        sharpen=True,
    ),
    AssetSpec(
        name="paper-tile",
        sources=("images/tx_paper_warm_seamless_2048.png",),
        output="textures/tx_paper_warm_seamless_2048.png",
        width=2048,
        height=2048,
        mode="resize",
        sharpen=True,
    ),
    AssetSpec(
        name="gloss-strip",
        sources=("images/ov_gloss_strip_2048x512.png",),
        output="overlays/ov_gloss_strip_2048x512.png",
        width=2048,
        height=512,
        mode="cover",
    ),
    AssetSpec(
        name="inner-vignette",
        sources=("images/ov_inner_vignette_2048x2048.png",),
        output="overlays/ov_inner_vignette_2048x2048.png",
        width=2048,
        height=2048,
        mode="cover",
    ),
    AssetSpec(
        name="micro-dust",
        sources=("images/ov_micro_dust_2048x2048.png",),
        output="overlays/ov_micro_dust_2048x2048.png",
        width=2048,
        height=2048,
        mode="cover",
    ),
    AssetSpec(
        name="divider-strip",
        sources=("images/ui_divider_emboss_2048x128.png",),
        output="overlays/ui_divider_emboss_2048x128.png",
        width=2048,
        height=128,
        mode="cover",
    ),
    AssetSpec(
        name="button-amber",
        sources=("images/tx_button_amber_1024x256.png",),
        output="buttons/tx_button_amber_1024x256.png",
        width=1024,
        height=256,
        mode="cover",
        refit_alpha_to_canvas=True,
    ),
    AssetSpec(
        name="button-slate",
        sources=("images/tx_button_slate_1024x256.png",),
        output="buttons/tx_button_slate_1024x256.png",
        width=1024,
        height=256,
        mode="cover",
        refit_alpha_to_canvas=True,
    ),
    AssetSpec(
        name="card-back-clean",
        sources=(
            "images/processed/card_backs/card_back_clean_tight_768x1024.png",
            "images/processed/card_backs/card_back_clean_768x1024.png",
            "images/card_back_skeuo_768x1024.png",
        ),
        output="card-backs/card_back_clean_768x1024.png",
        width=768,
        height=1024,
        mode="cover",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and normalize generated skeuomorphic assets into web/assets/skeuo."
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root path (default: current directory).",
    )
    parser.add_argument(
        "--output-dir",
        default="web/assets/skeuo",
        help="Output asset directory.",
    )
    parser.add_argument(
        "--manifest",
        default="web/assets/skeuo/manifest.json",
        help="Manifest JSON output path.",
    )
    parser.add_argument(
        "--card-variants",
        type=int,
        default=16,
        help="Target number of card-back variants to publish.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any required source asset is missing.",
    )
    return parser.parse_args()


def choose_source(project_root: Path, candidates: Iterable[str]) -> Path | None:
    for rel in candidates:
        path = (project_root / rel).resolve()
        if path.is_file():
            return path
    return None


def resize_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    if image.width == width and image.height == height:
        return image.copy()
    scale = max(width / image.width, height / image.height)
    resized_w = max(width, int(math.ceil(image.width * scale)))
    resized_h = max(height, int(math.ceil(image.height * scale)))
    resized = image.resize((resized_w, resized_h), RESAMPLE)
    left = max(0, (resized_w - width) // 2)
    top = max(0, (resized_h - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def resize_exact(image: Image.Image, width: int, height: int) -> Image.Image:
    if image.width == width and image.height == height:
        return image.copy()
    return image.resize((width, height), RESAMPLE)


def _median_bottom_edge(alpha: Image.Image, *, threshold: int) -> int | None:
    px = alpha.load()
    w, h = alpha.size
    bottoms: list[int] = []
    for x in range(w):
        y_found = -1
        for y in range(h - 1, -1, -1):
            if px[x, y] > threshold:
                y_found = y
                break
        if y_found >= 0:
            bottoms.append(y_found)
    if not bottoms:
        return None
    return int(median(bottoms))


def _refit_alpha_texture(image: Image.Image, width: int, height: int) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    bottom = _median_bottom_edge(alpha, threshold=8)
    if bottom is None:
        return resize_exact(rgba, width, height)

    w, h = rgba.size
    alpha_px = alpha.load()
    for y in range(bottom + 1, h):
        for x in range(w):
            alpha_px[x, y] = 0
    rgba.putalpha(alpha)

    mask = alpha.point(lambda p: 255 if p > 8 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return resize_exact(rgba, width, height)

    crop = rgba.crop(bbox)
    inset_x = max(8, int(round(width * 0.0215)))
    inset_y = max(6, int(round(height * 0.040)))
    inner_w = max(10, width - (inset_x * 2))
    inner_h = max(10, height - (inset_y * 2))
    fit = resize_cover(crop, inner_w, inner_h)

    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ox = (width - inner_w) // 2
    oy = (height - inner_h) // 2
    out.paste(fit, (ox, oy), fit)
    return out


def prepare_image(image: Image.Image, spec: AssetSpec) -> Image.Image:
    if spec.mode == "cover":
        prepared = resize_cover(image, spec.width, spec.height)
    elif spec.mode == "resize":
        prepared = resize_exact(image, spec.width, spec.height)
    else:
        raise ValueError(f"Unsupported mode: {spec.mode}")
    if spec.refit_alpha_to_canvas:
        prepared = _refit_alpha_texture(prepared, spec.width, spec.height)
    if spec.sharpen:
        prepared = prepared.filter(ImageFilter.UnsharpMask(radius=1.4, percent=80, threshold=2))
    return prepared


def save_image(image: Image.Image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, optimize=True)


def parse_variant_index(path: Path) -> int:
    stem = path.stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    if not digits:
        return 0
    return int(digits[-2:])


def process_core_specs(project_root: Path, out_root: Path, strict: bool) -> tuple[list[dict[str, object]], list[str]]:
    manifest_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for spec in CORE_SPECS:
        source = choose_source(project_root, spec.sources)
        if source is None:
            message = f"Missing source for {spec.name}: {', '.join(spec.sources)}"
            warnings.append(message)
            manifest_rows.append(
                {
                    "name": spec.name,
                    "status": "missing_source",
                    "sourcesTried": list(spec.sources),
                    "output": spec.output,
                }
            )
            if strict:
                raise FileNotFoundError(message)
            continue

        with Image.open(source) as raw:
            source_size = [raw.width, raw.height]
            prepared = prepare_image(raw, spec)
            output_path = out_root / spec.output
            save_image(prepared, output_path)
            manifest_rows.append(
                {
                    "name": spec.name,
                    "status": "ok",
                    "source": str(source.relative_to(project_root)).replace("\\", "/"),
                    "sourceSize": source_size,
                    "targetSize": [spec.width, spec.height],
                    "mode": spec.mode,
                    "output": str(output_path.relative_to(project_root)).replace("\\", "/"),
                    "resized": source_size != [spec.width, spec.height],
                }
            )
            if source_size != [spec.width, spec.height]:
                warnings.append(
                    f"{spec.name}: source {source_size[0]}x{source_size[1]} -> target {spec.width}x{spec.height}"
                )
    return manifest_rows, warnings


def process_card_variants(
    project_root: Path,
    out_root: Path,
    *,
    target_count: int,
    strict: bool,
) -> tuple[list[dict[str, object]], list[str]]:
    src_dir = project_root / "images" / "processed" / "card_backs" / "variants_768x1024"
    if not src_dir.is_dir():
        msg = f"Card variant directory not found: {src_dir}"
        if strict:
            raise FileNotFoundError(msg)
        return (
            [
                {
                    "name": "card-back-variants",
                    "status": "missing_source",
                    "sourceDir": str(src_dir.relative_to(project_root)).replace("\\", "/"),
                }
            ],
            [msg],
        )

    source_variants = sorted(src_dir.glob("*.png"), key=parse_variant_index)
    if not source_variants:
        msg = f"No card variant files found in {src_dir}"
        if strict:
            raise FileNotFoundError(msg)
        return (
            [
                {
                    "name": "card-back-variants",
                    "status": "empty_source",
                    "sourceDir": str(src_dir.relative_to(project_root)).replace("\\", "/"),
                }
            ],
            [msg],
        )

    target_dir = out_root / "card-backs" / "variants"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    if len(source_variants) < target_count:
        warnings.append(
            f"Only {len(source_variants)} card variants available, below requested {target_count}."
        )

    usable = source_variants[: max(1, min(target_count, len(source_variants)))]
    for idx, source in enumerate(usable, start=1):
        with Image.open(source) as raw:
            source_size = [raw.width, raw.height]
            processed = resize_cover(raw, 768, 1024)
            output_path = target_dir / f"card_back_variant_{idx:02d}.png"
            save_image(processed, output_path)
            out_rows.append(
                {
                    "name": f"card-back-variant-{idx:02d}",
                    "status": "ok",
                    "source": str(source.relative_to(project_root)).replace("\\", "/"),
                    "sourceSize": source_size,
                    "targetSize": [768, 1024],
                    "output": str(output_path.relative_to(project_root)).replace("\\", "/"),
                    "resized": source_size != [768, 1024],
                }
            )
            if source_size != [768, 1024]:
                warnings.append(
                    f"card-back-variant-{idx:02d}: source {source_size[0]}x{source_size[1]} -> target 768x1024"
                )
    return out_rows, warnings


def write_manifest(
    project_root: Path,
    manifest_path: Path,
    rows: list[dict[str, object]],
    warnings: list[str],
) -> None:
    payload = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "projectRoot": str(project_root).replace("\\", "/"),
        "assetCount": len(rows),
        "warningsCount": len(warnings),
        "warnings": warnings,
        "assets": rows,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    out_root = (project_root / args.output_dir).resolve()
    manifest_path = (project_root / args.manifest).resolve()

    rows: list[dict[str, object]] = []
    warnings: list[str] = []

    core_rows, core_warnings = process_core_specs(project_root, out_root, args.strict)
    rows.extend(core_rows)
    warnings.extend(core_warnings)

    variant_rows, variant_warnings = process_card_variants(
        project_root,
        out_root,
        target_count=max(1, int(args.card_variants)),
        strict=args.strict,
    )
    rows.extend(variant_rows)
    warnings.extend(variant_warnings)

    write_manifest(project_root, manifest_path, rows, warnings)

    print(f"Prepared assets in: {out_root}")
    print(f"Manifest: {manifest_path}")
    print(f"Assets: {len(rows)}")
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
