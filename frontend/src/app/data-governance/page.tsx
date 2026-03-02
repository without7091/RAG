"use client";

import { useEffect, useState, useCallback } from "react";
import { KBList } from "@/components/data-governance/kb-list";
import { DocTable } from "@/components/data-governance/doc-table";
import { listKBs, listDocuments, type KBInfo, type DocInfo } from "@/lib/api";

export default function DataGovernancePage() {
  const [kbs, setKbs] = useState<KBInfo[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocInfo[]>([]);
  const [loadingKbs, setLoadingKbs] = useState(true);
  const [loadingDocs, setLoadingDocs] = useState(false);

  const refreshKbs = useCallback(() => {
    setLoadingKbs(true);
    listKBs()
      .then((res) => setKbs(res.knowledge_bases))
      .catch(() => {})
      .finally(() => setLoadingKbs(false));
  }, []);

  useEffect(() => {
    refreshKbs();
  }, [refreshKbs]);

  const refreshDocs = useCallback((kbId: string, silent = false) => {
    if (!silent) setLoadingDocs(true);
    listDocuments(kbId)
      .then((res) => {
        if (silent) {
          // Preserve optimistic "initializing" status until backend catches up
          setDocs((prev) =>
            res.documents.map((newDoc) => {
              const oldDoc = prev.find((d) => d.doc_id === newDoc.doc_id);
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
      .catch(() => {})  // preserve existing docs on error
      .finally(() => { if (!silent) setLoadingDocs(false); });
  }, []);

  useEffect(() => {
    if (selectedKb) {
      setDocs([]);  // clear stale docs from previous KB immediately
      refreshDocs(selectedKb);
    } else {
      setDocs([]);
    }
  }, [selectedKb, refreshDocs]);

  // Auto-refresh docs for processing documents
  useEffect(() => {
    if (!selectedKb) return;
    const hasProcessing = docs.some(
      (d) => d.status !== "completed" && d.status !== "failed"
    );
    if (!hasProcessing) return;

    const timer = setInterval(() => refreshDocs(selectedKb, true), 3000);
    return () => clearInterval(timer);
  }, [selectedKb, docs, refreshDocs]);

  // Optimistic status update — immediately reflect status change in UI
  const updateDocStatuses = useCallback(
    (docIds: string[], status: string) => {
      setDocs((prev) =>
        prev.map((d) => (docIds.includes(d.doc_id) ? { ...d, status: status as DocInfo["status"] } : d))
      );
    },
    []
  );

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">数据治理</h1>
      <div className="flex gap-4 h-[calc(100vh-10rem)]">
        <div className="w-72 shrink-0">
          <KBList
            kbs={kbs}
            selectedKb={selectedKb}
            loading={loadingKbs}
            onSelect={setSelectedKb}
            onRefresh={refreshKbs}
          />
        </div>
        <div className="flex-1 min-w-0">
          <DocTable
            kbId={selectedKb}
            docs={docs}
            loading={loadingDocs}
            onRefresh={(silent?: boolean) => selectedKb && refreshDocs(selectedKb, silent)}
            onKbRefresh={refreshKbs}
            onDocStatusUpdate={updateDocStatuses}
          />
        </div>
      </div>
    </div>
  );
}
