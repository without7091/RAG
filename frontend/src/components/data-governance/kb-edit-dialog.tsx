"use client";

import { useEffect, useState } from "react";
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
import { updateKB, type KBInfo } from "@/lib/api";
import { Loader2 } from "lucide-react";

interface Props {
  kb: KBInfo | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: () => void;
}

export function KBEditDialog({ kb, open, onOpenChange, onUpdated }: Props) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (kb && open) {
      setName(kb.knowledge_base_name);
      setDesc(kb.description);
      setError("");
    }
  }, [kb, open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!kb || !name.trim()) return;
    setLoading(true);
    setError("");
    try {
      await updateKB(kb.knowledge_base_id, {
        knowledge_base_name: name.trim(),
        description: desc.trim(),
      });
      onOpenChange(false);
      onUpdated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>编辑知识库</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="kb-edit-name">知识库名称</Label>
            <Input
              id="kb-edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：产品文档库"
              maxLength={128}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="kb-edit-desc">描述 (可选)</Label>
            <Input
              id="kb-edit-desc"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="知识库用途说明"
              maxLength={512}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="submit" disabled={loading || !name.trim()}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
