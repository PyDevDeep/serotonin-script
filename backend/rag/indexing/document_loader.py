from pathlib import Path
from typing import Protocol, runtime_checkable

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document


@runtime_checkable
class DocumentReaderProtocol(Protocol):
    """Contract for anything that can load Documents from a file path or directory."""

    def load_data(self) -> list[Document]:
        """Return a list of loaded Documents."""
        ...


class LlamaIndexDirectoryReader:
    """Thin wrapper around SimpleDirectoryReader that satisfies DocumentReaderProtocol."""

    def __init__(self, directory_path: str | Path) -> None:
        self._directory_path = str(directory_path)

    def load_data(self) -> list[Document]:
        reader = SimpleDirectoryReader(
            input_dir=self._directory_path,
            required_exts=[".md", ".txt", ".pdf"],
            recursive=True,
        )
        return reader.load_data()


class LlamaIndexFileReader:
    """Thin wrapper around SimpleDirectoryReader for a single file."""

    def __init__(self, file_path: str | Path) -> None:
        self._reader = SimpleDirectoryReader(input_files=[str(file_path)])

    def load_data(self) -> list[Document]:
        return self._reader.load_data()


def load_documents_from_dir(
    directory_path: str | Path,
    reader: DocumentReaderProtocol | None = None,
) -> list[Document]:
    """
    Завантажує всі підтримувані документи (MD, TXT, PDF) з вказаної директорії.

    Args:
        directory_path: Шлях до директорії з документами.
        reader: Реалізація DocumentReaderProtocol. За замовчуванням —
                LlamaIndexDirectoryReader з підтримкою PDF через PyMuPDF.
    """
    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Directory {directory_path} does not exist.")

    if reader is None:
        reader = LlamaIndexDirectoryReader(path)

    return reader.load_data()
