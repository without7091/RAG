"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { getDocumentChunks, type DocChunksResponse } from "@/lib/api";

interface Props {
  kbId: string;
  docId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DocPreviewSheet({ kbId, docId, open, onOpenChange }: Props) {
  const [data, setData] = useState<DocChunksResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    getDocumentChunks(kbId, docId)
      .then(setData)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, [open, kbId, docId]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-xl w-full flex flex-col">
        <SheetHeader>
          <SheetTitle className="text-base truncate">
            {data?.file_name ?? "文档详情"}
          </SheetTitle>
        </SheetHeader>

        {loading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-destructive text-sm">{error}</p>
          </div>
        ) : data ? (
          <div className="flex-1 flex flex-col min-h-0 gap-4">
            {/* Document metadata */}
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span className="text-muted-foreground">状态: </span>
                <Badge variant="secondary" className="ml-1">
                  {data.status}
                </Badge>
              </div>
              <div>
                <span className="text-muted-foreground">切片数: </span>
                <span className="font-medium">{data.chunk_count}</span>
              </div>
              <div className="col-span-2">
                <span className="text-muted-foreground">doc_id: </span>
                <code className="text-xs bg-muted px-1 py-0.5 rounded">
                  {data.doc_id}
                </code>
              </div>
            </div>

            <Separator />

            {/* Chunk list */}
            <div className="flex-1 min-h-0">
              <h3 className="text-sm font-medium mb-2">
                切片内容 ({data.chunks.length})
              </h3>
              {data.chunks.length === 0 ? (
                <p className="text-sm text-muted-foreground">暂无切片数据</p>
              ) : (
                <ScrollArea className="h-[calc(100%-2rem)]">
                  <div className="space-y-3 pr-4">
                    {data.chunks.map((chunk) => (
                      <div
                        key={chunk.chunk_index}
                        className="rounded-lg border p-3 text-sm"
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <Badge variant="outline" className="text-xs">
                            #{chunk.chunk_index}
                          </Badge>
                          {chunk.header_path && (
                            <span className="text-xs text-muted-foreground truncate">
                              {chunk.header_path}
                            </span>
                          )}
                        </div>
                        <pre className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground font-mono max-h-40 overflow-auto">
                          {chunk.text}
                        </pre>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
