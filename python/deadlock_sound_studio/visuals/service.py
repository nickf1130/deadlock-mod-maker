from __future__ import annotations

import re
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..errors import StudioError, validation_error
from ..models import VisualResourceKind, VisualSourceMetadata
from ..paths import AppPaths

IMAGE_EXTENSIONS = {".png", ".tga", ".psd"}
MATERIAL_EXTENSIONS = {".vmat"}
RESOURCE_PATTERN = re.compile(
    r"""(?i)(?:resource:)?[\"']?((?:materials|models)/[^\"'\s]+?\.(?:vtex|vtex_c|vmat|vmat_c))[\"']?"""
)


def _power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def write_vtex_descriptor(
    destination: Path,
    image_internal_path: str,
    *,
    has_alpha: bool,
    color_space: str,
    normal_map: bool,
) -> None:
    output_format = "DXT5" if has_alpha else "DXT1"
    if normal_map:
        output_format = "BC5"
    descriptor = f"""<!-- dmx encoding keyvalues2_noids 1 format vtex 1 -->
"CDmeVtex"
{{
\t"m_inputTextureArray" "element_array"
\t[
\t\t"CDmeInputTexture"
\t\t{{
\t\t\t"m_name" "string" "InputTexture0"
\t\t\t"m_fileName" "string" "{image_internal_path}"
\t\t\t"m_colorSpace" "string" "{color_space}"
\t\t\t"m_typeString" "string" "2D"
\t\t\t"m_imageProcessorArray" "element_array"
\t\t\t[
\t\t\t\t"CDmeImageProcessor"
\t\t\t\t{{
\t\t\t\t\t"m_algorithm" "string" "None"
\t\t\t\t\t"m_stringArg" "string" ""
\t\t\t\t\t"m_vFloat4Arg" "vector4" "0 0 0 0"
\t\t\t\t}}
\t\t\t]
\t\t}}
\t]
\t"m_outputTypeString" "string" "2D"
\t"m_outputFormat" "string" "{output_format}"
\t"m_outputClearColor" "vector4" "0 0 0 0"
\t"m_nOutputMinDimension" "int" "0"
\t"m_nOutputMaxDimension" "int" "0"
\t"m_textureOutputChannelArray" "element_array"
\t[
\t\t"CDmeTextureOutputChannel"
\t\t{{
\t\t\t"m_inputTextureArray" "string_array" [ "InputTexture0" ]
\t\t\t"m_srcChannels" "string" "rgba"
\t\t\t"m_dstChannels" "string" "rgba"
\t\t\t"m_mipAlgorithm" "CDmeImageProcessor"
\t\t\t{{
\t\t\t\t"m_algorithm" "string" "Box"
\t\t\t\t"m_stringArg" "string" ""
\t\t\t\t"m_vFloat4Arg" "vector4" "0 0 0 0"
\t\t\t}}
\t\t\t"m_outputColorSpace" "string" "{color_space}"
\t\t}}
\t]
\t"m_vClamp" "vector3" "0 0 0"
\t"m_bNoLod" "bool" "0"
}}
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(descriptor, encoding="utf-8", newline="\n")


def validate_visual_source(source: Path, kind: VisualResourceKind) -> Path:
    """Resolve a visual source and reject unsupported or empty files."""
    source = source.resolve(strict=True)
    if not source.is_file():
        raise validation_error("Choose a visual replacement file.")
    allowed = (
        IMAGE_EXTENSIONS
        if kind == VisualResourceKind.TEXTURE
        else MATERIAL_EXTENSIONS
    )
    if source.suffix.lower() not in allowed:
        expected = ", ".join(sorted(allowed))
        raise validation_error(
            f"{kind.value.title()} replacements must use one of: {expected}."
        )
    if source.stat().st_size <= 0:
        raise validation_error("The selected visual source is empty.")
    return source


def inspect_visual_source(
    paths: AppPaths,
    source: Path,
    kind: VisualResourceKind,
) -> VisualSourceMetadata:
    """Inspect a replacement texture or material and prepare its preview."""
    source = validate_visual_source(source, kind)
    if kind == VisualResourceKind.MATERIAL:
        return _inspect_material(source)
    return _inspect_texture(paths, source)


def _inspect_texture(paths: AppPaths, source: Path) -> VisualSourceMetadata:
    warnings: list[str] = []
    try:
        with Image.open(source) as image:
            image.load()
            width, height = image.size
            mode = image.mode
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            if width > 16384 or height > 16384:
                raise validation_error(
                    "Textures may not exceed 16384 pixels on either side.",
                    width=width,
                    height=height,
                )
            if not _power_of_two(width) or not _power_of_two(height):
                warnings.append(
                    "Non-power-of-two dimensions can fail in runtime shaders; "
                    "power-of-two is recommended."
                )
            probable_normal = any(
                marker in source.stem.casefold()
                for marker in ("_normal", "_norm", "_nrm")
            )
            color_space = "linear" if probable_normal else "srgb"
            preview_root = paths.cache / "visual-previews"
            preview_root.mkdir(parents=True, exist_ok=True)
            preview = preview_root / f"{uuid.uuid4().hex}.png"
            converted = image.convert("RGBA" if has_alpha else "RGB")
            converted.thumbnail((1600, 1600))
            converted.save(preview, "PNG")
    except UnidentifiedImageError as error:
        raise StudioError(
            "VISUAL_SOURCE_INVALID",
            "The selected image could not be decoded.",
        ) from error
    except OSError as error:
        raise StudioError(
            "VISUAL_SOURCE_INVALID",
            f"The selected image could not be read: {error}",
        ) from error
    return VisualSourceMetadata(
        format=source.suffix.lower().lstrip(".").upper(),
        width=width,
        height=height,
        mode=mode,
        has_alpha=has_alpha,
        color_space=color_space,
        probable_normal_map=probable_normal,
        preview_path=str(preview),
        warnings=warnings,
    )


def _inspect_material(source: Path) -> VisualSourceMetadata:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise StudioError(
            "VISUAL_SOURCE_INVALID",
            "VMAT replacements must be UTF-8 text source files.",
        ) from error
    warnings: list[str] = []
    if len(text) > 2_000_000:
        raise validation_error("The VMAT source is unexpectedly large.")
    if "Layer0" not in text and "shader" not in text.casefold():
        warnings.append("No obvious material shader declaration was found.")
    dependencies = sorted(
        {match.group(1) for match in RESOURCE_PATTERN.finditer(text)}
    )
    return VisualSourceMetadata(
        format="VMAT",
        text_preview=text[:120_000],
        dependencies=dependencies,
        warnings=warnings,
    )
