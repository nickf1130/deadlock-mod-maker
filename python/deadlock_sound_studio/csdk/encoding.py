from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..errors import validation_error
from ..models import LoopSettings

HEADER = (
    "<!-- kv3 encoding:text:version{e21c7f3c-8a33-41c5-9977-a76d3a32aa0d} "
    "format:generic:version{7412167c-06e9-4698-aff2-e63eb59037e7} -->"
)


@dataclass(frozen=True, slots=True)
class EncodingEntry:
    filename: str
    loop: LoopSettings


def validate_loop(loop: LoopSettings, duration_seconds: float | None = None) -> None:
    if not loop.enabled:
        return
    time_pair = loop.start_seconds is not None or loop.end_seconds is not None
    sample_pair = loop.start_sample is not None or loop.end_sample is not None
    if time_pair and sample_pair:
        raise validation_error("Use loop points in seconds or samples, not both")
    if time_pair:
        if loop.start_seconds is None or loop.end_seconds is None:
            raise validation_error("Both loop start and end seconds are required")
        if loop.start_seconds >= loop.end_seconds:
            raise validation_error("Loop start must be before loop end")
        if duration_seconds is not None and loop.end_seconds > duration_seconds:
            raise validation_error("Loop end exceeds processed audio duration")
        return
    if sample_pair:
        if loop.start_sample is None or loop.end_sample is None:
            raise validation_error("Both loop start and end samples are required")
        if loop.start_sample >= loop.end_sample:
            raise validation_error("Loop start sample must be before loop end sample")
        return
    raise validation_error("Looping is enabled but loop points are missing")


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def generate_encoding(entries: Sequence[EncodingEntry]) -> str:
    enabled = sorted(
        (entry for entry in entries if entry.loop.enabled),
        key=lambda entry: entry.filename.casefold(),
    )
    for entry in enabled:
        validate_loop(entry.loop)
    lines = [
        HEADER,
        "{",
        "\tcompress =",
        "\t{",
        '\t\tformat = "mp3"',
        "\t\tminbitrate = 128",
        "\t\tmaxbitrate = 320",
        "\t\tvbr = 1",
        "\t}",
        "\tfiles =",
        "\t[",
    ]
    for entry in enabled:
        loop = entry.loop
        lines.extend(
            [
                "\t\t{",
                f'\t\t\tfileName = "{_quote(entry.filename)}"',
                "\t\t\tloop =",
                "\t\t\t{",
            ]
        )
        if loop.start_seconds is not None:
            lines.append(f"\t\t\t\tloop_start_time = {loop.start_seconds:.6f}")
            lines.append(f"\t\t\t\tloop_end_time = {loop.end_seconds:.6f}")
        else:
            lines.append(f"\t\t\t\tloop_start_sample = {loop.start_sample}")
            lines.append(f"\t\t\t\tloop_end_sample = {loop.end_sample}")
        lines.extend(["\t\t\t}", "\t\t},"])
    lines.extend(["\t]", "}", ""])
    return "\n".join(lines)
