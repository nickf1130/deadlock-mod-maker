from __future__ import annotations

import json
import wave
from pathlib import Path

from mutagen import File as MutagenFile

from ..errors import StudioError, capability_error, validation_error
from ..external.process import CancellationToken, run_process
from ..models import AudioMetadata, ProcessRecord, ProcessingSettings


def build_ffmpeg_arguments(
    source: Path,
    output: Path,
    settings: ProcessingSettings,
    *,
    source_duration_seconds: float | None = None,
) -> list[str]:
    """Build the deterministic FFmpeg command used for replacement audio."""
    filters: list[str] = []
    trim = f"atrim=start={settings.trim_start_seconds:.6f}"
    if settings.trim_end_seconds is not None:
        if settings.trim_end_seconds <= settings.trim_start_seconds:
            raise validation_error("Trim end must be after trim start")
        trim += f":end={settings.trim_end_seconds:.6f}"
    filters.append(trim)
    filters.append("asetpts=PTS-STARTPTS")
    if settings.auto_trim_silence:
        filters.append(
            "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB:"
            "stop_periods=-1:stop_duration=0.05:stop_threshold=-50dB"
        )
    if settings.gain_db:
        filters.append(f"volume={settings.gain_db:.3f}dB")
    if settings.normalize:
        filters.append(
            f"loudnorm=I={settings.target_loudness_lufs:.2f}:"
            f"TP={settings.peak_headroom_db:.2f}:LRA=11"
        )
    if settings.fade_in_seconds > 0:
        filters.append(f"afade=t=in:st=0:d={settings.fade_in_seconds:.6f}")
    effective_duration = None
    if settings.trim_end_seconds is not None:
        effective_duration = (
            settings.trim_end_seconds - settings.trim_start_seconds
        )
    elif source_duration_seconds:
        effective_duration = source_duration_seconds - settings.trim_start_seconds
    if settings.fade_out_seconds > 0:
        if effective_duration is None:
            raise validation_error("Fade-out requires a known duration or trim end")
        start = effective_duration - settings.fade_out_seconds
        if start < 0:
            raise validation_error("Fade-out is longer than the processed audio")
        filters.append(
            f"afade=t=out:st={start:.6f}:d={settings.fade_out_seconds:.6f}"
        )
    arguments = ["-hide_banner", "-nostdin", "-y", "-i", str(source)]
    if filters:
        arguments.extend(["-af", ",".join(filters)])
    if settings.channels:
        arguments.extend(["-ac", str(settings.channels)])
    if settings.sample_rate:
        arguments.extend(["-ar", str(settings.sample_rate)])
    arguments.extend(["-c:a", "pcm_s16le", str(output)])
    return arguments


def validate_audio_source(path: Path) -> Path:
    """Resolve and validate an audio file selected by the user."""
    source = path.expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".wav", ".mp3"}:
        raise validation_error("Choose an existing MP3 or WAV file", path=str(path))
    return source


def inspect_audio(path: Path, ffprobe: Path | None = None) -> AudioMetadata:
    """Read audio metadata with FFprobe, or a limited local fallback."""
    source = validate_audio_source(path)
    if ffprobe and ffprobe.is_file():
        record = run_process(
            ffprobe,
            [
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(source),
            ],
            timeout_seconds=30,
        )
        try:
            payload = json.loads(record.stdout)
            stream = next(
                value
                for value in payload.get("streams", [])
                if value.get("codec_type") == "audio"
            )
            duration = stream.get("duration") or payload.get("format", {}).get(
                "duration"
            )
            sample_rate = None
            if stream.get("sample_rate"):
                sample_rate = int(stream["sample_rate"])
            duration_ms = None
            if duration:
                duration_ms = round(float(duration) * 1000)
            channels = None
            if stream.get("channels"):
                channels = int(stream["channels"])
            return AudioMetadata(
                duration_ms=duration_ms,
                sample_rate=sample_rate,
                channels=channels,
                codec=stream.get("codec_name"),
                preview_path=str(source),
                warnings=_audio_warnings(sample_rate),
            )
        except (
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise StudioError(
                "AUDIO_DECODE_FAILED",
                "FFprobe could not identify a decodable audio stream.",
                {"error": str(error)},
            ) from error
    metadata = _fallback_inspect(source)
    metadata.warnings.insert(
        0, "FFprobe is unavailable; metadata uses a limited local fallback."
    )
    return metadata


def process_audio(
    source: Path,
    output: Path,
    settings: ProcessingSettings,
    ffmpeg: Path | None,
    ffprobe: Path | None,
    *,
    cancellation: CancellationToken | None = None,
    record_sink: list[ProcessRecord] | None = None,
) -> AudioMetadata:
    """Process a replacement to WAV and verify the generated file."""
    if not ffmpeg:
        raise capability_error("FFmpeg is required to process replacement audio.")
    if not ffprobe:
        raise capability_error("FFprobe is required to validate processed audio.")
    source_metadata = inspect_audio(source, ffprobe)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_duration_seconds = None
    if source_metadata.duration_ms:
        source_duration_seconds = source_metadata.duration_ms / 1000
    arguments = build_ffmpeg_arguments(
        source,
        output,
        settings,
        source_duration_seconds=source_duration_seconds,
    )
    record = run_process(
        ffmpeg,
        arguments,
        timeout_seconds=15 * 60,
        cancellation=cancellation,
        expected_files=[output],
    )
    if record_sink is not None:
        record_sink.append(record)
    if not output.is_file() or output.stat().st_size == 0:
        raise StudioError(
            "AUDIO_PROCESSING_FAILED", "FFmpeg did not produce a nonempty WAV file."
        )
    result = inspect_audio(output, ffprobe)
    result.preview_path = str(output)
    return result


def _fallback_inspect(path: Path) -> AudioMetadata:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                frames = audio.getnframes()
                rate = audio.getframerate()
                duration_ms = None
                if rate:
                    duration_ms = round(frames / rate * 1000)
                return AudioMetadata(
                    duration_ms=duration_ms,
                    sample_rate=rate,
                    channels=audio.getnchannels(),
                    codec=f"pcm_s{audio.getsampwidth() * 8}le",
                    preview_path=str(path),
                    warnings=_audio_warnings(rate),
                )
        except (wave.Error, EOFError) as error:
            raise StudioError("AUDIO_DECODE_FAILED", "The WAV file is invalid.") from error
    try:
        audio = MutagenFile(path)
        if audio is None or not getattr(audio, "info", None):
            raise ValueError("No audio stream")
        sample_rate = getattr(audio.info, "sample_rate", None)
        return AudioMetadata(
            duration_ms=round(audio.info.length * 1000),
            sample_rate=sample_rate,
            channels=getattr(audio.info, "channels", None),
            codec=path.suffix.lower().lstrip("."),
            preview_path=str(path),
            warnings=_audio_warnings(sample_rate),
        )
    except Exception as error:
        raise StudioError(
            "AUDIO_DECODE_FAILED", "The selected file could not be decoded."
        ) from error


def _audio_warnings(sample_rate: int | None) -> list[str]:
    if sample_rate and sample_rate < 22_050:
        return ["The sample rate is unusually low."]
    return []
