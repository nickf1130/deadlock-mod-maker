import { useMemo, useState, type ReactNode } from "react";
import { AudioLines, ChevronDown, ChevronRight, Folder, FolderOpen } from "lucide-react";
import type { BrowsableAsset, CatalogFolder } from "../types";

// One folder of the catalog, plus its own files. Folders that only ever hold
// other folders never arrive from the backend - see buildFolderTree.
type TreeNode = {
  name: string;
  path: string;
  directFileCount: number;
  // Everything below this folder as well, so a collapsed folder can still say
  // how much is inside it.
  totalFileCount: number;
  children: TreeNode[];
};

// The backend reports only folders that directly hold a file, because those are
// the only ones it can see. "sounds/vo" holds nothing itself - every file is a
// level or two deeper - so it never appears, and a tree built from the list
// alone would have holes where the game has folders. Rebuild the missing ones
// from the path segments.
export function buildFolderTree(folders: CatalogFolder[]): TreeNode[] {
  const roots: TreeNode[] = [];
  const byPath = new Map<string, TreeNode>();

  function ensure(path: string): TreeNode {
    const existing = byPath.get(path);
    if (existing) return existing;
    const cut = path.lastIndexOf("/");
    const node: TreeNode = {
      // Files sitting at the very top of the archive have no folder name.
      name: path === "" ? "(root)" : path.slice(cut + 1),
      path,
      directFileCount: 0,
      totalFileCount: 0,
      children: []
    };
    byPath.set(path, node);
    if (cut === -1) roots.push(node);
    else ensure(path.slice(0, cut)).children.push(node);
    return node;
  }

  for (const entry of folders) {
    ensure(entry.folder).directFileCount = entry.fileCount;
  }

  function rollUp(node: TreeNode): number {
    node.children.sort((a, b) => a.name.localeCompare(b.name));
    node.totalFileCount =
      node.directFileCount + node.children.reduce((sum, child) => sum + rollUp(child), 0);
    return node.totalFileCount;
  }
  roots.forEach(rollUp);
  return roots.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Which folders are open and what has been fetched for them.
 *
 * Both catalog pages need exactly this, and keeping it in one place is not
 * only tidiness: the first version of this logic was written out twice and had
 * the same bug in both copies, described below.
 *
 * `browse` is called at most once per folder. Reopening a folder is instant
 * because the files are kept.
 */
export function useFolderBrowser<T extends BrowsableAsset>(
  browse: (folder: string) => Promise<T[]>,
  onError: (message: string) => void
) {
  const [openFolders, setOpenFolders] = useState<Set<string>>(new Set());
  const [filesByFolder, setFilesByFolder] = useState<Record<string, T[]>>({});
  const [loadingFolders, setLoadingFolders] = useState<Set<string>>(new Set());

  async function toggleFolder(folder: string) {
    // Decide from the state this render is showing, never from inside the
    // updater below. React runs updaters during render rather than at the call
    // site, so a flag assigned in one is still unset by the time the next line
    // reads it. That is worth spelling out because the broken version appears
    // to work: with no update pending React evaluates the updater eagerly, so
    // the first folder opened does load its files, and every one after it
    // silently does not.
    const opening = !openFolders.has(folder);
    setOpenFolders((current) => {
      const next = new Set(current);
      if (opening) next.add(folder);
      else next.delete(folder);
      return next;
    });
    if (!opening || filesByFolder[folder]) return;

    setLoadingFolders((current) => new Set(current).add(folder));
    try {
      const files = await browse(folder);
      setFilesByFolder((current) => ({ ...current, [folder]: files }));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingFolders((current) => {
        const next = new Set(current);
        next.delete(folder);
        return next;
      });
    }
  }

  return {
    openFolders,
    filesByFolder,
    loadingFolders,
    toggleFolder,
    // Called when a filter changes, because everything fetched so far
    // describes the previous one.
    forgetFiles: () => setFilesByFolder({})
  };
}

// Draws the catalog the way it is laid out inside the archive. Purely
// presentational: the page above owns which folders are open and which files
// have been fetched, because it is the one that knows how to fetch them.
export function ResourceTree<T extends BrowsableAsset>({
  folders,
  filesByFolder,
  openFolders,
  loadingFolders,
  selectedId,
  onToggle,
  onSelect,
  icon: FileIcon,
  renderTags
}: {
  folders: CatalogFolder[];
  filesByFolder: Record<string, T[]>;
  openFolders: Set<string>;
  loadingFolders: Set<string>;
  selectedId: string | null;
  onToggle: (folder: string) => void;
  onSelect: (file: T) => void;
  icon: typeof AudioLines;
  renderTags?: (file: T) => ReactNode;
}) {
  const tree = useMemo(() => buildFolderTree(folders), [folders]);

  function renderNode(node: TreeNode, depth: number): ReactNode {
    const open = openFolders.has(node.path);
    const files = filesByFolder[node.path] ?? [];
    // Indent by nesting level. The archive goes 7 deep at most, so this stays
    // readable without needing to scroll sideways.
    const indent = { paddingLeft: `${depth * 14 + 10}px` };
    return (
      <li key={node.path}>
        <button
          className="tree-folder"
          style={indent}
          aria-expanded={open}
          onClick={() => onToggle(node.path)}
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {open ? <FolderOpen size={15} /> : <Folder size={15} />}
          <span className="tree-name">{node.name}</span>
          <span className="tree-count">{node.totalFileCount.toLocaleString()}</span>
        </button>
        {open && (
          <ul>
            {node.children.map((child) => renderNode(child, depth + 1))}
            {loadingFolders.has(node.path) && (
              <li className="tree-loading" style={{ paddingLeft: `${(depth + 1) * 14 + 10}px` }}>
                Loading {node.directFileCount.toLocaleString()} files…
              </li>
            )}
            {files.map((file) => (
              <li key={file.id}>
                <button
                  className={`tree-file${selectedId === file.id ? " selected" : ""}`}
                  style={{ paddingLeft: `${(depth + 1) * 14 + 10}px` }}
                  onClick={() => onSelect(file)}
                  title={file.internalPath}
                >
                  <FileIcon size={14} />
                  <span className="tree-name">{file.filename}</span>
                  {renderTags?.(file)}
                </button>
              </li>
            ))}
          </ul>
        )}
      </li>
    );
  }

  return <ul className="resource-tree">{tree.map((node) => renderNode(node, 0))}</ul>;
}
