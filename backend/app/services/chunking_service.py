import logging
import re
from dataclasses import dataclass, field

from llama_index.core.schema import TextNode

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Header regex: lines like "# Title", "## Sub", up to 6 levels ──
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# ── Fenced code block delimiter ──
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

# ── Table row (starts with |) ──
_TABLE_ROW_RE = re.compile(r"^\|")


@dataclass
class SectionNode:
    """A node in the markdown heading tree."""

    header: str  # heading text (empty for root)
    level: int  # 0 = root, 1–6 = h1–h6
    content_lines: list[str] = field(default_factory=list)
    children: list["SectionNode"] = field(default_factory=list)


def _parse_markdown_tree(text: str) -> SectionNode:
    """Parse markdown text into a tree of SectionNodes based on heading hierarchy.

    Handles:
    - Heading levels 1–6
    - Level jumps (e.g. h1 -> h3, missing h2)
    - Fenced code blocks (headings inside are ignored)
    - Content before the first heading (goes to root)
    """
    root = SectionNode(header="", level=0)
    # Stack tracks the path from root to the current insertion point.
    # Each entry is a SectionNode. stack[0] is always root.
    stack: list[SectionNode] = [root]
    current = root
    in_fence = False
    fence_marker = ""

    for line in text.split("\n"):
        # ── Track fenced code blocks ──
        fence_match = _FENCE_RE.match(line.strip())
        if fence_match:
            marker = fence_match.group(1)[0]  # ` or ~
            marker_len = len(fence_match.group(1))
            if not in_fence:
                in_fence = True
                fence_marker = marker * marker_len
            elif line.strip().startswith(marker) and len(line.strip()) >= len(fence_marker):
                # Closing fence must use same char and be at least as long
                if line.strip().rstrip() == marker * len(line.strip().rstrip()):
                    in_fence = False
                    fence_marker = ""
            current.content_lines.append(line)
            continue

        if in_fence:
            current.content_lines.append(line)
            continue

        # ── Check for heading ──
        header_match = _HEADER_RE.match(line)
        if header_match:
            level = len(header_match.group(1))
            header_text = header_match.group(2).strip()

            new_node = SectionNode(header=header_text, level=level)

            # Pop stack until we find a parent with level < new level
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()

            parent = stack[-1]
            parent.children.append(new_node)
            stack.append(new_node)
            current = new_node
        else:
            current.content_lines.append(line)

    return root


def _get_content_text(node: SectionNode) -> str:
    """Join content lines and strip, returning the body text of a node."""
    return "\n".join(node.content_lines).strip()


def _detect_content_type(text: str) -> str:
    """Detect whether text is primarily code, table, or plain text."""
    lines = text.split("\n")
    fence_count = sum(1 for line in lines if _FENCE_RE.match(line.strip()))
    table_count = sum(1 for line in lines if _TABLE_ROW_RE.match(line.strip()))
    total = len(lines)

    if fence_count >= 2:
        return "code"
    if total > 0 and table_count / total > 0.5:
        return "table"
    return "text"


def _build_header_prefix(ancestors: list[str], service: "ChunkingService") -> str:
    """Build the header path prefix string like '[A > B > C]\n\n'."""
    if not ancestors:
        return ""
    settings = get_settings()
    path = settings.header_separator.join(ancestors)
    return settings.header_prefix_template.format(path=path)


def _split_overflow(text: str, max_size: int, overlap: int) -> list[str]:
    """Split oversized text with CJK-aware boundary detection.

    Preserves atomic regions (code blocks, tables) and splits at natural
    boundaries with the following priority:
    \\n\\n → \\n → 。→ ！→ ？→ ；→ ，→ 、→ . → ! → ? → space → char-level
    """
    if len(text) <= max_size:
        return [text]

    # ── Identify atomic regions (code blocks, tables) ──
    # We'll try to keep these intact during splitting
    segments = _segment_atomic(text)

    chunks: list[str] = []
    current_buf: list[str] = []
    current_len = 0

    for seg_text, is_atomic in segments:
        seg_len = len(seg_text)

        # If adding this segment exceeds max and we have content, flush
        if current_len + seg_len > max_size and current_len > 0:
            chunk_text = "\n\n".join(current_buf)
            if is_atomic and seg_len <= max_size:
                # Flush current, then start new with atomic
                chunks.append(chunk_text)
                current_buf = [seg_text]
                current_len = seg_len
                continue
            elif is_atomic and seg_len > max_size:
                # Flush current, then force-split the atomic (rare)
                chunks.append(chunk_text)
                forced = _force_split(seg_text, max_size, overlap)
                chunks.extend(forced[:-1])
                current_buf = [forced[-1]]
                current_len = len(forced[-1])
                continue
            else:
                # Non-atomic: flush current, then split the segment
                chunks.append(chunk_text)
                current_buf = []
                current_len = 0

        if seg_len <= max_size - current_len:
            current_buf.append(seg_text)
            current_len += seg_len + (2 if current_buf else 0)  # account for \n\n join
        else:
            # Need to split this non-atomic segment
            sub_parts = _force_split(seg_text, max_size - current_len if current_len == 0 else max_size, overlap)
            if current_len > 0 and sub_parts:
                # Merge first sub_part with current buffer if it fits
                first = sub_parts[0]
                if current_len + len(first) <= max_size:
                    current_buf.append(first)
                    sub_parts = sub_parts[1:]
                    chunk_text = "\n\n".join(current_buf)
                    chunks.append(chunk_text)
                    current_buf = []
                    current_len = 0
                else:
                    chunks.append("\n\n".join(current_buf))
                    current_buf = []
                    current_len = 0

            for sp in sub_parts[:-1]:
                chunks.append(sp)
            if sub_parts:
                current_buf = [sub_parts[-1]]
                current_len = len(sub_parts[-1])

    if current_buf:
        chunks.append("\n\n".join(current_buf))

    return [c for c in chunks if c.strip()]


def _segment_atomic(text: str) -> list[tuple[str, bool]]:
    """Split text into segments, marking code blocks and tables as atomic.

    Returns list of (text, is_atomic) tuples.
    """
    segments: list[tuple[str, bool]] = []
    lines = text.split("\n")
    buf: list[str] = []
    in_fence = False
    in_table = False

    for line in lines:
        stripped = line.strip()
        fence_m = _FENCE_RE.match(stripped)

        if fence_m and not in_fence:
            # Flush non-atomic buffer
            if buf:
                segments.append(("\n".join(buf), False))
                buf = []
            in_fence = True
            buf = [line]
            continue

        if in_fence:
            buf.append(line)
            if fence_m:
                # Closing fence
                in_fence = False
                segments.append(("\n".join(buf), True))
                buf = []
            continue

        # Table detection
        is_table_row = bool(_TABLE_ROW_RE.match(stripped))
        if is_table_row and not in_table:
            # Flush non-atomic buffer
            if buf:
                segments.append(("\n".join(buf), False))
                buf = []
            in_table = True
            buf = [line]
        elif in_table and is_table_row:
            buf.append(line)
        elif in_table and not is_table_row:
            # End of table
            segments.append(("\n".join(buf), True))
            buf = [line]
            in_table = False
        else:
            buf.append(line)

    if buf:
        segments.append(("\n".join(buf), in_fence or in_table))

    return segments


def _find_split_pos(text: str, max_size: int) -> int:
    """Find the best split position within text[:max_size] using separator priority.

    Priority: \\n\\n → \\n → 。→ ！→ ？→ ；→ ，→ 、→ . → ! → ? → space → char-level
    Returns the position AFTER the separator (i.e., start of next chunk).
    """
    separators = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", ". ", "! ", "? ", " "]
    window = text[:max_size]
    for sep in separators:
        pos = window.rfind(sep)
        if pos > max_size // 4:  # Don't split too early
            return pos + len(sep)
    # Fallback: character-level split
    return max_size


def _force_split(text: str, max_size: int, overlap: int) -> list[str]:
    """Force-split text at natural CJK-aware boundaries with overlap.

    Overlap is implemented at split time: after cutting at position P,
    the next chunk starts from (P - overlap), snapped backward to a clean
    sentence boundary so the overlap region begins at a readable point.
    """
    if len(text) <= max_size:
        return [text]

    chunks: list[str] = []
    pos = 0
    text_len = len(text)

    while pos < text_len:
        end = pos + max_size
        if end >= text_len:
            # Last chunk — take everything remaining
            tail = text[pos:].strip()
            if tail:
                chunks.append(tail)
            break

        # Find best split point within [pos, pos + max_size]
        split_pos = pos + _find_split_pos(text[pos:], max_size)
        chunk = text[pos:split_pos].rstrip()
        if chunk:
            chunks.append(chunk)

        # Next chunk starts (overlap) chars before the split point,
        # snapped forward to the first clean boundary after the rewind
        # point, so the overlap region begins at a readable sentence start.
        if overlap > 0 and split_pos < text_len:
            rewind_start = max(pos, split_pos - overlap)
            # Search forward from rewind_start for the first sentence boundary
            rewind_zone = text[rewind_start:split_pos]
            snap_pos = -1
            for sep in ["\n", "。", "！", "？", "；", ". ", "! ", "? "]:
                p = rewind_zone.find(sep)
                if p >= 0:
                    snap_pos = p + len(sep)
                    break
            if snap_pos >= 0 and rewind_start + snap_pos < split_pos:
                pos = rewind_start + snap_pos
            else:
                # No clean boundary found — use raw rewind
                pos = rewind_start
        else:
            pos = split_pos

    return chunks


def _collect_chunks(
    node: SectionNode,
    ancestors: list[str],
    service: "ChunkingService",
) -> list[dict]:
    """Recursively collect chunks from the section tree.

    Only nodes with actual content produce chunks.
    Empty parent headings pass their header text down via ancestors.
    """
    results: list[dict] = []
    settings = get_settings()

    # Build ancestor list for children
    current_ancestors = ancestors[:]
    if node.header:
        current_ancestors.append(node.header)

    content = _get_content_text(node)

    if content:
        content_type = _detect_content_type(content)
        prefix = _build_header_prefix(current_ancestors, service)

        # Check if content exceeds chunk size (accounting for prefix)
        full_text = prefix + content
        if len(full_text) > service.chunk_size:
            # Overflow split on content, then re-attach prefix
            max_content = max(service.chunk_size - len(prefix), settings.min_chunk_size)
            sub_texts = _split_overflow(content, max_content, service.chunk_overlap)
            for sub in sub_texts:
                sub_full = prefix + sub if prefix else sub
                results.append({
                    "text": sub_full,
                    "header_path": settings.header_separator.join(current_ancestors) if current_ancestors else "",
                    "header_level": node.level,
                    "content_type": _detect_content_type(sub),
                })
        else:
            # Skip short content when node has children — header info
            # already flows down to children via the ancestor prefix.
            if len(content) >= settings.min_chunk_size or not node.children:
                results.append({
                    "text": full_text,
                    "header_path": settings.header_separator.join(current_ancestors) if current_ancestors else "",
                    "header_level": node.level,
                    "content_type": content_type,
                })

    # Recurse into children
    for child in node.children:
        results.extend(_collect_chunks(child, current_ancestors, service))

    return results


class ChunkingService:
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        settings = get_settings()
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def chunk_markdown(
        self,
        markdown_text: str,
        doc_id: str,
        file_name: str,
        knowledge_base_id: str,
    ) -> list[TextNode]:
        """Chunk markdown text using tree-based header parsing with CJK-aware overflow protection."""
        if not markdown_text.strip():
            return []

        # Phase 1: Parse markdown into heading tree
        root = _parse_markdown_tree(markdown_text)

        # Phase 2: Collect chunks from tree (only non-empty leaves)
        raw_chunks = _collect_chunks(root, [], self)

        if not raw_chunks:
            return []

        # Phase 3: Build TextNode list with metadata
        nodes: list[TextNode] = []
        for i, chunk in enumerate(raw_chunks):
            node = TextNode(
                text=chunk["text"],
                metadata={
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "knowledge_base_id": knowledge_base_id,
                    "chunk_index": i,
                    "header_path": chunk["header_path"],
                    "header_level": chunk["header_level"],
                    "content_type": chunk["content_type"],
                },
            )
            nodes.append(node)

        logger.info(
            f"Chunked doc_id={doc_id} into {len(nodes)} chunks "
            f"(chunk_size={self.chunk_size})"
        )
        return nodes
