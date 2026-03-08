"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { QueryInput } from "@/components/playground/query-input";
import { SSEProgress } from "@/components/playground/sse-progress";
import { ContextPanel } from "@/components/playground/context-panel";
import { SourceCards } from "@/components/playground/source-cards";
import {
  listKBs,
  retrieveSSE,
  type KBInfo,
  type RetrieveResponse,
} from "@/lib/api";

export default function PlaygroundPage() {
  const [kbs, setKbs] = useState<KBInfo[]>([]);
  const [selectedKb, setSelectedKb] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(10);
  const [topN, setTopN] = useState(3);
  const [enableReranker, setEnableReranker] = useState(true);
  const [enableContextSynthesis, setEnableContextSynthesis] = useState(true);
  const [enableQueryRewrite, setEnableQueryRewrite] = useState(false);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<{ step: string; candidates?: number }[]>([]);
  const [result, setResult] = useState<RetrieveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    listKBs()
      .then((res) => {
        setKbs(res.knowledge_bases);
        if (res.knowledge_bases.length > 0) {
          setSelectedKb(res.knowledge_bases[0].knowledge_base_id);
        }
      })
      .catch(() => {});
  }, []);

  const handleRetrieve = useCallback(() => {
    if (!selectedKb || !query.trim()) return;

    setRunning(true);
    setSteps([]);
    setResult(null);
    setError(null);
    setHighlightIdx(null);

    abortRef.current?.();
    abortRef.current = retrieveSSE(
      {
        user_id: "playground",
        knowledge_base_id: selectedKb,
        query: query.trim(),
        top_k: topK,
        top_n: topN,
        enable_reranker: enableReranker,
        enable_context_synthesis: enableContextSynthesis,
        enable_query_rewrite: enableQueryRewrite,
        stream: true,
      },
      {
        onStatus(step, candidates) {
          setSteps((prev) => [...prev, { step, candidates }]);
        },
        onResult(res) {
          setResult(res);
          setRunning(false);
        },
        onError(err) {
          setError(err);
          setRunning(false);
        },
      }
    );
  }, [
    selectedKb,
    query,
    topK,
    topN,
    enableReranker,
    enableContextSynthesis,
    enableQueryRewrite,
  ]);

  return (
    <div className="space-y-4 h-full flex flex-col">
      <h1 className="text-2xl font-bold shrink-0">检索调试台</h1>

      <QueryInput
        kbs={kbs}
        selectedKb={selectedKb}
        onSelectKb={setSelectedKb}
        query={query}
        onQueryChange={setQuery}
        topK={topK}
        onTopKChange={setTopK}
        topN={topN}
        onTopNChange={setTopN}
        enableReranker={enableReranker}
        onEnableRerankerChange={setEnableReranker}
        enableContextSynthesis={enableContextSynthesis}
        onEnableContextSynthesisChange={setEnableContextSynthesis}
        enableQueryRewrite={enableQueryRewrite}
        onEnableQueryRewriteChange={setEnableQueryRewrite}
        onRetrieve={handleRetrieve}
        running={running}
      />

      {(running || steps.length > 0) && <SSEProgress steps={steps} running={running} />}

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {result && (
        <div className="flex-1 min-h-0 flex gap-4">
          <div className="flex-1 min-w-0">
            <ContextPanel
              sourceNodes={result.source_nodes}
              highlightIdx={highlightIdx}
            />
          </div>
          <div className="w-96 shrink-0">
            <SourceCards
              sourceNodes={result.source_nodes}
              onHighlight={setHighlightIdx}
              highlightIdx={highlightIdx}
            />
          </div>
        </div>
      )}
    </div>
  );
}
