"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DocTable } from "@/components/data-governance/doc-table";
import { KBList } from "@/components/data-governance/kb-list";
import { listDocuments, listKBTree, type DocInfo, type KBTreeRootFolderNode } from "@/lib/api";

function findFirstKbId(folders: KBTreeRootFolderNode[]): string | null {
  for (const root of folders) {
    for (const child of root.children) {
      const firstKb = child.knowledge_bases[0];
      if (firstKb) {
        return firstKb.knowledge_base_id;
      }
    }
  }
  return null;
}

function hasKbId(folders: KBTreeRootFolderNode[], kbId: string | null): boolean {
  if (kbId == null) {
    return false;
  }

  return folders.some((root) =>
    root.children.some((child) =>
      child.knowledge_bases.some((kb) => kb.knowledge_base_id === kbId)
    )
  );
}

function hasFolderId(folders: KBTreeRootFolderNode[], folderId: string | null): boolean {
  if (folderId == null) {
    return false;
  }

  return folders.some(
    (root) =>
      root.folder_id === folderId || root.children.some((child) => child.folder_id === folderId)
  );
}

interface TreeRefreshOptions {
  preferredKbId?: string | null;
}

export default function DataGovernancePage() {
  const [tree, setTree] = useState<KBTreeRootFolderNode[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocInfo[]>([]);
  const [loadingTree, setLoadingTree] = useState(true);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const selectedKbRef = useRef<string | null>(null);
  const selectedFolderIdRef = useRef<string | null>(null);

  const handleSelectKb = useCallback((kbId: string | null) => {
    selectedKbRef.current = kbId;
    selectedFolderIdRef.current = null;
    setSelectedKb(kbId);
    setSelectedFolderId(null);
    setDocs([]);
    setLoadingDocs(Boolean(kbId));
  }, []);

  const handleSelectFolder = useCallback((folderId: string | null) => {
    selectedFolderIdRef.current = folderId;
    selectedKbRef.current = null;
    setSelectedFolderId(folderId);
    setSelectedKb(null);
    setDocs([]);
    setLoadingDocs(false);
  }, []);

  const applyTree = useCallback((folders: KBTreeRootFolderNode[], options?: TreeRefreshOptions) => {
    setTree(folders);

    const preferredKbId = options?.preferredKbId ?? null;
    const currentKbId = selectedKbRef.current;
    const currentFolderId = selectedFolderIdRef.current;

    if (preferredKbId && hasKbId(folders, preferredKbId)) {
      if (currentKbId !== preferredKbId || currentFolderId !== null) {
        handleSelectKb(preferredKbId);
      }
      return;
    }

    if (hasKbId(folders, currentKbId)) {
      if (currentFolderId !== null) {
        selectedFolderIdRef.current = null;
        setSelectedFolderId(null);
      }
      return;
    }

    if (hasFolderId(folders, currentFolderId)) {
      if (currentKbId !== null) {
        handleSelectFolder(currentFolderId);
      }
      return;
    }

    handleSelectKb(findFirstKbId(folders));
  }, [handleSelectFolder, handleSelectKb]);

  const refreshTree = useCallback((options?: TreeRefreshOptions) => {
    setLoadingTree(true);
    listKBTree()
      .then((res) => applyTree(res.folders, options))
      .catch(() => {})
      .finally(() => setLoadingTree(false));
  }, [applyTree]);

  useEffect(() => {
    let cancelled = false;

    listKBTree()
      .then((res) => {
        if (cancelled) return;
        applyTree(res.folders);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingTree(false);
      });

    return () => {
      cancelled = true;
    };
  }, [applyTree]);

  const refreshDocs = useCallback((kbId: string, silent = false) => {
    if (!silent) setLoadingDocs(true);
    listDocuments(kbId)
      .then((res) => {
        if (silent) {
          setDocs((prev) =>
            res.documents.map((newDoc) => {
              const oldDoc = prev.find((doc) => doc.doc_id === newDoc.doc_id);
              if (
                oldDoc?.status === "initializing" &&
                (newDoc.status === "completed" ||
                  newDoc.status === "failed" ||
                  newDoc.status === "uploaded")
              ) {
                return { ...newDoc, status: "initializing" as DocInfo["status"] };
              }
              return newDoc;
            })
          );
        } else {
          setDocs(res.documents);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!silent) setLoadingDocs(false);
      });
  }, []);

  useEffect(() => {
    if (!selectedKb) return;

    let cancelled = false;

    listDocuments(selectedKb)
      .then((res) => {
        if (!cancelled) setDocs(res.documents);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingDocs(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedKb]);

  useEffect(() => {
    if (!selectedKb) return;
    const hasProcessing = docs.some(
      (doc) => doc.status !== "completed" && doc.status !== "failed"
    );
    if (!hasProcessing) return;

    const timer = setInterval(() => refreshDocs(selectedKb, true), 3000);
    return () => clearInterval(timer);
  }, [docs, refreshDocs, selectedKb]);

  const updateDocStatuses = useCallback((docIds: string[], status: string) => {
    setDocs((prev) =>
      prev.map((doc) =>
        docIds.includes(doc.doc_id) ? { ...doc, status: status as DocInfo["status"] } : doc
      )
    );
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">数据治理</h1>
      <div className="flex gap-4 h-[calc(100vh-10rem)]">
        <div className="w-80 shrink-0">
          <KBList
            tree={tree}
            selectedKb={selectedKb}
            selectedFolderId={selectedFolderId}
            loading={loadingTree}
            onSelect={handleSelectKb}
            onSelectFolder={handleSelectFolder}
            onRefresh={refreshTree}
          />
        </div>
        <div className="flex-1 min-w-0">
          <DocTable
            kbId={selectedKb}
            docs={docs}
            loading={loadingDocs}
            onRefresh={(silent?: boolean) => selectedKb && refreshDocs(selectedKb, silent)}
            onKbRefresh={refreshTree}
            onDocStatusUpdate={updateDocStatuses}
          />
        </div>
      </div>
    </div>
  );
}
