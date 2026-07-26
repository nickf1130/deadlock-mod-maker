from __future__ import annotations

from difflib import SequenceMatcher

from ..models import SoundAsset


def relocation_score(original: SoundAsset, candidate: SoundAsset) -> float:
    """Score a possible moved asset without ever making an automatic decision."""
    score = 0.0
    if original.filename.casefold() == candidate.filename.casefold():
        score += 0.30
    score += (
        SequenceMatcher(
            None, original.internal_path.casefold(), candidate.internal_path.casefold()
        ).ratio()
        * 0.20
    )
    if original.hero_id and original.hero_id == candidate.hero_id:
        score += 0.15
    if original.ability_name and original.ability_name == candidate.ability_name:
        score += 0.10
    if original.sound_event and original.sound_event == candidate.sound_event:
        score += 0.20
    if original.duration_ms and candidate.duration_ms:
        difference = abs(original.duration_ms - candidate.duration_ms)
        tolerance = max(original.duration_ms, candidate.duration_ms)
        score += max(0.0, 1 - difference / tolerance) * 0.05
    return round(min(score, 1.0), 4)
