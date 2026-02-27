import os
import requests
from typing import List, Optional

from llama_index.core import VectorStoreIndex, Document, StorageContext, Settings
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from pydantic import Field

from qdrant_client import QdrantClient
from llama_index.vector_stores.qdrant import QdrantVectorStore


# 注意：换成你实际解压的路径
os.environ["FASTEMBED_CACHE_PATH"] = "/usr1/ai-service-test-linux-env/fastembed_cache" 

# ==========================================
# 0. 公司内部配置信息
# ==========================================

print("▶️ [步骤 1] 正在配置 Embedding API...")
Settings.embed_model = OpenAIEmbedding(
    api_key=API_KEY, api_base=EMBED_BASE_URL
)
Settings.llm = None 

# ==========================================
# 1. 初始化 Qdrant 向量数据库 (开启原生 Hybrid)
# ==========================================
print("▶️ [步骤 2] 正在连接本地 Qdrant 数据库...")
client = QdrantClient(path="./qdrant_local_storage")
vector_store = QdrantVectorStore(
    client=client, 
    collection_name="production_rag_docs", 
    enable_hybrid=True # 🌟 核心魔法 2：霸气开启 Qdrant 原生混合检索！
)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# ==========================================
# 2. 准备数据并存入 Qdrant
# ==========================================
print("▶️ [步骤 3] 正在构建知识库...")
documents = [
    Document(text="规章制度：员工报销必须使用专用的财务系统进行申报。"),
    Document(text="产品手册：我们的最新型号路由器 XJ-998 支持 Wi-Fi 7 技术。"),
    Document(text="历史对话：我昨天买了一个苹果，很甜。"),
    Document(text="用户说：路由器的灯一直闪红灯怎么回事？"),
    Document(text="干扰项：市场上有很多叫做 XJ 的杂牌路由器。")
]
index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)

# ==========================================
# 3. 定义自定义 Reranker
# ==========================================
class HuaweiReranker(BaseNodePostprocessor):
    api_url: str = Field(description="Reranker API URL")
    api_key: str = Field(description="API Key")
    top_n: int = Field(default=2, description="精排后保留前 N 个结果")

    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_bundle: Optional[QueryBundle] = None) -> List[NodeWithScore]:
        if not query_bundle or not nodes: return nodes
        query = query_bundle.query_str
        texts = [node.node.get_content() for node in nodes]
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": "qwen3-reranker", "query": query, "texts": texts}
        
        print("\n▶️ [步骤 5] 正在调用公司 Rerank 接口进行精排比对...")
        response = requests.post(self.api_url, json=payload, headers=headers)
        if response.status_code != 200: return nodes
        
        try:
            results = response.json()
            scores_list = results if isinstance(results, list) else results.get("results", [])
            for item in scores_list:
                idx = item.get("index")
                score = item.get("score", item.get("relevance_score", 0.0))
                nodes[idx].score = score
            nodes.sort(key=lambda x: x.score, reverse=True)
            return nodes[:self.top_n]
        except Exception:
            return nodes

reranker = HuaweiReranker(api_url=RERANK_URL, api_key=API_KEY, top_n=2)

# ==========================================
# 4. 执行测试：Query -> 混合检索 -> 重排
# ==========================================
query_text = "XJ-998 路由器用的什么技术？"
print(f"\n【用户提问】: {query_text}")

print("▶️ [步骤 4] 正在执行 Qdrant 原生混合检索 (Dense + Sparse)...")
# 代码变得极其清爽，Qdrant 自己把所有活全干了！
retriever = index.as_retriever(similarity_top_k=4)
retrieved_nodes = retriever.retrieve(query_text)

print("\n--- 🔍 第一阶段：混合检索结果 (Top 4) ---")
for i, node in enumerate(retrieved_nodes):
    print(f"[{i+1}] 混合得分: {node.score:.4f} | 内容: {node.text}")

reranked_nodes = reranker.postprocess_nodes(nodes=retrieved_nodes, query_bundle=QueryBundle(query_text))

print("\n--- 🎯 第二阶段：Reranker 精排最终结果 (Top 2) ---")
for i, node in enumerate(reranked_nodes):
    print(f"[{i+1}] 精排得分: {node.score:.4f} | 内容: {node.text}")

print("\n🚀 满血版 RAG 检索底层打通！完美收工！")

# 解决退出时的报红小 bug
client.close()