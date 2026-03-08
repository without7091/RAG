"use client";

import { useEffect, useMemo, useState } from "react";
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
import { createKB, type KBInfo } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2 } from "lucide-react";

interface Props {
  open: boolean;
  folderOptions: Array<{ folderId: string; label: string }>;
  initialFolderId?: string | null;
  onOpenChange: (open: boolean) => void;
  onCreated: (kb: KBInfo) => void;
}

export function KBCreateDialog({
  open,
  folderOptions,
  initialFolderId,
  onOpenChange,
  onCreated,
}: Props) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [folderId, setFolderId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fallbackFolderId = useMemo(
    () => initialFolderId ?? folderOptions[0]?.folderId ?? "",
    [folderOptions, initialFolderId]
  );

  useEffect(() => {
    if (!open) {
      setName("");
      setDesc("");
      setError("");
      setFolderId("");
      setLoading(false);
      return;
    }

    setFolderId(fallbackFolderId);
    setError("");
  }, [fallbackFolderId, open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !folderId) return;
    setLoading(true);
    setError("");
    try {
      const createdKb = await createKB({
        knowledge_base_name: name.trim(),
        folder_id: folderId,
        description: desc.trim(),
      });
      setName("");
      setDesc("");
      setFolderId("");
      onOpenChange(false);
      onCreated(createdKb);
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
          <DialogTitle>新建知识库</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="kb-name">知识库名称</Label>
            <Input
              id="kb-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：产品文档库"
              maxLength={128}
              required
            />
          </div>
          <div className="space-y-2">
            <Label>所属二级目录</Label>
            <Select value={folderId} onValueChange={setFolderId}>
              <SelectTrigger>
                <SelectValue placeholder="选择二级目录" />
              </SelectTrigger>
              <SelectContent>
                {folderOptions.map((folder) => (
                  <SelectItem key={folder.folderId} value={folder.folderId}>
                    {folder.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="kb-desc">描述 (可选)</Label>
            <Input
              id="kb-desc"
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
            <Button type="submit" disabled={loading || !name.trim() || !folderId}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              创建
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
