const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Knowledge Base ───

export interface KBInfo {
  knowledge_base_id: string;
  knowledge_base_name: string;
  description: string;
  document_count: number;
  created_at: string;
}

export interface KBListResponse {
  knowledge_bases: KBInfo[];
  total: number;
}

export interface KBCreateRequest {
  knowledge_base_name: string;
  description?: string;
}

export function listKBs() {
  return request<KBListResponse>("/kb/list");
}

export function createKB(data: KBCreateRequest) {
  return request<KBInfo & { knowledge_base_id: string }>("/kb/create", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface KBUpdateRequest {
  knowledge_base_name?: string;
  description?: string;
}

export function updateKB(kbId: string, data: KBUpdateRequest) {
  return request<KBInfo>(`/kb/${kbId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteKB(kbId: string) {
  return request<{ knowledge_base_id: string; deleted: boolean }>(
    `/kb/${kbId}`,
    { method: "DELETE" }
  );
}

// ─── Document ───

export type DocumentStatus =
  | "uploaded"
  | "pending"
  | "parsing"
  | "chunking"
  | "embedding"
  | "upserting"
  | "completed"
  | "failed"
  | "initializing";

export interface DocInfo {
  doc_id: string;
  file_name: string;
  knowledge_base_id: string;
  status: DocumentStatus;
  chunk_count: number;
  chunk_size: number | null;
  chunk_overlap: number | null;
  error_message: string | null;
  progress_message: string | null;
  upload_timestamp: string;
  updated_at: string;
}

export interface DocListResponse {
  documents: DocInfo[];
  total: number;
}

export function listDocuments(kbId: string) {
  return request<DocListResponse>(`/document/list/${kbId}`);
}

export async function uploadDocument(
  kbId: string,
  file: File,
  options?: { chunk_size?: number; chunk_overlap?: number },
) {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams({ knowledge_base_id: kbId });
  if (options?.chunk_size != null) params.set("chunk_size", String(options.chunk_size));
  if (options?.chunk_overlap != null) params.set("chunk_overlap", String(options.chunk_overlap));
  const res = await fetch(`${BASE}/document/upload?${params}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<{
    doc_id: string;
    file_name: string;
    knowledge_base_id: string;
    status: DocumentStatus;
    chunk_size: number | null;
    chunk_overlap: number | null;
  }>;
}

export function deleteDocument(kbId: string, docId: string) {
  return request<{ deleted: boolean }>(`/document/${kbId}/${docId}`, {
    method: "DELETE",
  });
}

// ─── Document Vectorize ───

export interface VectorizeDocInfo {
  doc_id: string;
  status: DocumentStatus;
}

export interface VectorizeResponse {
  docs: VectorizeDocInfo[];
}

export function vectorizeDocuments(
  kbId: string,
  docIds: string[],
  options?: { chunk_size?: number; chunk_overlap?: number },
) {
  return request<VectorizeResponse>("/document/vectorize", {
    method: "POST",
    body: JSON.stringify({
      knowledge_base_id: kbId,
      doc_ids: docIds,
      ...(options?.chunk_size != null && { chunk_size: options.chunk_size }),
      ...(options?.chunk_overlap != null && { chunk_overlap: options.chunk_overlap }),
    }),
  });
}

// ─── Document Chunks ───

export interface ChunkInfo {
  chunk_index: number;
  text: string;
  header_path: string;
}

export interface DocChunksResponse {
  doc_id: string;
  file_name: string;
  knowledge_base_id: string;
  status: DocumentStatus;
  chunk_count: number;
  chunks: ChunkInfo[];
}

export function getDocumentChunks(kbId: string, docId: string) {
  return request<DocChunksResponse>(`/document/${kbId}/${docId}/chunks`);
}

// ─── Document Retry ───

export interface DocRetryResponse {
  doc_id: string;
  status: DocumentStatus;
}

export function retryDocument(kbId: string, docId: string) {
  return request<DocRetryResponse>(`/document/${kbId}/${docId}/retry`, {
    method: "POST",
  });
}

// ─── Document Download ───

export function getDocumentDownloadUrl(kbId: string, docId: string) {
  return `${BASE}/document/${kbId}/${docId}/download`;
}

// ─── Document Settings ───

export interface DocSettingsRequest {
  chunk_size?: number | null;
  chunk_overlap?: number | null;
}

export interface DocSettingsResponse {
  doc_id: string;
  chunk_size: number | null;
  chunk_overlap: number | null;
}

export function updateDocumentSettings(kbId: string, docId: string, data: DocSettingsRequest) {
  return request<DocSettingsResponse>(`/document/${kbId}/${docId}/settings`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ─── Retrieval ───

export interface SourceNode {
  text: string;
  score: number;
  doc_id: string;
  file_name: string;
  knowledge_base_id: string;
  chunk_index: number | null;
  header_path: string | null;
  context_text: string | null;
  metadata: Record<string, unknown>;
}

export interface RetrieveRequest {
  user_id: string;
  knowledge_base_id: string;
  query: string;
  top_k?: number;
  top_n?: number;
  enable_reranker?: boolean;
  stream?: boolean;
}

export interface RetrieveResponse {
  query: string;
  knowledge_base_id: string;
  source_nodes: SourceNode[];
  total_candidates: number;
  top_k_used: number;
  top_n_used: number;
  min_score_used: number | null;
  enable_reranker_used: boolean;
}

export function retrieveJSON(data: RetrieveRequest) {
  return request<RetrieveResponse>("/retrieve", {
    method: "POST",
    body: JSON.stringify({ ...data, stream: false }),
  });
}

export function retrieveSSE(
  data: RetrieveRequest,
  handlers: {
    onStatus?: (step: string, candidates?: number) => void;
    onResult?: (result: RetrieveResponse) => void;
    onError?: (error: string) => void;
  }
) {
  const ctrl = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/retrieve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...data, stream: true }),
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) {
        handlers.onError?.(`HTTP ${res.status}`);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const json = JSON.parse(line.slice(5).trim());
            if (currentEvent === "status") {
              handlers.onStatus?.(json.step, json.candidates);
            } else if (currentEvent === "result") {
              handlers.onResult?.(json);
            } else if (currentEvent === "error") {
              handlers.onError?.(json.error);
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.((err as Error).message);
      }
    }
  })();

  return () => ctrl.abort();
}

// ─── Stats (to be added to backend) ───

export interface StatsResponse {
  total_knowledge_bases: number;
  total_documents: number;
  total_chunks: number;
  knowledge_bases: Array<{
    knowledge_base_id: string;
    knowledge_base_name: string;
    document_count: number;
  }>;
}

export function getStats() {
  return request<StatsResponse>("/stats");
}
