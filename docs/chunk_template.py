#!/usr/bin/env python3
"""
预切分 JSON 生成模板
====================
用途: 读取你自己的文件，按自定义策略切分，输出符合平台格式的 JSON 文件。

使用方法:
    python chunk_template.py

输出格式（JSON 数组，每个切片是一个对象）:
    {
        "text":         (str,  必填) 切片文本内容，不可为空
        "header_path":  (str,  可选) 标题路径，如 "第一章 > 1.1 概述"，默认 ""
        "header_level": (int,  可选) 标题层级 0-6，对应 h1-h6，默认 0
        "content_type": (str,  可选) "text" | "code" | "table"，默认 "text"
        "metadata":     (dict, 可选) 自定义扩展字段，平台原样保存，默认 {}
    }
"""

import json

# ─────────────────────────────────────────────────────────────────────────────
# 第一步：读取你的文件
# 在这里替换成你自己的文件读取逻辑
# ─────────────────────────────────────────────────────────────────────────────

INPUT_FILE = "your_file.txt"   # 替换为你的文件路径
OUTPUT_FILE = "chunks.json"    # 输出 JSON 文件路径

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    text = f.read()


# ─────────────────────────────────────────────────────────────────────────────
# 第二步：实现你的切分逻辑
# 在这里写任意切分策略，返回 list[dict]
# ─────────────────────────────────────────────────────────────────────────────

def my_chunking(text: str) -> list[dict]:
    """
    在这里实现你的切分策略。

    唯一要求：返回 list[dict]，每个 dict 必须包含非空的 "text" 字段。
    其余字段可选，不填时平台使用默认值。
    """
    chunks = []

    # ── 示例：按段落切分（替换为你自己的逻辑）──
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    for i, para in enumerate(paragraphs):
        chunks.append({
            "text": para,
            "header_path": "",      # 如果你能识别文档结构，填入如 "第一章 > 第一节"
            "header_level": 0,      # 对应该切片所属标题的层级（1-6），无标题填 0
            "content_type": "text", # "text" | "code" | "table"
            "metadata": {
                # 可以添加任意自定义字段，平台原样保存，不影响检索
                # "page": 1,
                # "source": "internal",
            },
        })

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 第三步：生成并保存 JSON
# ─────────────────────────────────────────────────────────────────────────────

chunks = my_chunking(text)

if not chunks:
    raise ValueError("切片结果为空，请检查输入文件和切分逻辑")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(chunks, f, ensure_ascii=False, indent=2)

print(f"完成：{len(chunks)} 个切片 → {OUTPUT_FILE}")
