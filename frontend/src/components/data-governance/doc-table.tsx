"use client";

import { useState } from "react";
import { Upload, Trash2, Loader2, RefreshCw, Eye, RotateCw, Download, Play, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  deleteDocument,
  retryDocument,
  getDocumentDownloadUrl,
  vectorizeDocuments,
  type DocInfo,
} from "@/lib/api";
import { UploadDialog } from "./upload-dialog";
import { DocPreviewSheet } from "./doc-preview-sheet";
import { ChunkSettingsDialog } from "./chunk-settings-dialog";

const statusBadge: Record<string, { label: string; className: string }> = {
  uploaded: { label: "已上传", className: "bg-gray-100 text-gray-800" },
  initializing: { label: "初始化", className: "bg-yellow-100 text-yellow-800" },
  pending: { label: "等待中", className: "bg-yellow-100 text-yellow-800" },
  parsing: { label: "解析中", className: "bg-blue-100 text-blue-800" },
  chunking: { label: "分块中", className: "bg-blue-100 text-blue-800" },
  embedding: { label: "嵌入中", className: "bg-blue-100 text-blue-800" },
  upserting: { label: "入库中", className: "bg-blue-100 text-blue-800" },
  completed: { label: "已完成", className: "bg-green-100 text-green-800" },
  failed: { label: "失败", className: "bg-red-100 text-red-800" },
};

/** Map document status to progress percentage */
const statusProgress: Record<string, number> = {
  uploaded: 0,
  initializing: 2,
  pending: 5,
  parsing: 15,
  chunking: 35,
  embedding: 60,
  upserting: 85,
  completed: 100,
  failed: 100,
};

interface DocTableProps {
  kbId: string | null;
  docs: DocInfo[];
  loading: boolean;
  onRefresh: (silent?: boolean) => void;
  onKbRefresh: () => void;
  onDocStatusUpdate?: (docIds: string[], status: string) => void;
}

export function DocTable({ kbId, docs, loading, onRefresh, onKbRefresh, onDocStatusUpdate }: DocTableProps) {
  const [showUpload, setShowUpload] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [vectorizing, setVectorizing] = useState(false);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [previewDoc, setPreviewDoc] = useState<{ kbId: string; docId: string } | null>(null);
  const [settingsDoc, setSettingsDoc] = useState<DocInfo | null>(null);

  // Selectable = not currently processing
  const selectableDocs = docs.filter(
    (d) => d.status === "uploaded" || d.status === "failed" || d.status === "completed"
  );
  const unvectorizedDocs = selectableDocs.filter(
    (d) => d.status === "uploaded" || d.status === "failed"
  );
  const allSelected = selectableDocs.length > 0 && selectableDocs.every((d) => selectedDocs.has(d.doc_id));
  const someSelected = selectedDocs.size > 0 && !allSelected;

  // Three-state select: empty → unvectorized (uploaded+failed) → all selectable → empty
  function toggleSelectAll() {
    if (selectedDocs.size === 0) {
      // Empty → select unvectorized
      if (unvectorizedDocs.length > 0) {
        setSelectedDocs(new Set(unvectorizedDocs.map((d) => d.doc_id)));
      } else {
        // No unvectorized files, select all selectable
        setSelectedDocs(new Set(selectableDocs.map((d) => d.doc_id)));
      }
    } else if (!allSelected) {
      // Partial → select all selectable
      setSelectedDocs(new Set(selectableDocs.map((d) => d.doc_id)));
    } else {
      // All → deselect
      setSelectedDocs(new Set());
    }
  }

  function toggleSelect(docId: string) {
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  }

  async function handleVectorize() {
    if (!kbId || selectedDocs.size === 0) return;
    const docIds = Array.from(selectedDocs);
    setVectorizing(true);
    try {
      await vectorizeDocuments(kbId, docIds);
      onDocStatusUpdate?.(docIds, "initializing");
      setSelectedDocs(new Set());
      onRefresh(true);
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setVectorizing(false);
    }
  }

  async function handleDelete(docId: string) {
    if (!kbId) return;
    if (!confirm("确定要删除此文档？")) return;
    setDeleting(docId);
    try {
      await deleteDocument(kbId, docId);
      setSelectedDocs((prev) => { const n = new Set(prev); n.delete(docId); return n; });
      onRefresh(true);
      onKbRefresh();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  async function handleRetry(docId: string) {
    if (!kbId) return;
    setRetrying(docId);
    try {
      await retryDocument(kbId, docId);
      onDocStatusUpdate?.([docId], "initializing");
      setRetrying(null);
      onRefresh(true);
    } catch (err) {
      setRetrying(null);
      alert((err as Error).message);
    }
  }

  function handleDownload(docId: string) {
    if (!kbId) return;
    const url = getDocumentDownloadUrl(kbId, docId);
    window.open(url, "_blank");
  }

  if (!kbId) {
    return (
      <Card className="h-full flex items-center justify-center">
        <p className="text-muted-foreground">请在左侧选择一个知识库</p>
      </Card>
    );
  }

  return (
    <TooltipProvider delayDuration={300}>
      <Card className="h-full flex flex-col">
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <CardTitle className="text-base">文档列表</CardTitle>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="default"
              onClick={handleVectorize}
              disabled={vectorizing || selectedDocs.size === 0}
            >
              {vectorizing ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              ) : (
                <Play className="h-4 w-4 mr-1" />
              )}
              向量化{selectedDocs.size > 0 ? ` (${selectedDocs.size})` : ""}
            </Button>
            <Button size="sm" variant="outline" onClick={() => onRefresh()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button size="sm" onClick={() => setShowUpload(true)}>
              <Upload className="h-4 w-4 mr-1" />
              上传文档
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex-1 min-h-0 overflow-auto p-0">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : docs.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">
              暂无文档，点击上方按钮上传
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[40px]">
                    {docs.length > 0 && (
                      <Checkbox
                        checked={allSelected ? true : someSelected ? "indeterminate" : false}
                        onCheckedChange={toggleSelectAll}
                        aria-label="全选"
                      />
                    )}
                  </TableHead>
                  <TableHead>文件名</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">切片数</TableHead>
                  <TableHead>切分参数</TableHead>
                  <TableHead>上传时间</TableHead>
                  <TableHead className="w-[150px]">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.map((doc) => {
                  const badge = statusBadge[doc.status] || {
                    label: doc.status,
                    className: "",
                  };
                  const isProcessing =
                    doc.status !== "completed" &&
                    doc.status !== "failed" &&
                    doc.status !== "uploaded";
                  const isVectorizeBusy = isProcessing || retrying === doc.doc_id;
                  const pct = statusProgress[doc.status] ?? 0;

                  return (
                    <TableRow key={doc.doc_id}>
                      <TableCell>
                        <Checkbox
                          checked={selectedDocs.has(doc.doc_id)}
                          onCheckedChange={() => toggleSelect(doc.doc_id)}
                          disabled={isProcessing}
                          aria-label={`选择 ${doc.file_name}`}
                        />
                      </TableCell>
                      <TableCell className="font-medium max-w-[200px]">
                        <span className="truncate inline-block max-w-[170px] align-middle">
                          {doc.file_name}
                        </span>
                        {doc.is_pre_chunked && (
                          <Badge variant="outline" className="ml-1.5 text-[10px] px-1.5 py-0 border-blue-300 text-blue-600 bg-blue-50 align-middle">
                            切片
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="space-y-1.5 min-w-[160px]">
                          <Badge variant="secondary" className={badge.className}>
                            {isProcessing && (
                              <Loader2 className="h-3 w-3 animate-spin mr-1" />
                            )}
                            {badge.label}
                          </Badge>
                          {isProcessing && (
                            <>
                              <Progress value={pct} className="h-1.5" />
                              {doc.progress_message && (
                                <p className="text-[11px] text-muted-foreground truncate">
                                  {doc.progress_message}
                                </p>
                              )}
                            </>
                          )}
                          {doc.status === "failed" && doc.error_message && (
                            <p className="text-[11px] text-red-600 break-words line-clamp-2" title={doc.error_message}>
                              {doc.error_message}
                            </p>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">{doc.chunk_count}</TableCell>
                      <TableCell className="text-xs">
                        {doc.is_pre_chunked ? (
                          <span className="text-muted-foreground">预切片文档</span>
                        ) : (
                          <div className="space-y-1">
                            <div className="font-mono text-[11px]">
                              {doc.effective_chunk_size} / {doc.effective_chunk_overlap}
                            </div>
                            <div className="text-muted-foreground">
                              {doc.chunk_size == null && doc.chunk_overlap == null ? "默认" : "自定义"}
                            </div>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {new Date(doc.upload_timestamp).toLocaleString("zh-CN")}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-0.5">
                          {/* Preview */}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => setPreviewDoc({ kbId: kbId!, docId: doc.doc_id })}
                              >
                                <Eye className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>查看详情与切片</TooltipContent>
                          </Tooltip>

                          {/* Chunk settings */}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => setSettingsDoc(doc)}
                                disabled={doc.is_pre_chunked}
                              >
                                <Settings className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              {doc.is_pre_chunked ? "切片文档无需切分参数" : "切分参数设置"}
                            </TooltipContent>
                          </Tooltip>

                          {/* Vectorize */}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => handleRetry(doc.doc_id)}
                                disabled={isVectorizeBusy}
                              >
                                {isVectorizeBusy ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <RotateCw className="h-3.5 w-3.5" />
                                )}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>向量化</TooltipContent>
                          </Tooltip>

                          {/* Download */}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => handleDownload(doc.doc_id)}
                              >
                                <Download className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              {doc.is_pre_chunked ? "下载切片源文件" : "下载原文件"}
                            </TooltipContent>
                          </Tooltip>

                          {/* Delete */}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                                onClick={() => handleDelete(doc.doc_id)}
                                disabled={deleting === doc.doc_id}
                              >
                                {deleting === doc.doc_id ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Trash2 className="h-3.5 w-3.5" />
                                )}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>删除文档</TooltipContent>
                          </Tooltip>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {kbId && (
        <UploadDialog
          kbId={kbId}
          open={showUpload}
          onOpenChange={setShowUpload}
          onUploaded={() => {
            onRefresh(true);
            onKbRefresh();
          }}
        />
      )}

      {previewDoc && (
        <DocPreviewSheet
          kbId={previewDoc.kbId}
          docId={previewDoc.docId}
          open={true}
          onOpenChange={(open) => {
            if (!open) setPreviewDoc(null);
          }}
        />
      )}

      {settingsDoc && kbId && (
        <ChunkSettingsDialog
          kbId={kbId}
          doc={settingsDoc}
          open={true}
          onOpenChange={(open) => {
            if (!open) setSettingsDoc(null);
          }}
          onSaved={onRefresh}
        />
      )}
    </TooltipProvider>
  );
}
