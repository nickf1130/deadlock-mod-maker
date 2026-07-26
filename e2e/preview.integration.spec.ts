import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { _electron as electron } from "playwright";

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("exports and plays a real indexed sound with configured local tools", async () => {
  test.skip(
    process.env.DSS_PREVIEW_INTEGRATION !== "1",
    "Requires the locally configured Deadlock archive, Source2Viewer CLI, and FFmpeg tools."
  );
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] =>
        entry[0] !== "ELECTRON_RUN_AS_NODE" && typeof entry[1] === "string"
    )
  );
  const packagedExecutable = process.env.DSS_PREVIEW_EXECUTABLE;
  const application = await electron.launch({
    ...(packagedExecutable
      ? { executablePath: path.resolve(packagedExecutable), args: [] }
      : { args: [workspace] }),
    cwd: workspace,
    env: {
      ...environment,
      DSS_TEST_APP_ROOT: workspace,
      PORTABLE_EXECUTABLE_DIR: workspace
    }
  });

  try {
    const page = await application.firstWindow();
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Sounds", exact: true }).click();
    await page
      .getByPlaceholder("Filename, path, hero, ability, event…")
      .fill("abrams_a2_charge_wall_impact");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const result = page.locator(".asset-list button").first();
    await expect(result).toBeVisible({ timeout: 20_000 });
    await result.click();

    const exportButton = page.getByRole("button", {
      name: "Export & preview original",
      exact: true
    });
    await expect(exportButton).toBeEnabled();
    await exportButton.click();
    const originalPlayer = page.locator(".player").first();
    await expect(originalPlayer.getByText("Ready", { exact: true })).toBeVisible({
      timeout: 30_000
    });
    await originalPlayer.getByRole("button", { name: "Play", exact: true }).click();
    await expect(originalPlayer.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  } finally {
    await application.close();
  }
});
