"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Loader2, Search } from "lucide-react";
import type { KBInfo } from "@/lib/api";

interface Props {
  kbs: KBInfo[];
  selectedKb: string;
  onSelectKb: (v: string) => void;
  query: string;
  onQueryChange: (v: string) => void;
  topK: number;
  onTopKChange: (v: number) => void;
  topN: number;
  onTopNChange: (v: number) => void;
  enableReranker: boolean;
  onEnableRerankerChange: (v: boolean) => void;
  enableContextSynthesis: boolean;
  onEnableContextSynthesisChange: (v: boolean) => void;
  enableQueryRewrite: boolean;
  onEnableQueryRewriteChange: (v: boolean) => void;
  onRetrieve: () => void;
  running: boolean;
}

export function QueryInput({
  kbs,
  selectedKb,
  onSelectKb,
  query,
  onQueryChange,
  topK,
  onTopKChange,
  topN,
  onTopNChange,
  enableReranker,
  onEnableRerankerChange,
  enableContextSynthesis,
  onEnableContextSynthesisChange,
  enableQueryRewrite,
  onEnableQueryRewriteChange,
  onRetrieve,
  running,
}: Props) {
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !running) {
      e.preventDefault();
      onRetrieve();
    }
  }

  return (
    <Card className="shrink-0">
      <CardContent className="p-4 space-y-4">
        <div className="flex gap-4 items-end">
          <div className="w-56">
            <Label className="text-xs mb-1 block">知识库</Label>
            <Select value={selectedKb} onValueChange={onSelectKb}>
              <SelectTrigger>
                <SelectValue placeholder="选择知识库" />
              </SelectTrigger>
              <SelectContent>
                {kbs.map((kb) => (
                  <SelectItem key={kb.knowledge_base_id} value={kb.knowledge_base_id}>
                    {kb.knowledge_base_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex-1">
            <Label className="text-xs mb-1 block">查询语句</Label>
            <Input
              placeholder="输入检索问题..."
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              onKeyDown={handleKeyDown}
            />
          </div>
          <Button onClick={onRetrieve} disabled={running || !selectedKb || !query.trim()}>
            {running ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            <span className="ml-1.5">检索</span>
          </Button>
        </div>
        <div className="flex gap-8 items-end">
          <div className="flex-1">
            <Label className="text-xs">
              Top-K (候选数量): {topK}
            </Label>
            <Slider
              min={1}
              max={50}
              step={1}
              value={[topK]}
              onValueChange={([v]) => onTopKChange(v)}
              className="mt-2"
            />
          </div>
          <div className="flex-1">
            <Label className="text-xs">
              Top-N (返回数量): {topN}
            </Label>
            <Slider
              min={1}
              max={20}
              step={1}
              value={[topN]}
              onValueChange={([v]) => onTopNChange(v)}
              className="mt-2"
            />
          </div>
          <div className="flex items-center gap-2 shrink-0 pb-0.5">
            <Switch
              id="reranker-toggle"
              checked={enableReranker}
              onCheckedChange={onEnableRerankerChange}
            />
            <Label htmlFor="reranker-toggle" className="text-xs cursor-pointer">
              Reranker
            </Label>
          </div>
          <div className="flex items-center gap-2 shrink-0 pb-0.5">
            <Switch
              id="context-synthesis-toggle"
              checked={enableContextSynthesis}
              onCheckedChange={onEnableContextSynthesisChange}
            />
            <Label htmlFor="context-synthesis-toggle" className="text-xs cursor-pointer">
              Context
            </Label>
          </div>
          <div className="flex items-center gap-2 shrink-0 pb-0.5">
            <Switch
              id="query-rewrite-toggle"
              checked={enableQueryRewrite}
              onCheckedChange={onEnableQueryRewriteChange}
            />
            <Label htmlFor="query-rewrite-toggle" className="text-xs cursor-pointer">
              Rewrite
            </Label>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
