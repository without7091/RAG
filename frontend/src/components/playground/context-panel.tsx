"use client";

import { useRef, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { SourceNode } from "@/lib/api";

interface Props {
  sourceNodes: SourceNode[];
  highlightIdx: number | null;
}

export function ContextPanel({ sourceNodes, highlightIdx }: Props) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (highlightIdx !== null && refs.current[highlightIdx]) {
      refs.current[highlightIdx]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightIdx]);

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">上下文内容</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-0">
        <ScrollArea className="h-full px-4 pb-4">
          <div className="space-y-4">
            {sourceNodes.map((node, i) => (
              <div
                key={i}
                ref={(el) => { refs.current[i] = el; }}
                className={cn(
                  "rounded-md border p-3 text-sm leading-relaxed whitespace-pre-wrap transition-colors",
                  highlightIdx === i
                    ? "border-primary bg-primary/5"
                    : "border-border"
                )}
              >
                <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium">#{i + 1}</span>
                  {node.header_path && (
                    <span className="truncate">{node.header_path}</span>
                  )}
                </div>
                {node.context_text || node.text}
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
