import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { once } from "node:events";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { expect, test } from "@playwright/test";
import { _electron as electron } from "playwright";

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const VPK_SIGNATURE = 0x55aa1234;

async function pathExists(candidate: string): Promise<boolean> {
  try {
    await access(candidate);
    return true;
  } catch {
    return false;
  }
}

async function writeVpk(target: string, entries: Record<string, Buffer>): Promise<void> {
  const grouped = new Map<string, Map<string, Array<{ filename: string; payload: Buffer }>>>();
  for (const [internalPath, payload] of Object.entries(entries)) {
    const normalized = internalPath.replaceAll("\\", "/");
    const extensionWithDot = path.posix.extname(normalized);
    const extension = extensionWithDot ? extensionWithDot.slice(1) : " ";
    const directoryValue = path.posix.dirname(normalized);
    const directory = directoryValue === "." ? " " : directoryValue;
    const filename = path.posix.basename(normalized, extensionWithDot);
    if (!grouped.has(extension)) grouped.set(extension, new Map());
    const directories = grouped.get(extension)!;
    if (!directories.has(directory)) directories.set(directory, []);
    directories.get(directory)!.push({ filename, payload });
  }
  const tree: Buffer[] = [];
  const data: Buffer[] = [];
  let offset = 0;
  const string = (value: string) => Buffer.from(`${value}\0`, "utf8");
  for (const [extension, directories] of grouped) {
    tree.push(string(extension));
    for (const [directory, files] of directories) {
      tree.push(string(directory));
      for (const file of files) {
        tree.push(string(file.filename));
        const metadata = Buffer.alloc(18);
        metadata.writeUInt32LE(0, 0);
        metadata.writeUInt16LE(0, 4);
        metadata.writeUInt16LE(0x7fff, 6);
        metadata.writeUInt32LE(offset, 8);
        metadata.writeUInt32LE(file.payload.length, 12);
        metadata.writeUInt16LE(0xffff, 16);
        tree.push(metadata);
        data.push(file.payload);
        offset += file.payload.length;
      }
      tree.push(Buffer.from([0]));
    }
    tree.push(Buffer.from([0]));
  }
  tree.push(Buffer.from([0]));
  const treeBuffer = Buffer.concat(tree);
  const header = Buffer.alloc(12);
  header.writeUInt32LE(VPK_SIGNATURE, 0);
  header.writeUInt32LE(1, 4);
  header.writeUInt32LE(treeBuffer.length, 8);
  await writeFile(target, Buffer.concat([header, treeBuffer, ...data]));
}

test("desktop shell exposes the consolidated roadmap workflow", async ({}, testInfo) => {
  const appData = testInfo.outputPath("app-data");
  await mkdir(path.join(appData, "data"), { recursive: true });
  const fakeDeadlock = path.join(appData, "fixture-deadlock");
  await mkdir(path.join(fakeDeadlock, "game", "citadel"), { recursive: true });
  await writeVpk(path.join(fakeDeadlock, "game", "citadel", "pak01_dir.vpk"), {
    "sounds/ui/e2e_fixture.vsnd_c": Buffer.from("fixture")
  });
  await writeFile(
    path.join(appData, "data", "settings.json"),
    JSON.stringify({
      setupCompleted: true,
      tutorialCompleted: true,
      deadlockRootOverride: fakeDeadlock
    })
  );
  const firstPackage = testInfo.outputPath("first_mod.vpk");
  const secondPackage = testInfo.outputPath("second_mod.pak");
  const combinedPackage = testInfo.outputPath("combined_mod.vpk");
  await writeVpk(firstPackage, {
    "sounds/shared.vsnd_c": Buffer.from("first"),
    "sounds/first_only.vsnd_c": Buffer.from("one")
  });
  await writeVpk(secondPackage, {
    "sounds/shared.vsnd_c": Buffer.from("second"),
    "materials/second_only.vmat_c": Buffer.from("two")
  });
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] =>
        entry[0] !== "ELECTRON_RUN_AS_NODE" && typeof entry[1] === "string"
    )
  );
  const packagedExecutable = process.env.DSS_DESKTOP_EXECUTABLE;
  const application = await electron.launch({
    ...(packagedExecutable
      ? { executablePath: path.resolve(packagedExecutable), args: [] }
      : { args: [workspace] }),
    cwd: workspace,
    env: {
      ...environment,
      DSS_SKIP_UPDATE_CHECK: "1",
      ...(packagedExecutable
        ? { PORTABLE_EXECUTABLE_DIR: appData }
        : { DSS_TEST_APP_ROOT: appData })
    }
  });

  try {
    const page = await application.firstWindow();
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator(".brand .brand-mark img")).toHaveCSS("width", "21px");
    await expect(page.locator("body")).toHaveCSS("font-size", "16px");
    expect(
      await page.evaluate(() => ({
        regular: document.fonts.check('400 16px "Google Sans"'),
        semibold: document.fonts.check('600 16px "Google Sans"'),
        bodyFamily: getComputedStyle(document.body).fontFamily,
        bodyWeight: getComputedStyle(document.body).fontWeight,
        buttonFamily: getComputedStyle(document.querySelector("button")!).fontFamily
      }))
    ).toEqual({
      regular: true,
      semibold: true,
      bodyFamily: "\"Google Sans\"",
      bodyWeight: "400",
      buttonFamily: "\"Google Sans\""
    });
    expect(
      await page.evaluate(() => ({
        viewTransitionApi:
          typeof (
            document as Document & {
              startViewTransition?: (update: () => void) => unknown;
            }
          ).startViewTransition,
        headerTransitionName: getComputedStyle(
          document.querySelector(".topbar")!
        ).getPropertyValue("view-transition-name"),
        contentTransitionName: getComputedStyle(
          document.querySelector(".content")!
        ).getPropertyValue("view-transition-name"),
        appReveal: getComputedStyle(document.querySelector(".app-shell")!).animationName,
        buttonTransitions: getComputedStyle(
          document.querySelector(".sidebar nav button")!
        ).transitionProperty
      }))
    ).toEqual({
      viewTransitionApi: "function",
      headerTransitionName: "page-header",
      contentTransitionName: "page-content",
      appReveal: "app-shell-reveal",
      buttonTransitions: "transform, color, background-color, border-color"
    });

    const navigation = page.locator(".sidebar nav button");
    await expect(navigation).toHaveText([
      "Overview",
      "Sounds",
      "Visuals (WIP)",
      "Projects",
      "PAK Combiner",
      "Diagnostics",
      "About"
    ]);
    await expect(page.getByRole("button", { name: "Build & Export", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Batch Import", exact: true })).toHaveCount(0);
    await expect(page.getByText("Verified workflow", { exact: true })).toHaveCount(0);
    await expect(page.locator(".sidebar nav button").first()).toHaveCSS(
      "justify-content",
      "flex-start"
    );

    const workspaceBackground = await page.locator(".workspace").evaluate(
      (element) => getComputedStyle(element).backgroundImage
    );
    const overviewBackground = await page.locator(".overview-projects").evaluate(
      (element) => getComputedStyle(element).backgroundImage
    );
    expect(workspaceBackground).toBe("none");
    expect(overviewBackground).toBe("none");

    await page.getByRole("button", { name: "PAK Combiner", exact: true }).click();
    await expect(page.getByRole("heading", { name: "PAK Combiner", exact: true })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Inspect and combine PAK files", exact: true })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Choose package files" })).toBeVisible();
    expect(await page.evaluate(() => typeof window.studio.selectPackages)).toBe("function");
    expect(await page.evaluate(() => typeof window.studio.selectPackageOutput)).toBe("function");
    await application.evaluate(
      ({ dialog }, fixture) => {
        dialog.showOpenDialog = async () => ({
          canceled: false,
          filePaths: [fixture.firstPackage, fixture.secondPackage]
        });
        dialog.showSaveDialog = async () => ({
          canceled: false,
          filePath: fixture.combinedPackage
        });
      },
      { firstPackage, secondPackage, combinedPackage }
    );
    await page.getByRole("button", { name: "Choose package files" }).click();
    await expect(page.locator(".package-file")).toHaveCount(2);
    await expect(page.getByText("sounds/shared.vsnd_c", { exact: true })).toHaveCount(2);
    await expect(page.locator(".package-summary")).toContainText("1");
    await page.getByRole("button", { name: "Combine into one package" }).click();
    await expect(
      page.locator(".package-result").getByRole("heading", { name: "3 items written" })
    ).toBeVisible({ timeout: 15_000 });
    const combinedBytes = await readFile(combinedPackage);
    expect(combinedBytes.readUInt32LE(0)).toBe(VPK_SIGNATURE);
    await page.screenshot({
      path: testInfo.outputPath("package-combiner.png"),
      fullPage: true
    });

    await page.getByRole("button", { name: "Sounds", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sounds", exact: true })).toBeVisible();
    await expect(page.locator(".project-required")).toContainText(
      "Choose a project before making changes"
    );
    await page.getByRole("button", { name: "Create or select a project" }).click();
    await expect(
      page.getByRole("heading", { name: "Projects", exact: true, level: 1 })
    ).toBeVisible();
    await page.getByRole("button", { name: "Sounds", exact: true }).click();
    await expect(page.getByLabel("Sound scope")).toHaveValue("all");
    expect(
      await page
        .getByLabel("Sound scope")
        .locator("option")
        .evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))
    ).toEqual(["all", "heroes", "general"]);
    await expect(page.locator(".search-row select").nth(1)).toContainText(
      "Every category"
    );

    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.locator(".sound-list > .activity-bar")).not.toHaveClass(/is-active/, {
      timeout: 10_000
    });
    await expect(page.locator(".list-summary")).toContainText("catalog version");

    await page.getByRole("button", { name: "Visuals", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Visuals", exact: true })).toBeVisible();
    await expect(page.locator(".project-required")).toBeVisible();
    await expect(page.getByLabel("Visual resource kind")).toContainText(
      "Textures & materials"
    );
    await expect(
      page.getByPlaceholder("Texture or material filename/path…")
    ).toBeVisible();
    expect(await page.evaluate(() => typeof window.studio.selectVisual)).toBe("function");
    await expect(page.locator(".visual-browser")).toBeVisible();

    await page.getByRole("button", { name: "Diagnostics", exact: true }).click();
    await expect(page.locator(".diagnostic-checklist")).toBeVisible();
    await expect(page.locator(".diagnostic-row")).toHaveCount(13);
    await expect(page.locator(".diagnostic-selections .diagnostic-row")).toHaveCount(6);
    await expect(page.locator(".diagnostic-checklist .diagnostic-row")).toHaveCount(7);
    await expect(page.locator(".diagnostic-grid")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Choose CSDK folder" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Choose viewer file" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Choose CLI" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Choose Deadlock folder" })).toHaveCount(1);
    expect(await page.getByRole("button", { name: "Choose FFmpeg" }).count()).toBeGreaterThanOrEqual(1);
    await expect(page.getByRole("button", { name: "Download all requirements" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Choose path" })).toHaveCount(0);
    expect(await page.evaluate(() => typeof window.studio.selectFfmpeg)).toBe("function");
    expect(await page.locator(".diagnostic-row .status").first().textContent()).toBe("");
    await expect(page.locator(".diagnostic-checklist")).toHaveCSS("border-radius", "12px");
    await expect(page.locator(".diagnostic-copy strong").first()).toHaveCSS("font-size", "15px");
    await expect(page.locator(".diagnostic-copy code").first()).toHaveCSS(
      "font-family",
      "\"Google Sans\""
    );
    const diagnosticScroll = await page.locator(".content").evaluate((element) => {
      const before = element.scrollTop;
      element.scrollTop = element.scrollHeight;
      return {
        before,
        after: element.scrollTop,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight
      };
    });
    expect(diagnosticScroll.scrollHeight).toBeGreaterThan(diagnosticScroll.clientHeight);
    expect(diagnosticScroll.after).toBeGreaterThan(diagnosticScroll.before);
    await page.locator(".content").evaluate((element) => {
      element.scrollTop = 0;
    });
    await page.waitForTimeout(250);
    await page.screenshot({
      path: testInfo.outputPath("diagnostics-checklist.png"),
      fullPage: true
    });

    await page.getByRole("button", { name: "Projects", exact: true }).click();
    await page.getByPlaceholder("My mod").fill("Recoverable Test Mod");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("Recoverable Test Mod", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Build and export Recoverable Test Mod" }).click();
    await expect(
      page.getByRole("dialog").getByRole("heading", {
        name: "Build & export Recoverable Test Mod"
      })
    ).toBeVisible();
    await expect(page.getByRole("dialog").getByText("Process project", { exact: true })).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("project-export-modal.png"),
      fullPage: true
    });
    await page.getByRole("button", { name: "Close build and export" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Delete Recoverable Test Mod" })
    ).toHaveCSS("border-top-color", "rgb(38, 38, 38)");
    await page.getByRole("button", { name: "Delete Recoverable Test Mod" }).click();
    const deleteDialog = page.getByRole("alertdialog", {
      name: "Delete Recoverable Test Mod?"
    });
    await expect(deleteDialog).toBeVisible();
    await deleteDialog.getByRole("button", { name: "Delete project" }).click();
    await expect(page.getByRole("button", { name: "Delete Recoverable Test Mod" })).toHaveCount(0);
    expect(await pathExists(path.join(appData, "projects"))).toBe(false);
    expect(await pathExists(path.join(appData, "tools"))).toBe(false);
    expect(await pathExists(path.join(appData, "logs"))).toBe(false);
    expect(await pathExists(path.join(appData, "cache"))).toBe(false);

    await page.getByRole("button", { name: "About", exact: true }).click();
    await expect(page.getByRole("heading", { name: /Deadlock Mod Maker/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Check for updates" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Nick on GitHub" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Third-party notices" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Replay tutorial" })).toBeVisible();
    await page.getByRole("button", { name: "Replay tutorial" }).click();
    const tutorial = page.getByRole("dialog", { name: "Create your mod" });
    await expect(tutorial).toBeVisible();
    await expect(page.locator(".tutorial-spotlight")).toBeVisible();
    await tutorial.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("dialog", { name: "Find the original sound" })
    ).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("dialog", {
        name: "Choose and confirm replacement audio"
      })
    ).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("dialog", { name: "Review, build, and export" })
    ).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Finish" }).click();
    await expect(page.locator(".tutorial-card")).toHaveCount(0);
    await page.getByRole("button", { name: "About", exact: true }).click();
    const noticeDismiss = page.locator(".notice button");
    if (await noticeDismiss.isVisible()) await noticeDismiss.click();
    await page.waitForTimeout(250);

    await page.screenshot({
      path: testInfo.outputPath("desktop-shell.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});

test("first launch is gated by the complete setup checklist", async ({}, testInfo) => {
  const appData = testInfo.outputPath("first-run-app-data");
  await mkdir(appData, { recursive: true });
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] =>
        entry[0] !== "ELECTRON_RUN_AS_NODE" && typeof entry[1] === "string"
    )
  );
  const packagedExecutable = process.env.DSS_DESKTOP_EXECUTABLE;
  const application = await electron.launch({
    ...(packagedExecutable
      ? { executablePath: path.resolve(packagedExecutable), args: [] }
      : { args: [workspace] }),
    cwd: workspace,
    env: {
      ...environment,
      DSS_SKIP_UPDATE_CHECK: "1",
      ...(packagedExecutable
        ? { PORTABLE_EXECUTABLE_DIR: appData }
        : { DSS_TEST_APP_ROOT: appData })
    }
  });

  try {
    const page = await application.firstWindow();
    const wizard = page.locator(".setup-wizard");
    await expect(wizard).toBeVisible({ timeout: 30_000 });
    await expect(
      wizard.getByRole("heading", { name: "Set up required tools" })
    ).toBeVisible();
    await expect(wizard.locator(".diagnostic-row")).toHaveCount(13);
    await expect(wizard.getByRole("button", { name: "Finish setup" })).toBeVisible();
    await expect(wizard.getByRole("button", { name: /close/i })).toHaveCount(0);
    await expect(wizard.getByRole("button", { name: "Choose CSDK folder" })).toBeVisible();
    await expect(wizard.getByRole("button", { name: "Choose Deadlock folder" })).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("first-run-setup.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});

test("a second launch restores the existing window instead of starting another worker", async ({}, testInfo) => {
  const appData = testInfo.outputPath("single-instance-app-data");
  await mkdir(path.join(appData, "data"), { recursive: true });
  await writeFile(
    path.join(appData, "data", "settings.json"),
    JSON.stringify({
      setupCompleted: true,
      tutorialCompleted: true
    })
  );
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] =>
        entry[0] !== "ELECTRON_RUN_AS_NODE" && typeof entry[1] === "string"
    )
  );
  const packagedExecutable = process.env.DSS_DESKTOP_EXECUTABLE;
  const launchEnvironment = {
    ...environment,
    DSS_SKIP_UPDATE_CHECK: "1",
    ...(packagedExecutable
      ? { PORTABLE_EXECUTABLE_DIR: appData }
      : { DSS_TEST_APP_ROOT: appData })
  };
  const application = await electron.launch({
    ...(packagedExecutable
      ? { executablePath: path.resolve(packagedExecutable), args: [] }
      : { args: [workspace] }),
    cwd: workspace,
    env: launchEnvironment
  });

  let secondProcess: ReturnType<typeof spawn> | null = null;
  try {
    const page = await application.firstWindow();
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await application.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0]?.minimize();
    });
    await expect
      .poll(() =>
        application.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0]?.isMinimized()
        )
      )
      .toBe(true);

    const secondExecutable = packagedExecutable
      ? path.resolve(packagedExecutable)
      : path.join(workspace, "node_modules", "electron", "dist", "electron.exe");
    secondProcess = spawn(
      secondExecutable,
      packagedExecutable ? [] : [workspace],
      {
        cwd: workspace,
        env: launchEnvironment,
        windowsHide: true,
        stdio: "ignore"
      }
    );
    const exitCode = await Promise.race([
      once(secondProcess, "exit").then(([code]) => code),
      new Promise<never>((_resolve, reject) =>
        setTimeout(() => reject(new Error("Second instance did not exit")), 10_000)
      )
    ]);
    expect(exitCode).toBe(0);
    await expect
      .poll(() =>
        application.evaluate(({ BrowserWindow }) => {
          const window = BrowserWindow.getAllWindows()[0];
          return window ? { minimized: window.isMinimized(), visible: window.isVisible() } : null;
        })
      )
      .toEqual({ minimized: false, visible: true });
  } finally {
    if (secondProcess && secondProcess.exitCode === null) secondProcess.kill();
    await application.close();
  }
});

test("the optional sound tutorial appears once after setup", async ({}, testInfo) => {
  const appData = testInfo.outputPath("tutorial-app-data");
  const settingsFile = path.join(appData, "data", "settings.json");
  await mkdir(path.dirname(settingsFile), { recursive: true });
  await writeFile(
    settingsFile,
    JSON.stringify({
      setupCompleted: true,
      tutorialCompleted: false
    })
  );
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] =>
        entry[0] !== "ELECTRON_RUN_AS_NODE" && typeof entry[1] === "string"
    )
  );
  const packagedExecutable = process.env.DSS_DESKTOP_EXECUTABLE;
  const application = await electron.launch({
    ...(packagedExecutable
      ? { executablePath: path.resolve(packagedExecutable), args: [] }
      : { args: [workspace] }),
    cwd: workspace,
    env: {
      ...environment,
      DSS_SKIP_UPDATE_CHECK: "1",
      ...(packagedExecutable
        ? { PORTABLE_EXECUTABLE_DIR: appData }
        : { DSS_TEST_APP_ROOT: appData })
    }
  });

  try {
    const page = await application.firstWindow();
    const tutorial = page.getByRole("dialog", { name: "Create your mod" });
    await expect(tutorial).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".setup-wizard")).toHaveCount(0);
    await page.waitForTimeout(300);
    const tutorialBounds = await tutorial.boundingBox();
    expect(tutorialBounds).not.toBeNull();
    expect(tutorialBounds!.x).toBeGreaterThanOrEqual(0);
    expect(tutorialBounds!.y).toBeGreaterThanOrEqual(0);
    expect(tutorialBounds!.x + tutorialBounds!.width).toBeLessThanOrEqual(
      await page.evaluate(() => window.innerWidth)
    );
    expect(tutorialBounds!.y + tutorialBounds!.height).toBeLessThanOrEqual(
      await page.evaluate(() => window.innerHeight)
    );
    await page.screenshot({
      path: testInfo.outputPath("first-launch-tutorial.png"),
      fullPage: true
    });

    await tutorial.getByRole("button", { name: "Skip tutorial" }).click();
    await expect(page.locator(".tutorial-card")).toHaveCount(0);
    await expect
      .poll(async () => {
        const saved = JSON.parse(await readFile(settingsFile, "utf8"));
        return saved.tutorialCompleted;
      })
      .toBe(true);
  } finally {
    await application.close();
  }
});

test("a newer release is offered without blocking the user", async ({}, testInfo) => {
  const appData = testInfo.outputPath("update-app-data");
  const emptyDeadlock = path.join(appData, "empty-deadlock");
  await mkdir(path.join(appData, "data"), { recursive: true });
  await mkdir(emptyDeadlock, { recursive: true });
  await writeFile(
    path.join(appData, "data", "settings.json"),
    JSON.stringify({
      setupCompleted: true,
      tutorialCompleted: true,
      deadlockRootOverride: emptyDeadlock
    })
  );
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] =>
        entry[0] !== "ELECTRON_RUN_AS_NODE" && typeof entry[1] === "string"
    )
  );
  const packagedExecutable = process.env.DSS_DESKTOP_EXECUTABLE;
  const application = await electron.launch({
    ...(packagedExecutable
      ? { executablePath: path.resolve(packagedExecutable), args: [] }
      : { args: [workspace] }),
    cwd: workspace,
    env: {
      ...environment,
      DSS_FAKE_UPDATE_CHECK: "1",
      ...(packagedExecutable
        ? { PORTABLE_EXECUTABLE_DIR: appData }
        : { DSS_TEST_APP_ROOT: appData })
    }
  });

  try {
    const page = await application.firstWindow();
    const prompt = page.getByRole("alertdialog");
    await expect(prompt).toBeVisible({ timeout: 30_000 });
    await expect(
      prompt.getByRole("heading", {
        name: "Deadlock Mod Maker 9.9.9 Test Release"
      })
    ).toBeVisible();
    await expect(
      prompt.getByRole("button", { name: "Later", exact: true })
    ).toBeVisible();
    await prompt.getByRole("button", { name: "Later", exact: true }).click();
    await expect(prompt).toHaveCount(0);
    await page.getByRole("button", { name: "About", exact: true }).click();
    await expect(page.locator(".about-update")).toContainText(
      "Version 9.9.9 is available"
    );
    await expect(page.getByRole("button", { name: "View update" })).toBeVisible();
  } finally {
    await application.close();
  }
});
