# Deadlock Mod Maker

A Windows app for making sound mods (and eventually more!) for Valve's Deadlock.

Pick a sound from the game, choose a file to replace it with, and Deadlock Mod Maker
compiles and packages it into a `.vpk` mod file. You do not need to know how to program, use a
command line, or manually run any modding tools.

Deadlock Mods are currently a gray area; use this and related tools at your own risk!

> NOTE: Deadlock Mod Maker is a project made by me alone and is in no way affiliated with Valve or related projects.

---

## What it does

- Searches Deadlock's sounds without unpacking the game. The preview Visuals workspace can also
  index textures and materials.
- Previews the original sound, and your replacement, side by side with a waveform editor.
- Allows you to trim, fade, normalize and loop audio for you. For more advanced audio tweaks, consider something like Audacity.
- Packages everything into one `.vpk` file and verifies the contents before saying it worked.
- Warns you when Deadlock updates and your mod may have broken, and can re-point it in one click.

**It never modifies your Deadlock installation.** It only reads the game files and writes new
mod files into its own folder. Installing the finished mod is a manual step you do yourself.

---

## Install

### Step 1 - Download the app

Go to the [Releases page](https://github.com/nickf1130/deadlock-mod-maker/releases) and download
the file named `DeadlockModMaker-<version>-portable.exe`.

Put it in a folder of its own - for example `C:\DeadlockModMaker\`. The app creates its settings,
projects and exports folders next to the `.exe`, so give it somewhere tidy to live. Do **not** run
it from your Downloads folder. 

This app is **not** code-signed. Windows may show a blue "Windows protected your PC" warning.
Click **More info**, then **Run anyway**.

### Step 2 - Get the Deadlock modding toolkit (CSDK)

Deadlock Mod Maker does not come bundled with the CSDK12 zip. Please visit:

[CSDK 12 - DeadlockModding](https://deadlockmodding.pages.dev/modding-tools/csdk-12)

You need the **Deadlock CSDK 12** (also distributed as "Reduced CSDK 12") in order to use Deadlock Mod Maker. Unzip it somewhere permanent, such as `C:\Deadlock\CSDK12\`, then choose that folder in the setup checklist.

You should end up with a folder that contains `csdkcfg.exe` and a `game` folder inside it.

### Step 3 - Run the app and finish the checklist

Double-click the `.exe`. The first time it opens, a **Set up required tools** checklist appears.
It will not let you continue until everything on it is green.

Work down the list:

1. **Click "Download all requirements".** This fetches FFmpeg and Source 2 Viewer automatically
   and installs them into the app's own `tools` folder. This handles most of the list for you.
2. **Click "Choose CSDK folder"** and select the CSDK 12 folder from Step 2. Pick the top-level
   folder - the one containing `csdkcfg.exe`.
3. **Click "Choose Deadlock folder"** and select your Deadlock install. If you are not sure where
   it is, open Steam, right-click Deadlock, then **Manage → Browse local files**; the folder that
   opens is the one to pick.
4. Anything still marked with a red "X" has its own button on the right. Click it and point the app
   at the file it asks for.
5. When the counter in the top right reads **13/13**, click **Finish setup**.

Nothing you select here is copied or modified. The app just remembers where the files are so it can access them later.

### Step 4 - Wait for the first scan

The app now reads Deadlock's archive and builds a searchable index. This takes a few minutes the
first time and only happens once. A progress bar shows what it is doing. On a game update, this archive may need
to rebuild.

---

## Make your first mod

1. **Create a project.** Go to **Projects**, type a name (for example `my first mod`), and click
   **Create**. A project is just a container for the replacements you want to ship together.
2. **Find something to replace.** Go to **Sounds** and search - try a hero name
   like `abrams`. Click a result to select it.
3. **Listen to the original.** Click **Export & preview original** to hear what is currently in
   the game.
4. **Choose your replacement.** Click **Choose replacement** and pick an MP3 or WAV file. Drag the markers on the waveform to trim it, and open
   **Processing** if you want to adjust fades, volume or looping.
5. **Confirm it.** Click the confirm button to add the replacement to your project.
6. **Build it.** Go back to **Projects**, then click **Build & export**, then **Process project**.
7. **Collect the file.** When it finishes you will see **Export complete**. Click **Open export
   folder** - your `.vpk` is inside.

---

## Install the finished mod into Deadlock

Deadlock Mod Maker builds the `.vpk` but does not install it.

### Method 1:

The usual place is the `addons` folder inside your Deadlock install, alongside the game's own
`game\citadel\pak01_dir.vpk`:

1. Open your Deadlock folder, then go into `game\citadel\addons`. Create the `addons` folder if it
   does not exist.
2. Copy your exported `.vpk` into it.
3. Launch Deadlock.

Depending on the game version, loading addons can also require a launch option or an edit to
`gameinfo.gi`. Check current community guidance if the mod does not appear.

To uninstall the mod, delete the `.vpk` you copied. Nothing else was changed.

### Method 2:

Consider downloading [Deadlock Mod Manager](https://deadlockmods.app/). The steps to installing a mod with the Mod Manager are much more streamlined, and give you an easy way to view and edit everything that is installed.

Deadlock Mod Maker is not associated with Deadlock Mod Manager. I created this application to be a tool and bridge to making your own mods, without the tedious overhead. Deadlock Mod Manager is operated by a separate community.

> Use mods at your own risk. Valve may change what is permitted at any time, and modifying game
> files can carry consequences for your account. Only ever install mods you understand.

---

## When Deadlock updates

Game updates can change or move the files your mod replaced, which may break it.

After an update, open the app. If anything is affected, the **Overview** page shows a warning
listing the projects built against the older version. Open a project, click **Check game update**,
and if repairs are available click **Repair and rebuild** - the app re-points each replacement at
the current file and opens the export dialog so you can build a fresh `.vpk`.

Anything it cannot match automatically is listed for you to fix by hand.

---

## Troubleshooting

**"Windows protected your PC"**
The app is not code-signed yet. Click **More info → Run anyway**.

**The setup checklist will not go green**
Every red X row has a button on the right that tells you which file it wants. The most common
mistake is selecting the wrong CSDK level - pick the folder containing `csdkcfg.exe`, not a folder
inside it. Note that **Source 2 Viewer CLI** is a separate file from the Source 2 Viewer app;
"Download all requirements" fetches both.

**The build fails**
Open **Projects**, click the project's **Build & export** button, and expand **Per-item build
logs**. Each replacement shows the exact tool
that ran and what it printed, which usually names the problem file. **Retry failed items**
rebuilds only what failed.

**My mod stopped working after a Deadlock update**
See [When Deadlock updates](#when-deadlock-updates) above.

**Something else**
Open an issue on the [issue tracker](https://github.com/nickf1130/deadlock-mod-maker/issues) and
include the contents of the `logs` folder next to the `.exe`.

---

## What you supply, and what the app downloads

| Tool | Where it comes from |
| --- | --- |
| CSDK 12 | You supply it. Never copied or modified. |
| Deadlock install | You supply it. Only read, never written to. |
| FFmpeg / FFprobe | Downloaded by the app when you click **Download all requirements**. |
| Source 2 Viewer + CLI | Downloaded by the app when you click **Download all requirements**. |

Downloads only ever start when you press that button. Each one must come from its publisher's own
GitHub release over HTTPS and must match the SHA-256 digest that release publishes; anything that
fails either check is discarded instead of installed. Verified tools are installed into the app's
own `tools` folder.

---

## Building from source

For developers only - if you just want to use the app, download the release above.

Requirements: Windows 10/11, Node.js 20.19+ (or 22.12+), and Python 3.12 or 3.13.

```powershell
npm ci
npm run python:sync
```

Run in development:

```powershell
npm run dev
```

Run the checks:

```powershell
npm run typecheck
npm run test:all
npm run audit:python
```

Produce a portable Windows build in `release/`:

```powershell
npm run dist
```

`npm run dist` creates a clean Python environment before packaging, verifies the
portable layout, and writes a `.sha256` checksum beside the executable.

---

## Licence

Deadlock Mod Maker is free software released under the **GNU General Public License, version 3 or
later**. You may use, study, share and modify it. If you distribute a modified version, it must
also be released under the GPL with its source available. The full terms are in
[LICENSE.md](LICENSE.md). Bundled font attribution is in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

Deadlock and all related assets are the property of Valve Corporation. This tool bundles no Valve
content and does not redistribute any game files. FFmpeg and Source 2 Viewer are downloaded from
their own publishers and remain under their own licences.