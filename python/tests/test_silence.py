from __future__ import annotations

import wave
from pathlib import Path

from deadlock_sound_studio.audio import silence_processing, write_silence
from deadlock_sound_studio.audio.service import build_ffmpeg_arguments
from deadlock_sound_studio.audio.silence import SILENCE_SECONDS


def read_wav(path: Path):
    with wave.open(str(path), "rb") as audio:
        return {
            "channels": audio.getnchannels(),
            "rate": audio.getframerate(),
            "width": audio.getsampwidth(),
            "frames": audio.getnframes(),
            "data": audio.readframes(audio.getnframes()),
        }


def test_generated_file_is_a_valid_and_actually_silent_wav(tmp_path: Path):
    written = write_silence(tmp_path / "silence.wav")

    info = read_wav(written)
    assert info["width"] == 2
    assert info["frames"] > 0
    # Every sample is zero, which is what makes it silent rather than quiet.
    assert set(info["data"]) == {0}


def test_format_follows_the_sound_being_replaced(tmp_path: Path):
    written = write_silence(tmp_path / "s.wav", sample_rate=48_000, channels=2)

    info = read_wav(written)
    assert info["rate"] == 48_000
    assert info["channels"] == 2
    assert info["frames"] == round(48_000 * SILENCE_SECONDS)


def test_unknown_format_falls_back_to_sane_defaults(tmp_path: Path):
    written = write_silence(tmp_path / "s.wav", sample_rate=None, channels=None)

    info = read_wav(written)
    assert info["rate"] == 44_100
    assert info["channels"] == 1


def test_silence_processing_disables_the_two_settings_that_would_ruin_it():
    settings = silence_processing()

    # Normalising has no signal to work with, and trimming silence from a file
    # that is entirely silence removes the whole thing.
    assert settings.normalize is False
    assert settings.auto_trim_silence is False
    assert settings.gain_db == 0
    assert settings.fade_in_seconds == 0
    assert settings.fade_out_seconds == 0


def test_the_ffmpeg_command_for_silence_carries_no_destructive_filters(tmp_path: Path):
    arguments = build_ffmpeg_arguments(
        tmp_path / "in.wav", tmp_path / "out.wav", silence_processing(44_100, 1)
    )

    joined = " ".join(arguments)
    assert "loudnorm" not in joined
    assert "silenceremove" not in joined
    assert "afade" not in joined
