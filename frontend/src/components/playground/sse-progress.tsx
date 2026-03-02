"use client";

import { CheckCircle2, Loader2, Circle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

const STEP_LABELS: Record<string, string> = {
  embedding_query: "Query 向量化",
  hybrid_search: "混合检索",
  reranking: "重排序",
  building_response: "构建响应",
};

interface Props {
  steps: { step: string; candidates?: number }[];
  running: boolean;
}

export function SSEProgress({ steps, running }: Props) {
  const allSteps = ["embedding_query", "hybrid_search", "reranking", "building_response"];
  const completedSteps = new Set(steps.map((s) => s.step));
  const currentStep = steps.length > 0 ? steps[steps.length - 1].step : null;

  return (
    <Card className="shrink-0">
      <CardContent className="p-4">
        <div className="flex items-center gap-6">
          {allSteps.map((step) => {
            const done = completedSteps.has(step) && currentStep !== step;
            const active = currentStep === step && running;
            const stepData = steps.find((s) => s.step === step);

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
                    active ? "text-blue-600 font-medium" : done || (completedSteps.has(step) && !running) ? "text-foreground" : "text-muted-foreground/60"
                  }
                >
                  {STEP_LABELS[step] || step}
                </span>
                {stepData?.candidates !== undefined && (
                  <span className="text-xs text-muted-foreground">
                    ({stepData.candidates} 候选)
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
