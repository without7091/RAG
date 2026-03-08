import logging
from collections import defaultdict

from app.config import get_settings
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)


def _merge_overlapping_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []

    merged_ranges: list[list[int]] = []
    for start, end in sorted(ranges):
        if not merged_ranges or start > merged_ranges[-1][1]:
            merged_ranges.append([start, end])
            continue
        merged_ranges[-1][1] = max(merged_ranges[-1][1], end)

    return [(start, end) for start, end in merged_ranges]


def _build_range_context_text(chunks: list[dict], start: int, end: int) -> str:
    parts = [
        chunk.get("text", "")
        for chunk in chunks
        if start <= chunk.get("chunk_index", -1) <= end and chunk.get("text")
    ]
    return "\n\n".join(parts)


async def synthesize_context(
    source_nodes: list[dict],
    knowledge_base_id: str,
    vector_store: VectorStoreService,
    enable_context_synthesis: bool = True,
) -> list[dict]:
    """Enrich source nodes with merged adjacent chunk context."""
    if not source_nodes:
        return source_nodes

    for node in source_nodes:
        node["context_text"] = node["text"]

    if not enable_context_synthesis:
        return source_nodes

    window_size = max(get_settings().context_synthesis_window_size, 0)
    nodes_by_doc: dict[str, list[dict]] = defaultdict(list)
    for node in source_nodes:
        doc_id = node.get("doc_id")
        if doc_id:
            nodes_by_doc[doc_id].append(node)

    for doc_id, nodes in nodes_by_doc.items():
        try:
            chunks = await vector_store.get_chunks_by_doc_id(knowledge_base_id, doc_id)
        except Exception:
            logger.warning(
                "Context synthesis: failed to fetch chunks for doc %s in kb %s, "
                "falling back to original text",
                doc_id, knowledge_base_id,
                exc_info=True,
            )
            continue

        if not chunks:
            continue

        available_indices = {chunk.get("chunk_index") for chunk in chunks}
        node_ranges = [
            (node, (node["chunk_index"] - window_size, node["chunk_index"] + window_size))
            for node in nodes
            if node.get("chunk_index") is not None and node["chunk_index"] in available_indices
        ]
        if not node_ranges:
            continue

        merged_ranges = _merge_overlapping_ranges([chunk_range for _node, chunk_range in node_ranges])
        range_texts = {
            chunk_range: _build_range_context_text(chunks, chunk_range[0], chunk_range[1])
            for chunk_range in merged_ranges
        }

        for node, _chunk_range in node_ranges:
            chunk_index = node["chunk_index"]
            merged_range = next(
                (
                    candidate_range
                    for candidate_range in merged_ranges
                    if candidate_range[0] <= chunk_index <= candidate_range[1]
                ),
                None,
            )
            if merged_range is None:
                continue

            context_text = range_texts.get(merged_range)
            if context_text:
                node["context_text"] = context_text

    return source_nodes
