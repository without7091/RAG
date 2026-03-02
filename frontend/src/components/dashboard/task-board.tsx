"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function TaskBoard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">处理状态</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          文档处理进度请在知识库的文档列表中查看。后台 Worker 会自动处理待向量化的文档。
        </p>
      </CardContent>
    </Card>
  );
}
