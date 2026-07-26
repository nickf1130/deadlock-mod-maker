# Release checklist

Use this checklist from a clean Windows checkout. CI runs the same automated
checks, but a release owner still needs to perform the real-tool and publishing
steps.

## Automated gate

```powershell
npm ci
npm run typecheck
npm run test:all
npm run audit:python
npm audit --omit=dev --audit-level=high
npm run dist
```

`npm run dist` rebuilds the Python worker in a clean pinned environment,
packages the app, checks the packaged backend and license files, and creates:

- `release/DeadlockModMaker-<version>-portable.exe`
- `release/DeadlockModMaker-<version>-portable.exe.sha256`

## Real-tool gate

Set `DSS_CSDK_ROOT`, `DSS_DEADLOCK_ROOT`, `DSS_FFMPEG`, and `DSS_FFPROBE` as
shown in `SETUP.md`, then run the opt-in Python integration suite. Also run the
real preview test with the same configured application data:

```powershell
$env:DSS_RUN_INTEGRATION = "1"
Push-Location .\python
& .\.venv-release\Scripts\python.exe -m pytest tests/test_integration_tools.py -m integration
Pop-Location

$env:DSS_PREVIEW_INTEGRATION = "1"
npx playwright test e2e/preview.integration.spec.ts
```

## Manual release checks

1. Start the portable executable from a new empty folder.
2. Complete setup using copies/locations that represent a new user.
3. Preview an original sound, add a replacement, build it, and inspect the VPK.
4. Confirm the About page reports the intended version and opens the bundled
   third-party notices.
5. Scan the executable with Microsoft Defender. If a signing certificate is
   available, configure electron-builder signing before `npm run dist` so the
   generated checksum covers the signed artifact.
6. Commit the exact verified source. Create a new RC tag; never move an RC tag
   that already points at a different commit.
7. Create the GitHub Release and upload both the executable and `.sha256` file.
8. Download the published asset on a second Windows account or machine, verify
   the checksum, and repeat the first-launch plus one-sound build smoke test.

The app is currently documented as unsigned. Code signing is strongly
recommended, but if the unsigned build is published, keep the SmartScreen
warning in the README and release notes.
