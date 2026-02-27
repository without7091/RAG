from pathlib import Path

import pytest

from app.exceptions import ParsingError, UnsupportedFileTypeError
from app.services.parsing_service import ParsingService

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def parsing_service():
    return ParsingService()


class TestParsingService:
    async def test_parse_md_passthrough(self, parsing_service, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nWorld", encoding="utf-8")
        result = await parsing_service.parse_file(md_file)
        assert "# Hello" in result
        assert "World" in result

    async def test_parse_txt_passthrough(self, parsing_service, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Plain text content", encoding="utf-8")
        result = await parsing_service.parse_file(txt_file)
        assert "Plain text content" in result

    async def test_unsupported_format_raises(self, parsing_service, tmp_path):
        bad_file = tmp_path / "test.xyz"
        bad_file.write_text("content", encoding="utf-8")
        with pytest.raises(UnsupportedFileTypeError):
            await parsing_service.parse_file(bad_file)

    async def test_file_not_found_raises(self, parsing_service):
        with pytest.raises(ParsingError, match="File not found"):
            await parsing_service.parse_file("/nonexistent/file.md")

    async def test_empty_file(self, parsing_service, tmp_path):
        empty = tmp_path / "empty.md"
        empty.write_text("", encoding="utf-8")
        result = await parsing_service.parse_file(empty)
        assert result == ""

    async def test_sample_fixture(self, parsing_service):
        sample = FIXTURES_DIR / "sample.md"
        if sample.exists():
            result = await parsing_service.parse_file(sample)
            assert "Sample Document" in result
            assert "Section One" in result
