# Setup and Windows release build

## User-supplied tools

The first launch opens a blocking setup checklist containing the same controls as Diagnostics. Choose tool locations there; they are referenced in place and stored in `data/settings.json`, and CSDK is never copied. After setup, every location can be changed from Diagnostics. Alternatively, **Download all requirements** installs the missing Source 2 Viewer GUI/CLI and FFmpeg/FFprobe releases into the application-owned `tools/` folder and verifies them. CSDK and Deadlock remain user-supplied.

Required for a complete build:

- CSDK 12 root containing:
  - `csdkcfg.exe`
  - `game/bin/win64/resourcecompiler.exe`
  - `game/bin/win64/CSDKCfgVPK.exe` or a compatible `vpk.exe`
  - `content/citadel_addons`
  - `game/citadel_addons`
- `Source2Viewer-CLI.exe` for selective original-sound decompilation and preview.
- `ffmpeg.exe`.
- `ffprobe.exe`.
- Deadlock installation with `game/citadel/pak01_dir.vpk`.
- `lame_enc.dll` in the selected CSDK binary set when loop compression is used.

The Source 2 Viewer GUI is useful for manual investigation but does not satisfy the headless preview capability. Choose the separate CLI executable.

## Portable folder

The application resolves its root from the Electron executable location, not the working directory:

```text
DeadlockModMaker/
├── DeadlockModMaker.exe
├── resources/
│   └── backend/
│       └── deadlock-sound-worker/
│           └── deadlock-sound-worker.exe
├── tools/                         # created only by automatic tool downloads
│   ├── Source2Viewer/
│   │   ├── Source2Viewer.exe
│   │   └── Source2Viewer-CLI.exe
│   └── ffmpeg/
│       ├── ffmpeg.exe
│       └── ffprobe.exe
├── data/                          # settings, catalog database, Electron profile
├── cache/                         # created for previews; cleared after export
├── projects/                      # project.json, selected sources, failure reports
├── exports/                       # final VPK, README, and optional sharing copies
├── logs/                          # created only after an unexpected application error
└── backups/                       # previous manifests and deleted-project recovery
```

Common alternative CSDK names such as `Reduced_CSDK_12` and `Reduced CSDK 12` are detected only inside the app's portable `tools/` folder. A folder selected in diagnostics always takes precedence; the app does not assume the user's Desktop or another personal folder.

Only `data/` is created during a normal first launch. The other folders are created lazily by the feature that needs them. The automatic installer reads the publishers' current GitHub release metadata, downloads only missing assets, checks SHA-256 release digests when supplied, rejects unsafe ZIP paths, installs through temporary directories, and reruns diagnostics before reporting success.

## PAK/VPK combiner

The PAK Combiner page accepts up to 50 `.vpk` or Valve-format `.pak` files. It lists internal paths and stored sizes before writing anything. Package order is significant: when multiple inputs contain the same case-insensitive internal path, the lower input wins. The output is independently reopened and verified after it is written.

## Development setup

```powershell
npm install
python -m pip install -e ".\python[dev]"
npm run dev
```

To force a different development interpreter:

```powershell
$env:DSS_PYTHON = "C:\Python312\python.exe"
npm run dev
```

Electron supplies `DSS_APP_ROOT` to the worker. Running the worker directly is also possible:

```powershell
$env:DSS_APP_ROOT = (Get-Location).Path
Set-Location python
python -m deadlock_sound_studio
```

The worker then accepts one JSON-RPC request per standard-input line and writes only protocol JSON to standard output. Routine messages go to standard error. `logs/python-worker.log` is created only if the backend hits an unexpected error.

## Release build

1. Run verification:

   ```powershell
   npm run typecheck
   npm run test:all
   npm run build
   ```

2. Package the Python worker:

   ```powershell
   npm run build:python
   ```

3. Create the portable application:

   ```powershell
   npm run dist
   ```

4. Inspect `release/` and test on a clean Windows account.

PyInstaller uses one-folder mode for predictable startup and easier DLL diagnosis. Electron Builder copies that folder to `resources/backend/deadlock-sound-worker`.

To enable the in-app updater, publish the portable artifact as a GitHub Release asset named
`DeadlockModMaker-<version>-portable.exe`. The updater requires the exact versioned filename,
the asset size, and the SHA-256 digest supplied by GitHub's release API before it offers automatic
installation. Portable builds verify the complete download, place the newer asset beside the
running executable, relaunch it through a detached helper, and remove the previous executable
after the old process exits. Development builds direct the user to the Releases page instead.

## Optional real-tool integration tests

Normal tests use fixtures and never require CSDK or Deadlock. To run opt-in local probes:

```powershell
$env:DSS_RUN_INTEGRATION = "1"
$env:DSS_CSDK_ROOT = "C:\path\to\Reduced_CSDK_12"
$env:DSS_DEADLOCK_ROOT = "C:\path\to\Deadlock"
$env:DSS_FFMPEG = "C:\path\to\ffmpeg.exe"
$env:DSS_FFPROBE = "C:\path\to\ffprobe.exe"
Push-Location .\python
& .\.venv-release\Scripts\python.exe -m pytest tests/test_integration_tools.py -m integration
Pop-Location
```

Integration probes are read-only unless a test explicitly states that it creates an application-owned temporary addon.

`npm run test:e2e` builds the desktop assets and launches Electron through Playwright with an isolated temporary application root. It does not require browser downloads, Deadlock, or the CSDK.
