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
import { uploadDocument, uploadChunks } from "@/lib/api";
import { Loader2, Upload, FileJson, ChevronDown, ChevronRight, AlertCircle, CheckCircle2 } from "lucide-react";

const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"];

type UploadMode = "file" | "chunks";

interface Props {
  kbId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: () => void;
}

interface ChunksValidation {
  valid: boolean;
  message: string;
}

function validateChunksJson(raw: string): ChunksValidation {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { valid: false, message: "JSON 解析失败，请检查文件格式" };
  }

  if (!Array.isArray(parsed)) {
    return { valid: false, message: "顶层结构必须为数组 []" };
  }
  if (parsed.length === 0) {
    return { valid: false, message: "切片数组不能为空" };
  }

  for (let i = 0; i < parsed.length; i++) {
    const item = parsed[i];
    if (typeof item !== "object" || item === null) {
      return { valid: false, message: `第 ${i + 1} 项不是有效对象` };
    }
    const obj = item as Record<string, unknown>;
    if (typeof obj.text !== "string" || obj.text.trim() === "") {
      return { valid: false, message: `第 ${i + 1} 项缺少非空 text 字段` };
    }
    if (obj.header_level !== undefined) {
      const hl = Number(obj.header_level);
      if (!Number.isInteger(hl) || hl < 0 || hl > 6) {
        return { valid: false, message: `第 ${i + 1} 项 header_level 必须为 0-6 整数` };
      }
    }
  }

  return { valid: true, message: `校验通过，共 ${parsed.length} 个切片` };
}

const PROTOCOL_EXAMPLE = `[
  {
    "text": "切片的文本内容（必填，非空）",
    "header_path": "一级标题 > 二级标题",
    "header_level": 2,
    "content_type": "text",
    "metadata": { "source": "custom" }
  }
]

字段说明:
  text          (必填) 切片文本内容，不能为空
  header_path   (可选) 标题路径，默认 ""
  header_level  (可选) 标题层级 0-6，默认 0
  content_type  (可选) 内容类型，默认 "text"
  metadata      (可选) 自定义元数据，默认 {}`;

export function UploadDialog({ kbId, open, onOpenChange, onUploaded }: Props) {
  const [mode, setMode] = useState<UploadMode>("file");

  // File mode state
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<{ name: string; ok: boolean; msg: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Chunks mode state
  const [chunksFile, setChunksFile] = useState<File | null>(null);
  const [chunksValidation, setChunksValidation] = useState<ChunksValidation | null>(null);
  const [showProtocol, setShowProtocol] = useState(false);
  const chunksInputRef = useRef<HTMLInputElement>(null);

  function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setResults([]);
    }
  }

  function handleChunksFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setChunksFile(file);
    setResults([]);
    setChunksValidation(null);

    const reader = new FileReader();
    reader.onload = () => {
      const text = reader.result as string;
      setChunksValidation(validateChunksJson(text));
    };
    reader.onerror = () => {
      setChunksValidation({ valid: false, message: "文件读取失败" });
    };
    reader.readAsText(file);
  }

  async function handleUpload() {
    if (mode === "file") {
      await handleFileUpload();
    } else {
      await handleChunksUpload();
    }
  }

  async function handleFileUpload() {
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

  async function handleChunksUpload() {
    if (!chunksFile || !chunksValidation?.valid) return;
    setUploading(true);
    try {
      const r = await uploadChunks(kbId, chunksFile);
      setResults([{
        name: chunksFile.name,
        ok: true,
        msg: `已上传 ${r.chunk_count} 个切片 (doc_id: ${r.doc_id.slice(0, 8)}...)`,
      }]);
      onUploaded();
    } catch (err) {
      setResults([{
        name: chunksFile.name,
        ok: false,
        msg: (err as Error).message,
      }]);
    } finally {
      setUploading(false);
    }
  }

  function switchMode(newMode: UploadMode) {
    setMode(newMode);
    setFiles([]);
    setChunksFile(null);
    setChunksValidation(null);
    setResults([]);
  }

  function handleClose(v: boolean) {
    if (!v) {
      setFiles([]);
      setChunksFile(null);
      setChunksValidation(null);
      setResults([]);
      setShowProtocol(false);
    }
    onOpenChange(v);
  }

  const canUpload =
    mode === "file"
      ? files.length > 0
      : chunksFile != null && chunksValidation?.valid === true;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>上传文档</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {/* Mode switcher */}
          <div className="flex rounded-lg border p-0.5 bg-muted/50">
            <button
              type="button"
              className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === "file"
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => switchMode("file")}
            >
              <Upload className="h-3.5 w-3.5 inline-block mr-1.5 -mt-0.5" />
              原始文件
            </button>
            <button
              type="button"
              className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === "chunks"
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => switchMode("chunks")}
            >
              <FileJson className="h-3.5 w-3.5 inline-block mr-1.5 -mt-0.5" />
              切片文件
            </button>
          </div>

          {/* File mode */}
          {mode === "file" && (
            <>
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
            </>
          )}

          {/* Chunks mode */}
          {mode === "chunks" && (
            <>
              <div
                className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 cursor-pointer hover:border-primary/50 transition-colors"
                onClick={() => chunksInputRef.current?.click()}
              >
                <FileJson className="h-8 w-8 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  点击选择切片 JSON 文件
                </p>
                <input
                  ref={chunksInputRef}
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={handleChunksFile}
                />
              </div>

              {chunksFile && (
                <div className="text-sm space-y-1">
                  <p className="text-muted-foreground truncate">
                    {chunksFile.name} ({(chunksFile.size / 1024).toFixed(1)} KB)
                  </p>
                </div>
              )}

              {chunksValidation && (
                <div className={`flex items-start gap-2 text-sm rounded-md px-3 py-2 ${
                  chunksValidation.valid
                    ? "bg-green-50 text-green-700 border border-green-200"
                    : "bg-red-50 text-red-700 border border-red-200"
                }`}>
                  {chunksValidation.valid ? (
                    <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
                  ) : (
                    <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                  )}
                  <span>{chunksValidation.message}</span>
                </div>
              )}

              {/* Protocol hint */}
              <div className="border rounded-md">
                <button
                  type="button"
                  className="flex items-center gap-1.5 w-full px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setShowProtocol(!showProtocol)}
                >
                  {showProtocol ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                  切片协议说明
                </button>
                {showProtocol && (
                  <pre className="px-3 pb-3 text-xs text-muted-foreground overflow-auto max-h-48 whitespace-pre-wrap font-mono">
                    {PROTOCOL_EXAMPLE}
                  </pre>
                )}
              </div>
            </>
          )}

          {/* Results */}
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
          <Button onClick={handleUpload} disabled={uploading || !canUpload}>
            {uploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            上传
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
