"use client";

import { useEffect, useMemo, useState } from "react";
import { FolderPlus, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  deleteKB,
  deleteKBFolder,
  type KBFolderInfo,
  type KBInfo,
  type KBTreeRootFolderNode,
} from "@/lib/api";
import { KBCreateDialog } from "./kb-create-dialog";
import { KBEditDialog } from "./kb-edit-dialog";
import { KBFolderDialog } from "./kb-folder-dialog";
import { KBTree } from "./kb-tree";

interface KBListProps {
  tree: KBTreeRootFolderNode[];
  selectedKb: string | null;
  selectedFolderId: string | null;
  loading: boolean;
  onSelect: (kbId: string | null) => void;
  onSelectFolder: (folderId: string | null) => void;
  onRefresh: (options?: { preferredKbId?: string | null }) => void;
}

const EXPANDED_FOLDERS_STORAGE_KEY = "data-governance.expanded-folder-ids";

function findFirstKbId(tree: KBTreeRootFolderNode[]): string | null {
  for (const root of tree) {
    for (const child of root.children) {
      const firstKb = child.knowledge_bases[0];
      if (firstKb) {
        return firstKb.knowledge_base_id;
      }
    }
  }

  return null;
}

function collectFolderIds(tree: KBTreeRootFolderNode[]): Set<string> {
  const folderIds = new Set<string>();

  tree.forEach((root) => {
    folderIds.add(root.folder_id);
    root.children.forEach((child) => folderIds.add(child.folder_id));
  });

  return folderIds;
}

function findFolderPath(tree: KBTreeRootFolderNode[], folderId: string | null): string[] {
  if (folderId == null) {
    return [];
  }

  for (const root of tree) {
    if (root.folder_id === folderId) {
      return [root.folder_id];
    }

    for (const child of root.children) {
      if (child.folder_id === folderId) {
        return [root.folder_id, child.folder_id];
      }
    }
  }

  return [];
}

function findKbFolderPath(tree: KBTreeRootFolderNode[], kbId: string | null): string[] {
  if (kbId == null) {
    return [];
  }

  for (const root of tree) {
    for (const child of root.children) {
      if (child.knowledge_bases.some((kb) => kb.knowledge_base_id === kbId)) {
        return [root.folder_id, child.folder_id];
      }
    }
  }

  return [];
}

function findKbFolderId(tree: KBTreeRootFolderNode[], kbId: string | null): string | null {
  const [, childFolderId] = findKbFolderPath(tree, kbId);
  return childFolderId ?? null;
}

function findFirstChildFolderId(tree: KBTreeRootFolderNode[], rootFolderId: string): string | null {
  const rootFolder = tree.find((root) => root.folder_id === rootFolderId);
  return rootFolder?.children[0]?.folder_id ?? null;
}

function getDefaultExpandedFolderIds(
  tree: KBTreeRootFolderNode[],
  selectedFolderId: string | null,
  selectedKb: string | null
): Set<string> {
  const selectedFolderPath = findFolderPath(tree, selectedFolderId);
  if (selectedFolderPath.length > 0) {
    return new Set(selectedFolderPath);
  }

  const selectedKbPath = findKbFolderPath(tree, selectedKb ?? findFirstKbId(tree));
  if (selectedKbPath.length > 0) {
    return new Set(selectedKbPath);
  }

  return new Set(tree.map((root) => root.folder_id));
}

function readStoredExpandedFolderIds(validFolderIds: Set<string>): Set<string> | null {
  if (typeof window === "undefined") {
    return null;
  }

  const storedValue = window.localStorage.getItem(EXPANDED_FOLDERS_STORAGE_KEY);
  if (storedValue == null) {
    return null;
  }

  try {
    const parsed = JSON.parse(storedValue);
    if (!Array.isArray(parsed)) {
      return null;
    }

    return new Set(
      parsed.filter((folderId): folderId is string => {
        return typeof folderId === "string" && validFolderIds.has(folderId);
      })
    );
  } catch {
    return null;
  }
}

function resolveCreateKbFolderId(
  tree: KBTreeRootFolderNode[],
  selectedFolderId: string | null,
  selectedKb: string | null,
  fallbackFolderId: string | null
): string | null {
  if (selectedFolderId != null) {
    const selectedFolderPath = findFolderPath(tree, selectedFolderId);
    if (selectedFolderPath.length === 2) {
      return selectedFolderId;
    }

    if (selectedFolderPath.length === 1) {
      return findFirstChildFolderId(tree, selectedFolderId) ?? fallbackFolderId;
    }
  }

  return findKbFolderId(tree, selectedKb) ?? fallbackFolderId;
}

export function KBList({
  tree,
  selectedKb,
  selectedFolderId,
  loading,
  onSelect,
  onSelectFolder,
  onRefresh,
}: KBListProps) {
  const [showRootCreate, setShowRootCreate] = useState(false);
  const [createParentFolder, setCreateParentFolder] = useState<KBFolderInfo | null>(null);
  const [editingFolder, setEditingFolder] = useState<KBFolderInfo | null>(null);
  const [showCreateKb, setShowCreateKb] = useState(false);
  const [createKbFolderId, setCreateKbFolderId] = useState<string | null>(null);
  const [editingKb, setEditingKb] = useState<KBInfo | null>(null);
  const [deletingFolderId, setDeletingFolderId] = useState<string | null>(null);
  const [deletingKbId, setDeletingKbId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(new Set());
  const [hasInitializedExpandedFolders, setHasInitializedExpandedFolders] = useState(false);

  useEffect(() => {
    const validFolderIds = collectFolderIds(tree);

    setExpandedFolderIds((prev) => {
      if (!hasInitializedExpandedFolders && tree.length > 0) {
        const storedExpandedFolderIds = readStoredExpandedFolderIds(validFolderIds);
        if (storedExpandedFolderIds != null) {
          return storedExpandedFolderIds;
        }

        return getDefaultExpandedFolderIds(tree, selectedFolderId, selectedKb);
      }

      return new Set(Array.from(prev).filter((folderId) => validFolderIds.has(folderId)));
    });

    if (!hasInitializedExpandedFolders && tree.length > 0) {
      setHasInitializedExpandedFolders(true);
    }
  }, [hasInitializedExpandedFolders, selectedFolderId, selectedKb, tree]);

  useEffect(() => {
    if (typeof window === "undefined" || !hasInitializedExpandedFolders) {
      return;
    }

    window.localStorage.setItem(
      EXPANDED_FOLDERS_STORAGE_KEY,
      JSON.stringify(Array.from(expandedFolderIds))
    );
  }, [expandedFolderIds, hasInitializedExpandedFolders]);

  const folderOptions = useMemo(
    () =>
      tree.flatMap((root) =>
        root.children.map((child) => ({
          folderId: child.folder_id,
          label: `${root.folder_name} / ${child.folder_name}`,
        }))
      ),
    [tree]
  );

  const createKbInitialFolderId = useMemo(
    () =>
      resolveCreateKbFolderId(tree, selectedFolderId, selectedKb, folderOptions[0]?.folderId ?? null),
    [folderOptions, selectedFolderId, selectedKb, tree]
  );

  function toggleFolder(folderId: string) {
    setExpandedFolderIds((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) {
        next.delete(folderId);
      } else {
        next.add(folderId);
      }
      return next;
    });
  }

  function ensureExpanded(folderIds: Array<string | null | undefined>) {
    setExpandedFolderIds((prev) => {
      const next = new Set(prev);
      let changed = false;

      folderIds.forEach((folderId) => {
        if (folderId && !next.has(folderId)) {
          next.add(folderId);
          changed = true;
        }
      });

      return changed ? next : prev;
    });
  }

  async function handleDeleteKb(kbId: string) {
    if (!confirm("确定要删除此知识集吗？所有文件和向量数据将一并删除。")) return;

    setDeletingKbId(kbId);
    try {
      await deleteKB(kbId);
      if (selectedKb === kbId) {
        onSelect(null);
      }
      onRefresh();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setDeletingKbId(null);
    }
  }

  async function handleDeleteFolder(folderId: string) {
    if (!confirm("确定要删除此目录吗？仅空目录允许删除。")) return;

    setDeletingFolderId(folderId);
    try {
      await deleteKBFolder(folderId);
      onRefresh();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setDeletingFolderId(null);
    }
  }

  async function handleCopyKbId(kbId: string) {
    try {
      await navigator.clipboard.writeText(kbId);
      setCopiedId(kbId);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      // ignore clipboard fallback
    }
  }

  function handleFolderSaved(folder: KBFolderInfo, mode: "created" | "updated") {
    if (mode === "created") {
      ensureExpanded([folder.parent_folder_id, folder.folder_id]);
      onSelectFolder(folder.folder_id);
    }

    onRefresh();
  }

  function handleKbCreated(kb: KBInfo) {
    ensureExpanded([kb.parent_folder_id, kb.folder_id]);
    onSelect(kb.knowledge_base_id);
    onRefresh({ preferredKbId: kb.knowledge_base_id });
  }

  return (
    <>
      <Card className="flex h-full flex-col">
        <CardHeader className="gap-3 pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">知识集目录</CardTitle>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setShowRootCreate(true)}>
              <FolderPlus className="mr-1 h-4 w-4" />
              新建项目
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setCreateKbFolderId(createKbInitialFolderId);
                setShowCreateKb(true);
              }}
              disabled={folderOptions.length === 0}
            >
              <Plus className="mr-1 h-4 w-4" />
              新建知识集
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex-1 min-h-0 p-0">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : tree.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">暂无目录</p>
          ) : (
            <ScrollArea className="h-full px-2 pb-2">
              <KBTree
                tree={tree}
                selectedKb={selectedKb}
                selectedFolderId={selectedFolderId}
                copiedId={copiedId}
                deletingFolderId={deletingFolderId}
                deletingKbId={deletingKbId}
                expandedFolderIds={expandedFolderIds}
                onToggleFolder={toggleFolder}
                onSelectFolder={onSelectFolder}
                onSelectKb={onSelect}
                onCreateChildFolder={setCreateParentFolder}
                onCreateKb={(folderId) => {
                  setCreateKbFolderId(folderId);
                  setShowCreateKb(true);
                }}
                onEditFolder={setEditingFolder}
                onEditKb={setEditingKb}
                onDeleteFolder={handleDeleteFolder}
                onDeleteKb={handleDeleteKb}
                onCopyKbId={handleCopyKbId}
              />
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      <KBFolderDialog
        open={showRootCreate}
        onOpenChange={setShowRootCreate}
        onSaved={handleFolderSaved}
      />
      <KBFolderDialog
        open={createParentFolder !== null}
        parentFolder={createParentFolder}
        onOpenChange={(open) => {
          if (!open) setCreateParentFolder(null);
        }}
        onSaved={handleFolderSaved}
      />
      <KBFolderDialog
        open={editingFolder !== null}
        folder={editingFolder}
        onOpenChange={(open) => {
          if (!open) setEditingFolder(null);
        }}
        onSaved={handleFolderSaved}
      />
      <KBCreateDialog
        open={showCreateKb}
        folderOptions={folderOptions}
        initialFolderId={createKbFolderId ?? createKbInitialFolderId}
        onOpenChange={(open) => {
          setShowCreateKb(open);
          if (!open) setCreateKbFolderId(null);
        }}
        onCreated={handleKbCreated}
      />
      <KBEditDialog
        kb={editingKb}
        folderOptions={folderOptions}
        open={editingKb !== null}
        onOpenChange={(open) => {
          if (!open) setEditingKb(null);
        }}
        onUpdated={onRefresh}
      />
    </>
  );
}
