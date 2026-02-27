import logging

from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import Document, TextNode

from app.config import get_settings

logger = logging.getLogger(__name__)


class ChunkingService:
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        settings = get_settings()
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.md_parser = MarkdownNodeParser()
        self.sentence_splitter = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def chunk_markdown(
        self,
        markdown_text: str,
        doc_id: str,
        file_name: str,
        knowledge_base_id: str,
    ) -> list[TextNode]:
        """Chunk markdown text using header-aware splitting with overflow protection."""
        if not markdown_text.strip():
            return []

        # Create a LlamaIndex Document
        doc = Document(
            text=markdown_text,
            metadata={
                "doc_id": doc_id,
                "file_name": file_name,
                "knowledge_base_id": knowledge_base_id,
            },
        )

        # Phase 1: Structural split by markdown headers
        header_nodes = self.md_parser.get_nodes_from_documents([doc])

        # Phase 2: Overflow split — if any chunk is too large, split further
        final_nodes: list[TextNode] = []
        for node in header_nodes:
            if len(node.text) > self.chunk_size:
                sub_nodes = self.sentence_splitter.get_nodes_from_documents(
                    [Document(text=node.text, metadata=node.metadata)]
                )
                final_nodes.extend(sub_nodes)
            else:
                final_nodes.append(node)

        # Assign chunk_index and propagate header_path
        for i, node in enumerate(final_nodes):
            node.metadata["chunk_index"] = i
            node.metadata["doc_id"] = doc_id
            node.metadata["file_name"] = file_name
            node.metadata["knowledge_base_id"] = knowledge_base_id
            # Extract header path from metadata if available
            header_path = self._extract_header_path(node)
            if header_path:
                node.metadata["header_path"] = header_path

        logger.info(
            f"Chunked doc_id={doc_id} into {len(final_nodes)} chunks "
            f"(chunk_size={self.chunk_size})"
        )
        return final_nodes

    def _extract_header_path(self, node: TextNode) -> str:
        """Build a header path string from node metadata."""
        # MarkdownNodeParser stores headers in metadata like Header_1, Header_2, etc.
        parts = []
        for level in range(1, 7):
            key = f"Header_{level}"
            alt_key = f"header_{level}"
            header = node.metadata.get(key) or node.metadata.get(alt_key)
            if header:
                parts.append(header)
        return " > ".join(parts) if parts else ""
