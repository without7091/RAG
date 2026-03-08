"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
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
import {
  createKBFolder,
  type KBFolderInfo,
  updateKBFolder,
} from "@/lib/api";

interface KBFolderDialogProps {
  open: boolean;
  folder?: KBFolderInfo | null;
  parentFolder?: KBFolderInfo | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (folder: KBFolderInfo, mode: "created" | "updated") => void;
}

export function KBFolderDialog({
  open,
  folder,
  parentFolder,
  onOpenChange,
  onSaved,
}: KBFolderDialogProps) {
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      setName("");
      setError("");
      setLoading(false);
      return;
    }

    setName(folder?.folder_name ?? "");
    setError("");
  }, [folder, open]);

  const title = useMemo(() => {
    if (folder) {
      return folder.depth === 1 ? "重命名一级目录" : "重命名二级目录";
    }
    return parentFolder ? "新建二级目录" : "新建一级目录";
  }, [folder, parentFolder]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;

    setLoading(true);
    setError("");
    try {
      let savedFolder: KBFolderInfo;
      let mode: "created" | "updated";
      if (folder) {
        savedFolder = await updateKBFolder(folder.folder_id, { folder_name: name.trim() });
        mode = "updated";
      } else {
        savedFolder = await createKBFolder({
          folder_name: name.trim(),
          parent_folder_id: parentFolder?.folder_id,
        });
        mode = "created";
      }
      onOpenChange(false);
      onSaved(savedFolder, mode);
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
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {parentFolder && !folder && (
            <div className="space-y-2">
              <Label>所属一级目录</Label>
              <Input value={parentFolder.folder_name} disabled />
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="folder-name">目录名称</Label>
            <Input
              id="folder-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={parentFolder ? "例如：子项目A" : "例如：项目A"}
              maxLength={128}
              required
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
