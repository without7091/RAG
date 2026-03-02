"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { SourceNode } from "@/lib/api";

interface Props {
  sourceNodes: SourceNode[];
  onHighlight: (idx: number | null) => void;
  highlightIdx: number | null;
}

export function SourceCards({ sourceNodes, onHighlight, highlightIdx }: Props) {
  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Source Nodes</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-0">
        <ScrollArea className="h-full px-4 pb-4">
          <div className="space-y-3">
            {sourceNodes.map((node, i) => (
              <div
                key={i}
                role="button"
                onClick={() => onHighlight(highlightIdx === i ? null : i)}
                className={cn(
                  "rounded-md border p-3 cursor-pointer transition-colors",
                  highlightIdx === i
                    ? "border-primary bg-primary/5"
                    : "hover:border-primary/50"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium">#{i + 1}</span>
                  <Badge variant="secondary" className="text-xs">
                    {node.score.toFixed(4)}
                  </Badge>
                </div>
                <p className="text-sm line-clamp-3 text-muted-foreground">
                  {node.text}
                </p>
                <div className="mt-2 flex flex-wrap gap-1 text-xs text-muted-foreground">
                  <span className="truncate max-w-[180px]">{node.file_name}</span>
                  {node.chunk_index !== null && (
                    <span>chunk #{node.chunk_index}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
