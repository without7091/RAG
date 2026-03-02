"use client";

import { useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { uploadDocument } from "@/lib/api";
import { Loader2, Upload } from "lucide-react";

const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"];

interface Props {
  kbId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: () => void;
}

export function UploadDialog({ kbId, open, onOpenChange, onUploaded }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<{ name: string; ok: boolean; msg: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setResults([]);
    }
  }

  async function handleUpload() {
    if (files.length === 0) return;
    setUploading(true);
    const res: typeof results = [];
    let hasSuccess = false;

    for (const file of files) {
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        res.push({ name: file.name, ok: false, msg: `不支持的文件类型 ${ext}` });
        continue;
      }
      try {
        const r = await uploadDocument(kbId, file);
        res.push({ name: file.name, ok: true, msg: `已上传 (doc_id: ${r.doc_id.slice(0, 8)}...)` });
        hasSuccess = true;
      } catch (err) {
        res.push({ name: file.name, ok: false, msg: (err as Error).message });
      }
    }

    setResults(res);
    setUploading(false);
    if (hasSuccess) onUploaded();
  }

  function handleClose(v: boolean) {
    if (!v) {
      setFiles([]);
      setResults([]);
    }
    onOpenChange(v);
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>上传文档</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div
            className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => inputRef.current?.click()}
          >
            <Upload className="h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">
              点击选择文件 (PDF, DOCX, PPTX, XLSX, MD, TXT)
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ALLOWED_EXTENSIONS.join(",")}
              className="hidden"
              onChange={handleFiles}
            />
          </div>

          {files.length > 0 && (
            <div className="text-sm space-y-1">
              <p className="font-medium">已选择 {files.length} 个文件:</p>
              {files.map((f) => (
                <p key={f.name} className="text-muted-foreground truncate">
                  {f.name} ({(f.size / 1024).toFixed(1)} KB)
                </p>
              ))}
            </div>
          )}

          {results.length > 0 && (
            <div className="text-sm space-y-1 max-h-40 overflow-auto">
              {results.map((r, i) => (
                <p key={i} className={r.ok ? "text-green-600" : "text-destructive"}>
                  {r.name}: {r.msg}
                </p>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleClose(false)}>
            关闭
          </Button>
          <Button onClick={handleUpload} disabled={uploading || files.length === 0}>
            {uploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            上传
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
