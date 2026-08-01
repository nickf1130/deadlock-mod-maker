"""Generate a silent replacement, so a game sound simply does not play.

Muting a sound is one of the most common things people want from a sound mod:
an ability whose callout grates, a hit sound that fires constantly. The game
gives no way to disable an individual sound, so the way to do it is to replace
the file with one that contains nothing.

That only needs a valid, very short PCM WAV, which the standard library can
write. No FFmpeg, no user-supplied file, nothing to download.

The processing settings matter as much as the audio. Two of the defaults are
actively wrong for silence and are overridden in :func:`silence_processing`.
"""

from __future__ import annotations

import wave
from pathlib import Path

from ..models import ProcessingSettings

# Long enough to be a real sound the compiler will accept, short enough that a
# looping target stays silent without carrying a large file around. Nothing
# depends on the exact value; it is a constant so it is easy to revisit.
SILENCE_SECONDS = 0.25

# Used when the indexed asset does not record its own format.
DEFAULT_SAMPLE_RATE = 44_100
DEFAULT_CHANNELS = 1

SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM, which the build pipeline already expects.


def write_silence(
    destination: Path,
    *,
    seconds: float = SILENCE_SECONDS,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> Path:
    """Write a silent 16-bit PCM WAV to ``destination``.

    Format follows the sound being replaced when the catalog recorded it, so
    the replacement does not force a resample it did not need.
    """
    rate = sample_rate or DEFAULT_SAMPLE_RATE
    channel_count = channels or DEFAULT_CHANNELS
    frames = max(1, round(rate * seconds))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(channel_count)
        output.setsampwidth(SAMPLE_WIDTH_BYTES)
        output.setframerate(rate)
        # Zeroed samples are digital silence.
        output.writeframes(b"\0" * (frames * channel_count * SAMPLE_WIDTH_BYTES))
    return destination


def silence_processing(
    sample_rate: int | None = None, channels: int | None = None
) -> ProcessingSettings:
    """Processing that leaves silence alone.

    Two defaults would otherwise ruin it:

    ``normalize``
        Normalisation asks FFmpeg to bring the track up to a target loudness.
        There is no signal to bring up, so the filter either does nothing or
        chases noise that is not there. Off.

    ``auto_trim_silence``
        Trimming leading and trailing silence from a file that is entirely
        silence removes the whole thing. Very much off.

    Fades and gain are pointless on silence, so they stay at zero too.
    """
    return ProcessingSettings(
        trim_start_seconds=0,
        trim_end_seconds=None,
        auto_trim_silence=False,
        fade_in_seconds=0,
        fade_out_seconds=0,
        gain_db=0,
        normalize=False,
        channels=channels,
        sample_rate=sample_rate,
    )
