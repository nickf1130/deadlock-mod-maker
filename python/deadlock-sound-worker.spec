# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / "deadlock_sound_studio" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (
            str(project_root / "deadlock_sound_studio" / "database" / "migrations"),
            "deadlock_sound_studio/database/migrations",
        )
    ],
    hiddenimports=["mutagen", "openpyxl", "pydantic", *collect_submodules("PIL")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="deadlock-sound-worker",
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="deadlock-sound-worker",
)
