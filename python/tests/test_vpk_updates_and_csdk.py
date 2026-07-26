from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from deadlock_sound_studio.csdk.adapters import (
    expected_compiled_output,
    synchronize_csdk_workspace,
)
from deadlock_sound_studio.external.process import CancellationToken
from deadlock_sound_studio.indexing import classify_sound, index_archive
from deadlock_sound_studio.models import SoundCategory
from deadlock_sound_studio.updates import relocation_score
from deadlock_sound_studio.vpk import list_vpk

from conftest import make_asset, write_vpk


def test_vpk_content_listing_and_checksum(tmp_path: Path):
    vpk = write_vpk(
        tmp_path / "pack.vpk",
        {
            "sounds/ui/accept.vsnd_c": b"compiled-one",
            "sounds/vo/hero/line.vsnd_c": b"compiled-two",
        },
    )
    entries = list_vpk(vpk)
    assert [entry.path for entry in entries] == [
        "sounds/ui/accept.vsnd_c",
        "sounds/vo/hero/line.vsnd_c",
    ]
    expected = hashlib.sha256(vpk.read_bytes()).hexdigest()
    assert len(expected) == 64


def test_vpk_parser_rejects_non_vpk(tmp_path: Path):
    path = tmp_path / "bad.vpk"
    path.write_bytes(b"not a vpk")
    with pytest.raises(Exception):
        list_vpk(path)


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("sounds/vo/abrams/kill.vsnd_c", SoundCategory.VOICE),
        ("sounds/abilities/viscous/splash.vsnd_c", SoundCategory.ABILITY),
        ("sounds/weapons/pistol/fire.vsnd_c", SoundCategory.WEAPON),
        ("sounds/ui/menu.vsnd_c", SoundCategory.UI),
        ("sounds/unknown/mystery.vsnd_c", SoundCategory.GENERAL),
    ],
)
def test_hero_and_category_classification(path: str, category: SoundCategory):
    assert classify_sound(path)[0] == category


def test_ability_path_associates_hero_and_ability():
    category, hero, ability = classify_sound(
        "sounds/abilities/abrams/a2_charge/impact.vsnd_c"
    )
    assert category == SoundCategory.ABILITY
    assert hero == "abrams"
    assert ability == "a2_charge"


def test_index_enriches_sound_from_event_hero_ability_and_talker_metadata(
    database, tmp_path: Path
):
    sound_path = "sounds/abilities/abrams/a2_charge/cast.vsnd_c"
    metadata = b"""
hero_id "abrams"
display_name "Abrams"
ability_name "Shoulder Charge"
event_name "Hero.Abrams.Cast"
sound "sounds/abilities/abrams/a2_charge/cast.vsnd"
talker "abrams"
"""
    archive = write_vpk(
        tmp_path / "pak01_dir.vpk",
        {
            sound_path: b"compiled-sound",
            "scripts/game_sounds.vsndevts_c": metadata,
        },
    )

    result = index_archive(database, archive)
    asset = database.get_asset_by_path(sound_path)

    assert result.indexed == 1
    assert asset is not None
    assert asset.hero_name == "Abrams"
    assert asset.ability_name == "Shoulder Charge"
    assert asset.sound_event == "Hero.Abrams.Cast"


def test_csdk_workspace_sync_only_touches_owned_addon(tmp_path: Path):
    csdk = tmp_path / "csdk"
    (csdk / "content/citadel_addons").mkdir(parents=True)
    (csdk / "game/citadel_addons").mkdir(parents=True)
    generated = tmp_path / "generated"
    generated_sound = generated / "sounds/ui/accept.wav"
    generated_sound.parent.mkdir(parents=True)
    generated_sound.write_bytes(b"wav")
    content, game = synchronize_csdk_workspace(
        csdk, "project-one", "dss_example", generated
    )
    assert (content / "sounds/ui/accept.wav").read_bytes() == b"wav"
    assert (content / ".deadlock-sound-studio.json").is_file()
    assert (game / ".deadlock-sound-studio.json").is_file()
    stale = game / "sounds/ui/stale.vsnd_c"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    synchronize_csdk_workspace(csdk, "project-one", "dss_example", generated)
    assert not stale.exists()
    foreign = csdk / "content/citadel_addons/foreign"
    foreign.mkdir()
    with pytest.raises(Exception):
        synchronize_csdk_workspace(
            csdk, "project-one", "foreign", generated
        )


def test_compiled_output_mapping(tmp_path: Path):
    csdk = tmp_path / "csdk"
    expected = expected_compiled_output(
        csdk, "dss_test", "sounds/ui/accept.vsnd_c"
    )
    assert expected == csdk / "game/citadel_addons/dss_test/sounds/ui/accept.vsnd_c"


def test_update_relocation_scoring_prefers_matching_metadata():
    original = make_asset(
        "sounds/hero/a/old.vsnd_c",
        hero_id="a",
        ability_name="Ability",
        sound_event="Hero.Cast",
        duration_ms=1000,
    )
    good = make_asset(
        "sounds/hero/a/new.vsnd_c",
        id="good",
        hero_id="a",
        ability_name="Ability",
        sound_event="Hero.Cast",
        duration_ms=1020,
    )
    bad = make_asset("sounds/ui/unrelated.vsnd_c", id="bad", duration_ms=5000)
    assert relocation_score(original, good) > relocation_score(original, bad)


def test_build_cancellation_token():
    token = CancellationToken()
    assert not token.cancelled
    token.cancel()
    assert token.cancelled
    with pytest.raises(Exception):
        token.raise_if_cancelled()
