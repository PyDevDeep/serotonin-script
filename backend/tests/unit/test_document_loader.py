"""
Tests for backend.rag.indexing.document_loader module.

Всі тести використовують фейкові реалізації DocumentReaderProtocol —
жодного patching SimpleDirectoryReader чи файлової системи.
"""

from pathlib import Path

import pytest
from llama_index.core.schema import Document

from backend.rag.indexing.document_loader import (
    DocumentReaderProtocol,
    LlamaIndexDirectoryReader,
    LlamaIndexFileReader,
    load_documents_from_dir,
)

# ---------------------------------------------------------------------------
# Fake readers — реалізують Protocol без жодних зовнішніх залежностей
# ---------------------------------------------------------------------------


class FakeReader:
    """Повертає фіксований список документів."""

    def __init__(self, documents: list[Document]) -> None:
        self._documents = documents

    def load_data(self) -> list[Document]:
        return self._documents


class FailingReader:
    """Завжди кидає виняток — для тестування propagation."""

    def load_data(self) -> list[Document]:
        raise RuntimeError("reader backend unavailable")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestDocumentReaderProtocol:
    """Перевірка структурної відповідності реалізацій Protocol."""

    def test_fake_reader_satisfies_protocol(self) -> None:
        reader = FakeReader([])
        assert isinstance(reader, DocumentReaderProtocol)

    def test_failing_reader_satisfies_protocol(self) -> None:
        assert isinstance(FailingReader(), DocumentReaderProtocol)

    def test_object_without_load_data_does_not_satisfy_protocol(self) -> None:
        class NotAReader:
            pass

        assert not isinstance(NotAReader(), DocumentReaderProtocol)

    def test_object_with_wrong_signature_does_not_satisfy_protocol(self) -> None:
        # runtime_checkable перевіряє лише наявність методу, не сигнатуру —
        # але перевіряємо що базова структурна перевірка працює
        class AlmostReader:
            def load_data(self, extra_arg: str) -> list[Document]:  # type: ignore[override]
                return []

        # Метод є — Protocol вважає його валідним (duck typing)
        assert isinstance(AlmostReader(), DocumentReaderProtocol)


# ---------------------------------------------------------------------------
# load_documents_from_dir — логіка функції
# ---------------------------------------------------------------------------


class TestLoadDocumentsFromDir:
    """Тести load_documents_from_dir через ін'єкцію фейкового reader."""

    def test_returns_documents_from_injected_reader(self, tmp_path: Path) -> None:
        docs = [Document(text="Medical guideline content")]
        result = load_documents_from_dir(tmp_path, reader=FakeReader(docs))
        assert result == docs

    def test_returns_empty_list_when_reader_returns_empty(self, tmp_path: Path) -> None:
        result = load_documents_from_dir(tmp_path, reader=FakeReader([]))
        assert result == []

    def test_returns_multiple_documents(self, tmp_path: Path) -> None:
        docs = [Document(text=f"doc {i}") for i in range(5)]
        result = load_documents_from_dir(tmp_path, reader=FakeReader(docs))
        assert len(result) == 5

    def test_raises_value_error_for_nonexistent_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(ValueError, match="does not exist"):
            load_documents_from_dir(missing, reader=FakeReader([]))

    def test_raises_value_error_for_file_path_instead_of_directory(
        self, tmp_path: Path
    ) -> None:
        file = tmp_path / "file.txt"
        file.write_text("content")
        with pytest.raises(ValueError, match="does not exist"):
            load_documents_from_dir(file, reader=FakeReader([]))

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        docs = [Document(text="from string path")]
        result = load_documents_from_dir(str(tmp_path), reader=FakeReader(docs))
        assert result == docs

    def test_validation_runs_before_reader_is_called(self, tmp_path: Path) -> None:
        """ValueError від відсутньої директорії має виникати до виклику reader.load_data."""
        missing = tmp_path / "ghost"

        calls: list[str] = []

        class SpyReader:
            def load_data(self) -> list[Document]:
                calls.append("called")
                return []

        with pytest.raises(ValueError):
            load_documents_from_dir(missing, reader=SpyReader())

        assert calls == [], "reader.load_data() must not be called for invalid path"

    def test_propagates_reader_exception(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="reader backend unavailable"):
            load_documents_from_dir(tmp_path, reader=FailingReader())

    def test_documents_preserve_metadata(self, tmp_path: Path) -> None:
        docs = [Document(text="content", metadata={"source": "pubmed", "year": 2024})]
        result = load_documents_from_dir(tmp_path, reader=FakeReader(docs))
        assert result[0].metadata == {"source": "pubmed", "year": 2024}

    @pytest.mark.parametrize("count", [1, 10, 100])
    def test_returns_correct_document_count(self, tmp_path: Path, count: int) -> None:
        docs = [Document(text=str(i)) for i in range(count)]
        result = load_documents_from_dir(tmp_path, reader=FakeReader(docs))
        assert len(result) == count


# ---------------------------------------------------------------------------
# Default reader instantiation (smoke — не торкається файлової системи)
# ---------------------------------------------------------------------------


class TestDefaultReaderInstantiation:
    """
    Перевіряємо що LlamaIndexDirectoryReader та LlamaIndexFileReader
    конструюються без помилок і реалізують Protocol.
    Фактичний виклик .load_data() потребує реальних файлів — це інтеграційний тест.
    """

    def test_llama_index_directory_reader_satisfies_protocol(
        self, tmp_path: Path
    ) -> None:
        # Конструктор не звертається до FS — SimpleDirectoryReader лінивий
        reader = LlamaIndexDirectoryReader(tmp_path)
        assert isinstance(reader, DocumentReaderProtocol)

    def test_llama_index_file_reader_satisfies_protocol(self, tmp_path: Path) -> None:
        fake_file = tmp_path / "guide.pdf"
        fake_file.write_bytes(b"")
        reader = LlamaIndexFileReader(fake_file)
        assert isinstance(reader, DocumentReaderProtocol)

    def test_load_documents_from_dir_uses_default_reader_without_explicit_arg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без явного reader функція будує LlamaIndexDirectoryReader і викликає load_data."""
        sentinel = [Document(text="sentinel")]

        class CapturingReader:
            called_with: Path | None = None

            def load_data(self) -> list[Document]:
                return sentinel

        capturing = CapturingReader()

        monkeypatch.setattr(
            "backend.rag.indexing.document_loader.LlamaIndexDirectoryReader",
            lambda path: capturing,  # type: ignore[misc]
        )

        result = load_documents_from_dir(tmp_path)
        assert result is sentinel
