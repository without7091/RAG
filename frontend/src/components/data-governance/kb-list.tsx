"use client";

import { useState } from "react";
import { Plus, Trash2, Loader2, Pencil, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { deleteKB, type KBInfo } from "@/lib/api";
import { KBCreateDialog } from "./kb-create-dialog";
import { KBEditDialog } from "./kb-edit-dialog";

interface KBListProps {
  kbs: KBInfo[];
  selectedKb: string | null;
  loading: boolean;
  onSelect: (kbId: string | null) => void;
  onRefresh: () => void;
}

export function KBList({ kbs, selectedKb, loading, onSelect, onRefresh }: KBListProps) {
  const [showCreate, setShowCreate] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [editingKb, setEditingKb] = useState<KBInfo | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  async function handleDelete(kbId: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("确定要删除此知识库？所有文档和向量数据将一并删除。")) return;
    setDeleting(kbId);
    try {
      await deleteKB(kbId);
      if (selectedKb === kbId) onSelect(null);
      onRefresh();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  function handleEdit(kb: KBInfo, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingKb(kb);
  }

  async function handleCopy(kbId: string, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(kbId);
      setCopiedId(kbId);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      // Fallback ignored
    }
  }

  return (
    <>
      <Card className="h-full flex flex-col">
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <CardTitle className="text-base">知识库</CardTitle>
          <Button size="sm" variant="outline" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4 mr-1" />
            新建
          </Button>
        </CardHeader>
        <CardContent className="flex-1 min-h-0 p-0">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : kbs.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">
              暂无知识库
            </p>
          ) : (
            <ScrollArea className="h-full px-2 pb-2">
              <div className="space-y-1">
                {kbs.map((kb) => (
                  <div
                    key={kb.knowledge_base_id}
                    role="button"
                    onClick={() => onSelect(kb.knowledge_base_id)}
                    className={cn(
                      "group flex items-center justify-between rounded-md px-3 py-2 text-sm cursor-pointer transition-colors",
                      selectedKb === kb.knowledge_base_id
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-accent"
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">
                        {kb.knowledge_base_name}
                      </div>
                      <div className="flex items-center gap-1">
                        <span
                          className={cn(
                            "text-xs font-mono truncate",
                            selectedKb === kb.knowledge_base_id
                              ? "text-primary-foreground/70"
                              : "text-muted-foreground"
                          )}
                        >
                          {kb.knowledge_base_id}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => handleCopy(kb.knowledge_base_id, e)}
                          className={cn(
                            "inline-flex items-center justify-center h-4 w-4 rounded shrink-0",
                            "opacity-0 group-hover:opacity-100 transition-opacity",
                            selectedKb === kb.knowledge_base_id
                              ? "hover:bg-primary-foreground/20 text-primary-foreground/70"
                              : "hover:bg-accent-foreground/10 text-muted-foreground"
                          )}
                        >
                          {copiedId === kb.knowledge_base_id ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <Copy className="h-3 w-3" />
                          )}
                        </button>
                      </div>
                      <div
                        className={cn(
                          "text-xs",
                          selectedKb === kb.knowledge_base_id
                            ? "text-primary-foreground/70"
                            : "text-muted-foreground"
                        )}
                      >
                        {kb.document_count} 个文档
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5 shrink-0 ml-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100"
                        onClick={(e) => handleEdit(kb, e)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100"
                        onClick={(e) => handleDelete(kb.knowledge_base_id, e)}
                        disabled={deleting === kb.knowledge_base_id}
                      >
                        {deleting === kb.knowledge_base_id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
      <KBCreateDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        onCreated={onRefresh}
      />
      <KBEditDialog
        kb={editingKb}
        open={editingKb !== null}
        onOpenChange={(open) => { if (!open) setEditingKb(null); }}
        onUpdated={onRefresh}
      />
    </>
  );
}
