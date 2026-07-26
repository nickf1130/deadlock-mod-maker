from __future__ import annotations

from pathlib import Path

import pytest

from deadlock_sound_studio.audio import build_ffmpeg_arguments, inspect_audio
from deadlock_sound_studio.csdk.encoding import EncodingEntry, generate_encoding, validate_loop
from deadlock_sound_studio.models import LoopSettings, ProcessingSettings

from conftest import write_wav


def test_audio_processing_command_generation_is_direct_and_deterministic(tmp_path: Path):
    settings = ProcessingSettings(
        trim_start_seconds=1,
        trim_end_seconds=5,
        fade_in_seconds=0.2,
        fade_out_seconds=0.5,
        gain_db=2,
        normalize=True,
        channels=1,
        sample_rate=48_000,
    )
    arguments = build_ffmpeg_arguments(
        tmp_path / "source.mp3",
        tmp_path / "result.wav",
        settings,
        source_duration_seconds=8,
    )
    assert arguments[0:5] == [
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(tmp_path / "source.mp3"),
    ]
    filters = arguments[arguments.index("-af") + 1]
    assert "atrim=start=1.000000:end=5.000000" in filters
    assert "loudnorm=I=-16.00:TP=-1.00" in filters
    assert "afade=t=out:st=3.500000:d=0.500000" in filters
    assert arguments[-3:] == ["-c:a", "pcm_s16le", str(tmp_path / "result.wav")]


def test_audio_command_rejects_invalid_trim(tmp_path: Path):
    with pytest.raises(Exception):
        build_ffmpeg_arguments(
            tmp_path / "a.wav",
            tmp_path / "b.wav",
            ProcessingSettings(trim_start_seconds=2, trim_end_seconds=1),
        )


def test_wav_fallback_metadata_is_real(tmp_path: Path):
    source = write_wav(tmp_path / "source.wav", duration_seconds=0.25, rate=22_050)
    metadata = inspect_audio(source)
    assert 245 <= metadata.duration_ms <= 255
    assert metadata.sample_rate == 22_050
    assert metadata.channels == 1
    assert any("FFprobe" in warning for warning in metadata.warnings)


def test_loop_validation_seconds_and_samples():
    validate_loop(LoopSettings(enabled=True, start_seconds=0, end_seconds=2), 3)
    validate_loop(LoopSettings(enabled=True, start_sample=100, end_sample=200))
    with pytest.raises(Exception):
        validate_loop(LoopSettings(enabled=True, start_seconds=2, end_seconds=1))
    with pytest.raises(Exception):
        validate_loop(
            LoopSettings(
                enabled=True,
                start_seconds=0,
                end_seconds=1,
                start_sample=0,
                end_sample=100,
            )
        )


def test_encoding_txt_generation_is_sorted_escaped_and_deterministic():
    entries = [
        EncodingEntry(
            'z"sound.wav', LoopSettings(enabled=True, start_sample=4, end_sample=10)
        ),
        EncodingEntry(
            "alpha.wav", LoopSettings(enabled=True, start_seconds=0, end_seconds=1.25)
        ),
    ]
    first = generate_encoding(entries)
    second = generate_encoding(list(reversed(entries)))
    assert first == second
    assert first.index("alpha.wav") < first.index('z\\"sound.wav')
    assert "loop_end_time = 1.250000" in first
    assert "loop_start_sample = 4" in first
    assert first.startswith("<!-- kv3")
