import React from "react";
import { AudioLines } from "lucide-react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResourceTree, buildFolderTree, useFolderBrowser } from "./ResourceTree";
import type { BrowsableAsset, CatalogFolder } from "../types";

const FOLDERS: CatalogFolder[] = [
  { folder: "sounds/ui", fileCount: 1 },
  { folder: "sounds/vo/hero_one", fileCount: 2 },
  { folder: "sounds/vo/hero_one/lines", fileCount: 1 }
];

const FILES: Record<string, BrowsableAsset[]> = {
  "sounds/vo/hero_one": [
    { id: "a", internalPath: "sounds/vo/hero_one/attack.vsnd_c", filename: "attack.vsnd_c" },
    { id: "b", internalPath: "sounds/vo/hero_one/death.vsnd_c", filename: "death.vsnd_c" }
  ]
};

describe("buildFolderTree", () => {
  it("rebuilds folders the backend never reports", () => {
    const tree = buildFolderTree(FOLDERS);

    // "sounds" and "sounds/vo" hold no files of their own, so neither appears
    // in the input, yet both have to exist for the tree to be navigable.
    expect(tree.map((node) => node.path)).toEqual(["sounds"]);
    expect(tree[0].children.map((node) => node.path)).toEqual(["sounds/ui", "sounds/vo"]);
    expect(tree[0].totalFileCount).toBe(4);
  });
});

// Drives the real hook the pages use, so this cannot drift away from them.
function Harness({ onFetch }: { onFetch: (folder: string) => Promise<BrowsableAsset[]> }) {
  const browser = useFolderBrowser<BrowsableAsset>(onFetch, () => {});
  return (
    <ResourceTree
      folders={FOLDERS}
      filesByFolder={browser.filesByFolder}
      openFolders={browser.openFolders}
      loadingFolders={browser.loadingFolders}
      selectedId={null}
      onToggle={(folder) => void browser.toggleFolder(folder)}
      onSelect={() => {}}
      icon={AudioLines}
    />
  );
}

async function openFolder(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${name}`) }));
  });
}

describe("ResourceTree", () => {
  it("reveals a folder's files when it is opened", async () => {
    const asked: string[] = [];
    render(
      <React.StrictMode>
        <Harness
          onFetch={async (folder) => {
            asked.push(folder);
            return FILES[folder] ?? [];
          }}
        />
      </React.StrictMode>
    );

    await openFolder("sounds");
    await openFolder("vo");
    await openFolder("hero_one");

    expect(asked).toContain("sounds/vo/hero_one");
    expect(screen.queryByText("attack.vsnd_c")).not.toBeNull();
    expect(screen.queryByText("death.vsnd_c")).not.toBeNull();
  });
});
