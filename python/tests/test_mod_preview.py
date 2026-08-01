"""Hearing a sound that lives inside an installed mod.

The export machinery was originally written for the game archive alone. The
risk in reusing it is that it quietly keeps pointing at the archive, so the
player auditions the sound the mod *replaces* instead of the mod's own - which
looks like the feature working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import write_vpk
from deadlock_sound_studio.errors import StudioError
from deadlock_sound_studio.paths import AppPaths
from deadlock_sound_studio.protocol.router import BackendRouter
from deadlock_sound_studio.source_viewer import adapter, export_package_sound

MOD_SOUND = "sounds/vo/hero_one/attack.vsnd_c"


def fake_cli(tmp_path: Path) -> Path:
    """A stand-in for Source2Viewer-CLI.exe, which can_decompile() accepts."""
    executable = tmp_path / "Source2Viewer-CLI.exe"
    executable.write_bytes(b"stub")
    return executable


def test_export_reads_from_the_given_package_not_the_game_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package = write_vpk(tmp_path / "pak12_dir.vpk", {MOD_SOUND: b"sound"})
    cache_root = tmp_path / "cache" / "preview"
    recorded: dict[str, list[str]] = {}

    def capture(executable, arguments, **_kwargs):
        recorded["arguments"] = list(arguments)
        # The real CLI writes the decoded audio; stand in for that.
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "attack.wav").write_bytes(b"RIFF")

    monkeypatch.setattr(adapter, "run_process", capture)

    result = export_package_sound(
        fake_cli(tmp_path),
        AppPaths.from_root(tmp_path / "studio"),
        package,
        MOD_SOUND,
        cache_root=cache_root,
    )

    assert result.name == "attack.wav"
    arguments = recorded["arguments"]
    # -i is the package to read. It has to be the mod, or the player hears the
    # game's original and believes the mod does nothing.
    assert arguments[arguments.index("-i") + 1] == str(package)
    assert arguments[arguments.index("--vpk_filepath") + 1] == MOD_SOUND


def test_a_cached_preview_is_reused_rather_than_decompiled_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package = write_vpk(tmp_path / "pak12_dir.vpk", {MOD_SOUND: b"sound"})
    cache_root = tmp_path / "cache" / "preview"
    cache_root.mkdir(parents=True)
    (cache_root / "attack.wav").write_bytes(b"RIFF")

    def fail(*_args, **_kwargs):
        raise AssertionError("a cached preview must not run the decompiler")

    monkeypatch.setattr(adapter, "run_process", fail)

    assert export_package_sound(
        fake_cli(tmp_path),
        AppPaths.from_root(tmp_path / "studio"),
        package,
        MOD_SOUND,
        cache_root=cache_root,
    ).name == "attack.wav"


def test_preview_refuses_anything_that_is_not_a_compiled_sound(tmp_path: Path):
    """The export only knows how to decode .vsnd_c. Asking it for a texture
    would run the decompiler and then fail confusingly."""
    package = write_vpk(
        tmp_path / "pak12_dir.vpk",
        {"panorama/styles/element_gun.vcss_c": b"styles"},
    )
    router = BackendRouter(AppPaths.from_root(tmp_path / "studio"), lambda _event: None)
    try:
        with pytest.raises(StudioError) as error:
            router.dispatch(
                "mods.previewSound",
                {
                    "path": str(package),
                    "internalPath": "panorama/styles/element_gun.vcss_c",
                },
            )
        assert "compiled sounds" in error.value.message

        with pytest.raises(StudioError):
            router.dispatch(
                "mods.previewSound",
                {"path": str(tmp_path / "absent.vpk"), "internalPath": MOD_SOUND},
            )
    finally:
        router.close()
