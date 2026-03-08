"use client";

import { CheckCircle2, Circle, Loader2 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

const STEP_LABELS: Record<string, string> = {
  query_rewrite: "查询改写",
  embedding_query: "Query 向量化",
  hybrid_search: "混合检索",
  reranking: "重排序",
  skipping_reranker: "跳过重排序",
  context_synthesis: "上下文拼接",
  skipping_context_synthesis: "跳过上下文拼接",
  building_response: "构建响应",
};

interface Props {
  steps: { step: string; candidates?: number }[];
  running: boolean;
}

export function SSEProgress({ steps, running }: Props) {
  const hasQueryRewrite = steps.some((step) => step.step === "query_rewrite");
  const hasSkipReranker = steps.some((step) => step.step === "skipping_reranker");
  const hasContextSynthesis = steps.some(
    (step) =>
      step.step === "context_synthesis" ||
      step.step === "skipping_context_synthesis"
  );
  const hasSkipContextSynthesis = steps.some(
    (step) => step.step === "skipping_context_synthesis"
  );

  const rerankStep = hasSkipReranker ? "skipping_reranker" : "reranking";
  const contextStep = hasSkipContextSynthesis
    ? "skipping_context_synthesis"
    : "context_synthesis";
  const allSteps = [
    ...(hasQueryRewrite ? ["query_rewrite"] : []),
    "embedding_query",
    "hybrid_search",
    rerankStep,
    ...(hasContextSynthesis ? [contextStep] : []),
    "building_response",
  ];

  const completedSteps = new Set(steps.map((step) => step.step));
  const currentStep = steps.length > 0 ? steps[steps.length - 1].step : null;

  return (
    <Card className="shrink-0">
      <CardContent className="p-4">
        <div className="flex items-center gap-6">
          {allSteps.map((step) => {
            const done = completedSteps.has(step) && currentStep !== step;
            const active = currentStep === step && running;
            const stepData = steps.find((item) => item.step === step);

            return (
              <div key={step} className="flex items-center gap-2 text-sm">
                {done || (completedSteps.has(step) && !running) ? (
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                ) : active ? (
                  <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
                ) : (
                  <Circle className="h-4 w-4 text-muted-foreground/40" />
                )}
                <span
                  className={
                    active
                      ? "font-medium text-blue-600"
                      : done || (completedSteps.has(step) && !running)
                        ? "text-foreground"
                        : "text-muted-foreground/60"
                  }
                >
                  {STEP_LABELS[step] || step}
                </span>
                {stepData?.candidates !== undefined && (
                  <span className="text-xs text-muted-foreground">
                    （{stepData.candidates} 候选）
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
