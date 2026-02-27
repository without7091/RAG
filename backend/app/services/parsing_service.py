import logging
from pathlib import Path

from app.exceptions import ParsingError, UnsupportedFileTypeError

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".xlsx", ".md", ".txt"}


class ParsingService:
    """Convert uploaded documents to Markdown format."""

    def __init__(self):
        self._markitdown = None

    def _get_markitdown(self):
        if self._markitdown is None:
            from markitdown import MarkItDown

            self._markitdown = MarkItDown()
        return self._markitdown

    async def parse_file(self, file_path: str | Path) -> str:
        """Parse a file to Markdown string.

        .md files are returned as-is (passthrough).
        .txt files are returned as-is.
        Other supported formats (.pdf, .docx, .pptx, .xlsx) use MarkItDown.
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFileTypeError(path.name)

        if not path.exists():
            raise ParsingError(path.name, reason="File not found")

        # Passthrough for .md and .txt — read as UTF-8 text directly
        if ext in {".md", ".txt"}:
            content = path.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                return ""
            return content

        # Binary formats — delegate to MarkItDown (reads file itself)
        try:
            mid = self._get_markitdown()
            result = mid.convert(str(path))
            return result.text_content or ""
        except Exception as e:
            raise ParsingError(path.name, reason=str(e)) from e
