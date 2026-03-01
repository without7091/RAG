import pytest

from app.services.chunking_service import (
    ChunkingService,
    SectionNode,
    _parse_markdown_tree,
    _collect_chunks,
    _split_overflow,
    _force_split,
    _detect_content_type,
    _get_content_text,
)


@pytest.fixture
def chunking_service():
    return ChunkingService(chunk_size=512, chunk_overlap=64)


@pytest.fixture
def small_chunking_service():
    """Service with small chunk size for overflow testing."""
    return ChunkingService(chunk_size=100, chunk_overlap=10)


# ════════════════════════════════════════════════════
# Tree Parsing Tests
# ════════════════════════════════════════════════════


class TestParseMarkdownTree:
    def test_simple_headers(self):
        md = "# H1\n\nContent 1.\n\n## H2\n\nContent 2."
        root = _parse_markdown_tree(md)
        assert root.level == 0
        assert len(root.children) == 1
        h1 = root.children[0]
        assert h1.header == "H1"
        assert h1.level == 1
        assert "Content 1." in _get_content_text(h1)
        assert len(h1.children) == 1
        h2 = h1.children[0]
        assert h2.header == "H2"
        assert h2.level == 2
        assert "Content 2." in _get_content_text(h2)

    def test_level_jump(self):
        """h1 -> h3 (skipping h2) should still nest correctly."""
        md = "# Top\n\n### Jumped\n\nContent."
        root = _parse_markdown_tree(md)
        h1 = root.children[0]
        assert h1.header == "Top"
        assert len(h1.children) == 1
        h3 = h1.children[0]
        assert h3.header == "Jumped"
        assert h3.level == 3

    def test_code_block_headers_ignored(self):
        """Headers inside fenced code blocks should not be parsed as headings."""
        md = "# Real\n\n```\n# Not a header\n## Also not\n```\n\nAfter code."
        root = _parse_markdown_tree(md)
        assert len(root.children) == 1
        h1 = root.children[0]
        assert h1.header == "Real"
        content = _get_content_text(h1)
        assert "# Not a header" in content
        assert "After code." in content
        assert len(h1.children) == 0

    def test_content_before_first_header(self):
        """Content before any heading goes into the root node."""
        md = "Preamble text.\n\n# First\n\nBody."
        root = _parse_markdown_tree(md)
        root_content = _get_content_text(root)
        assert "Preamble text." in root_content
        assert len(root.children) == 1
        assert root.children[0].header == "First"

    def test_multiple_h1(self):
        """Multiple h1 sections should be siblings under root."""
        md = "# A\n\nContent A.\n\n# B\n\nContent B.\n\n# C\n\nContent C."
        root = _parse_markdown_tree(md)
        assert len(root.children) == 3
        assert [c.header for c in root.children] == ["A", "B", "C"]

    def test_tilde_fence(self):
        """Tilde-fenced code blocks should also be handled."""
        md = "# Title\n\n~~~\n# fake header\n~~~\n\nReal content."
        root = _parse_markdown_tree(md)
        assert len(root.children) == 1
        content = _get_content_text(root.children[0])
        assert "# fake header" in content


# ════════════════════════════════════════════════════
# Core Bug Fix: Consecutive Empty Headers
# ════════════════════════════════════════════════════


class TestConsecutiveEmptyHeaders:
    def test_no_empty_chunks_from_nested_headers(self, chunking_service):
        """The core bug: nested headers with no body between them should NOT
        produce empty chunks. Each chunk must have real content."""
        md = (
            "# Chapter 3\n\n"
            "## 3.1 Overview\n\n"
            "### 3.1.1 Details\n\n"
            "Actual content lives here.\n\n"
            "### 3.1.2 More Details\n\n"
            "More actual content."
        )
        nodes = chunking_service.chunk_markdown(md, "doc1", "test.md", "kb1")
        # Every chunk must have non-whitespace content beyond just the header prefix
        for node in nodes:
            text = node.text.strip()
            assert len(text) > 0, "Found empty chunk"
            # Strip header prefix and check there's still content
            if text.startswith("["):
                after_prefix = text.split("]\n\n", 1)
                if len(after_prefix) > 1:
                    assert after_prefix[1].strip(), f"Chunk has only header prefix: {text}"

    def test_deeply_nested_empty_headers(self, chunking_service):
        """Even deeply nested empty headers should not produce chunks."""
        md = (
            "# L1\n\n"
            "## L2\n\n"
            "### L3\n\n"
            "#### L4\n\n"
            "##### L5\n\n"
            "###### L6\n\n"
            "Finally some content."
        )
        nodes = chunking_service.chunk_markdown(md, "doc", "deep.md", "kb")
        assert len(nodes) == 1
        assert "Finally some content." in nodes[0].text

    def test_mixed_empty_and_content_headers(self, chunking_service):
        """Only headers with sufficient content produce chunks.
        Short content under a parent with children is skipped (< min_chunk_size)
        because the header info already flows to children via prefix."""
        md = (
            "# Root\n\n"
            "Root content.\n\n"
            "## Empty Section\n\n"
            "### Sub With Content\n\n"
            "Sub content here.\n\n"
            "## Another Section\n\n"
            "Another content."
        )
        nodes = chunking_service.chunk_markdown(md, "doc", "mixed.md", "kb")
        texts = [n.text for n in nodes]
        # "Root content." (13 chars) is below min_chunk_size and Root has children → skipped
        assert len(nodes) == 2
        assert any("Sub content here." in t for t in texts)
        assert any("Another content." in t for t in texts)


# ════════════════════════════════════════════════════
# Header Prefix Injection
# ════════════════════════════════════════════════════


class TestHeaderPrefixInjection:
    def test_header_path_in_text(self, chunking_service):
        """Chunk text should start with [ancestor > path] prefix."""
        md = "# Top\n\n## Sub\n\nContent under sub."
        nodes = chunking_service.chunk_markdown(md, "doc", "h.md", "kb")
        # Find the chunk with "Content under sub."
        sub_node = [n for n in nodes if "Content under sub." in n.text][0]
        assert sub_node.text.startswith("[Top > Sub]\n\n")

    def test_root_content_no_prefix(self, chunking_service):
        """Content before any header should have no header prefix.
        Content must be >= min_chunk_size (50) when root has children."""
        md = (
            "This is root-level preamble content that appears before any heading in the document.\n\n"
            "# Later\n\nLater content."
        )
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        root_node = [n for n in nodes if "preamble content" in n.text][0]
        assert not root_node.text.startswith("[")

    def test_single_h1_prefix(self, chunking_service):
        """Content directly under h1 gets [H1] prefix."""
        md = "# Title\n\nDirect content."
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        assert nodes[0].text.startswith("[Title]\n\n")


# ════════════════════════════════════════════════════
# Chunk Index Continuity
# ════════════════════════════════════════════════════


class TestChunkIndexContinuity:
    def test_sequential_chunk_indices(self, chunking_service):
        md = "# A\n\nContent A.\n\n## B\n\nContent B.\n\n## C\n\nContent C."
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        indices = [n.metadata["chunk_index"] for n in nodes]
        assert indices == list(range(len(nodes)))

    def test_chunk_indices_with_overflow(self, small_chunking_service):
        md = "# Title\n\n" + "This is a sentence for testing. " * 20
        nodes = small_chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        indices = [n.metadata["chunk_index"] for n in nodes]
        assert indices == list(range(len(nodes)))
        assert len(nodes) > 1


# ════════════════════════════════════════════════════
# Metadata Propagation
# ════════════════════════════════════════════════════


class TestMetadataPropagation:
    def test_core_metadata(self, chunking_service):
        md = "# Doc\n\nSome text."
        nodes = chunking_service.chunk_markdown(md, "my_doc", "report.md", "my_kb")
        for n in nodes:
            assert n.metadata["doc_id"] == "my_doc"
            assert n.metadata["file_name"] == "report.md"
            assert n.metadata["knowledge_base_id"] == "my_kb"
            assert "chunk_index" in n.metadata

    def test_header_path_metadata(self, chunking_service):
        md = "# A\n\n## B\n\n### C\n\nDeep content."
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        deep_node = [n for n in nodes if "Deep content." in n.text][0]
        assert deep_node.metadata["header_path"] == "A > B > C"

    def test_header_level_metadata(self, chunking_service):
        """Leaf nodes at different levels should carry correct header_level."""
        md = "# H1\n\n## H2a\n\nH2a has enough content to pass the minimum chunk size threshold easily.\n\n## H2b\n\nH2b also has enough content to pass the minimum chunk size threshold easily."
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        h2a_node = [n for n in nodes if "H2a has enough" in n.text][0]
        h2b_node = [n for n in nodes if "H2b also has" in n.text][0]
        assert h2a_node.metadata["header_level"] == 2
        assert h2b_node.metadata["header_level"] == 2

    def test_content_type_metadata(self, chunking_service):
        md = "# Code Section\n\n```python\nprint('hello')\n```\n\n# Text Section\n\nJust text."
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        code_node = [n for n in nodes if "print" in n.text][0]
        text_node = [n for n in nodes if "Just text." in n.text][0]
        assert code_node.metadata["content_type"] == "code"
        assert text_node.metadata["content_type"] == "text"


# ════════════════════════════════════════════════════
# Content Type Detection
# ════════════════════════════════════════════════════


class TestContentTypeDetection:
    def test_code_detection(self):
        text = "```python\ndef foo():\n    pass\n```"
        assert _detect_content_type(text) == "code"

    def test_table_detection(self):
        text = "| Col1 | Col2 |\n| --- | --- |\n| A | B |\n| C | D |"
        assert _detect_content_type(text) == "table"

    def test_text_detection(self):
        text = "This is just plain text with no special formatting."
        assert _detect_content_type(text) == "text"


# ════════════════════════════════════════════════════
# Atomic Region Protection
# ════════════════════════════════════════════════════


class TestAtomicProtection:
    def test_code_block_not_split(self):
        """A code block smaller than max_size should not be split."""
        code = "```python\ndef foo():\n    return 42\n```"
        result = _split_overflow(code, 200, 10)
        assert len(result) == 1
        assert "def foo" in result[0]
        assert "return 42" in result[0]

    def test_table_not_split(self):
        """A table smaller than max_size should stay intact."""
        table = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        result = _split_overflow(table, 200, 10)
        assert len(result) == 1
        assert "| A | B |" in result[0]


# ════════════════════════════════════════════════════
# CJK Sentence Splitting
# ════════════════════════════════════════════════════


class TestCJKSplitting:
    def test_chinese_sentence_boundaries(self):
        """Should split at Chinese punctuation marks."""
        # Create a long Chinese text that exceeds max_size
        text = "这是第一个句子。这是第二个句子。这是第三个句子。" * 10
        result = _split_overflow(text, 60, 0)
        assert len(result) > 1
        # Each chunk should end at or near a sentence boundary
        for chunk in result:
            assert len(chunk) <= 80  # some tolerance

    def test_mixed_cjk_and_english(self):
        """Mixed text should split at available boundaries."""
        text = "Hello世界。This is a test。混合文本here。" * 10
        result = _split_overflow(text, 60, 0)
        assert len(result) > 1


# ════════════════════════════════════════════════════
# Overlap Verification
# ════════════════════════════════════════════════════


class TestOverlapActuallyWorks:
    def test_force_split_overlap_shares_content(self):
        """Adjacent chunks produced by _force_split must share overlapping text."""
        sentences = [f"这是第{i}个测试句子。" for i in range(1, 21)]
        text = "".join(sentences)
        chunks = _force_split(text, 80, 30)
        assert len(chunks) >= 3
        # Each consecutive pair must share some text
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            # Find shared substring: the end of prev should appear at the start of curr
            shared = False
            # Check that some suffix of prev appears as prefix of curr
            for length in range(5, min(len(prev), len(curr)) + 1):
                if prev.endswith(curr[:length]):
                    shared = True
                    break
                if curr.startswith(prev[-length:]):
                    shared = True
                    break
            assert shared, (
                f"Chunks {i-1} and {i} share no overlapping text.\n"
                f"  prev tail: ...{prev[-40:]}\n"
                f"  curr head: {curr[:40]}..."
            )

    def test_force_split_no_overlap_when_zero(self):
        """With overlap=0, chunks should not share content."""
        text = "第一句话。第二句话。第三句话。第四句话。" * 5
        chunks = _force_split(text, 30, 0)
        assert len(chunks) >= 2
        # Reconstruct — no duplicated content
        joined = "".join(chunks)
        # Total length should equal original (minus whitespace trimming)
        assert len(joined) <= len(text)

    def test_split_overflow_overlap_on_plain_text(self):
        """_split_overflow on plain text (no code/table) must produce overlap."""
        text = "".join(f"句子编号{i}的内容在这里。" for i in range(1, 30))
        chunks = _split_overflow(text, 80, 30)
        assert len(chunks) >= 3
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            shared = False
            for length in range(3, min(len(prev), len(curr)) + 1):
                if curr.startswith(prev[-length:]):
                    shared = True
                    break
            assert shared, f"No overlap between chunk {i-1} and {i}"

    def test_overlap_with_english_sentences(self):
        """Overlap should work with English period-delimited sentences."""
        text = ". ".join(f"This is test sentence number {i}" for i in range(1, 30)) + "."
        chunks = _force_split(text, 100, 40)
        assert len(chunks) >= 3
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            shared = False
            for length in range(3, min(len(prev), len(curr)) + 1):
                if curr.startswith(prev[-length:]):
                    shared = True
                    break
            assert shared, f"No overlap between chunk {i-1} and {i}"


# ════════════════════════════════════════════════════
# Overflow Split + Header Inheritance
# ════════════════════════════════════════════════════


class TestOverflowWithHeaders:
    def test_overflow_chunks_inherit_prefix(self, small_chunking_service):
        """When a section overflows, all sub-chunks should get the header prefix."""
        md = "# Title\n\n## Section\n\n" + "This is sentence number one. " * 20
        nodes = small_chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        assert len(nodes) > 1
        for node in nodes:
            if "sentence" in node.text:
                assert node.text.startswith("[Title > Section]")

    def test_overflow_preserves_header_path_metadata(self, small_chunking_service):
        """All overflow sub-chunks should have the same header_path."""
        md = "# A\n\n## B\n\n" + "Word " * 100
        nodes = small_chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        for node in nodes:
            if "Word" in node.text:
                assert node.metadata["header_path"] == "A > B"


# ════════════════════════════════════════════════════
# Edge Cases
# ════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_document(self, chunking_service):
        nodes = chunking_service.chunk_markdown("", "doc", "empty.md", "kb")
        assert nodes == []

    def test_whitespace_only(self, chunking_service):
        nodes = chunking_service.chunk_markdown("   \n\n  ", "doc", "ws.md", "kb")
        assert nodes == []

    def test_no_headers(self, chunking_service):
        """Plain text without headers should still produce a chunk."""
        md = "Just plain text without any markdown headers."
        nodes = chunking_service.chunk_markdown(md, "doc", "plain.md", "kb")
        assert len(nodes) == 1
        assert "Just plain text" in nodes[0].text

    def test_root_content_with_no_children(self, chunking_service):
        md = "This is root-level content with no headings at all."
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        assert len(nodes) == 1
        assert nodes[0].metadata["header_path"] == ""
        assert nodes[0].metadata["header_level"] == 0

    def test_header_only_document(self, chunking_service):
        """A document with only headers and no body should produce no chunks."""
        md = "# A\n\n## B\n\n### C"
        nodes = chunking_service.chunk_markdown(md, "doc", "f.md", "kb")
        assert nodes == []

    def test_code_block_preserved(self, chunking_service):
        md = "# Code\n\n```python\ndef foo():\n    return 42\n```\n"
        nodes = chunking_service.chunk_markdown(md, "doc", "code.md", "kb")
        assert len(nodes) >= 1
        full_text = " ".join(n.text for n in nodes)
        assert "def foo" in full_text
        assert "return 42" in full_text
