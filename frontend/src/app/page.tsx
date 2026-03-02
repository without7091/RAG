"use client";

import { useEffect, useState } from "react";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { TaskBoard } from "@/components/dashboard/task-board";
import { listKBs, type KBInfo } from "@/lib/api";

export default function DashboardPage() {
  const [kbs, setKbs] = useState<KBInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listKBs()
      .then((res) => setKbs(res.knowledge_bases))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const totalDocs = kbs.reduce((sum, kb) => sum + kb.document_count, 0);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <StatsCards
        kbCount={kbs.length}
        docCount={totalDocs}
        loading={loading}
      />
      <TaskBoard />
    </div>
  );
}
