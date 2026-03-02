"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { updateDocumentSettings, type DocInfo } from "@/lib/api";
import { Loader2 } from "lucide-react";

interface Props {
  kbId: string;
  doc: DocInfo;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

export function ChunkSettingsDialog({ kbId, doc, open, onOpenChange, onSaved }: Props) {
  const [chunkSize, setChunkSize] = useState<string>("");
  const [chunkOverlap, setChunkOverlap] = useState<string>("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setChunkSize(doc.chunk_size != null ? String(doc.chunk_size) : "");
      setChunkOverlap(doc.chunk_overlap != null ? String(doc.chunk_overlap) : "");
    }
  }, [open, doc.chunk_size, doc.chunk_overlap]);

  async function handleSave() {
    const cs = chunkSize ? parseInt(chunkSize, 10) : null;
    const co = chunkOverlap ? parseInt(chunkOverlap, 10) : null;
    if (cs != null && (cs < 64 || cs > 8192)) {
      alert("chunk_size 范围：64 ~ 8192");
      return;
    }
    if (co != null && (co < 0 || co > 4096)) {
      alert("chunk_overlap 范围：0 ~ 4096");
      return;
    }
    if (cs != null && co != null && co >= cs) {
      alert("chunk_overlap 必须小于 chunk_size");
      return;
    }
    setSaving(true);
    try {
      await updateDocumentSettings(kbId, doc.doc_id, {
        chunk_size: cs,
        chunk_overlap: co,
      });
      onSaved();
      onOpenChange(false);
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-sm">切分参数设置</DialogTitle>
          <p className="text-xs text-muted-foreground truncate">{doc.file_name}</p>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cs-size" className="text-xs text-muted-foreground">
              chunk_size
            </Label>
            <Input
              id="cs-size"
              type="number"
              min={64}
              max={8192}
              placeholder="1024"
              value={chunkSize}
              onChange={(e) => setChunkSize(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cs-overlap" className="text-xs text-muted-foreground">
              chunk_overlap
            </Label>
            <Input
              id="cs-overlap"
              type="number"
              min={0}
              max={4096}
              placeholder="128"
              value={chunkOverlap}
              onChange={(e) => setChunkOverlap(e.target.value)}
            />
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground">
          修改参数后，需重新向量化才能生效。已有向量将被清除并重建。
        </p>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
