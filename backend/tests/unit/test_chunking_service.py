import pytest

from app.services.chunking_service import ChunkingService


@pytest.fixture
def chunking_service():
    return ChunkingService(chunk_size=256, chunk_overlap=32)


class TestChunkingService:
    def test_chunk_simple_markdown(self, chunking_service):
        md = "# Title\n\nSome content here.\n\n## Section\n\nMore content."
        nodes = chunking_service.chunk_markdown(md, "doc1", "test.md", "kb1")
        assert len(nodes) >= 1
        assert all(n.metadata["doc_id"] == "doc1" for n in nodes)
        assert all(n.metadata["file_name"] == "test.md" for n in nodes)
        assert all(n.metadata["knowledge_base_id"] == "kb1" for n in nodes)

    def test_chunk_index_assigned(self, chunking_service):
        md = "# A\n\nContent A.\n\n## B\n\nContent B.\n\n## C\n\nContent C."
        nodes = chunking_service.chunk_markdown(md, "doc2", "file.md", "kb2")
        indices = [n.metadata["chunk_index"] for n in nodes]
        assert indices == list(range(len(nodes)))

    def test_empty_document(self, chunking_service):
        nodes = chunking_service.chunk_markdown("", "doc3", "empty.md", "kb3")
        assert nodes == []

    def test_whitespace_only(self, chunking_service):
        nodes = chunking_service.chunk_markdown("   \n\n  ", "doc4", "ws.md", "kb4")
        assert nodes == []

    def test_no_headers(self, chunking_service):
        md = "Just plain text without any markdown headers."
        nodes = chunking_service.chunk_markdown(md, "doc5", "plain.md", "kb5")
        assert len(nodes) >= 1
        assert nodes[0].text.strip() != ""

    def test_overflow_split(self):
        """Large chunk should be split further by SentenceSplitter."""
        svc = ChunkingService(chunk_size=64, chunk_overlap=8)
        md = "# Title\n\n" + "This is a sentence. " * 50
        nodes = svc.chunk_markdown(md, "doc6", "big.md", "kb6")
        assert len(nodes) > 1
        for n in nodes:
            # Each chunk text should be reasonably bounded
            assert len(n.text) < 500

    def test_code_block_preserved(self, chunking_service):
        md = "# Code\n\n```python\ndef foo():\n    return 42\n```\n"
        nodes = chunking_service.chunk_markdown(md, "doc7", "code.md", "kb7")
        assert len(nodes) >= 1
        full_text = " ".join(n.text for n in nodes)
        assert "def foo" in full_text

    def test_header_path_metadata(self, chunking_service):
        md = "# Top\n\n## Sub\n\nContent under sub."
        nodes = chunking_service.chunk_markdown(md, "doc8", "h.md", "kb8")
        # At least one node should have header_path set
        paths = [n.metadata.get("header_path", "") for n in nodes]
        assert any(p for p in paths)

    def test_metadata_propagation(self, chunking_service):
        md = "# Doc\n\nSome text."
        nodes = chunking_service.chunk_markdown(md, "my_doc", "report.md", "my_kb")
        for n in nodes:
            assert n.metadata["doc_id"] == "my_doc"
            assert n.metadata["file_name"] == "report.md"
            assert n.metadata["knowledge_base_id"] == "my_kb"
            assert "chunk_index" in n.metadata
