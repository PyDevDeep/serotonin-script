from pathlib import Path

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document


def load_documents_from_dir(directory_path: str | Path) -> list[Document]:
    """
    Завантажує всі підтримувані документи (MD, TXT, PDF) з вказаної директорії.
    Використовує PyMuPDF під капотом для PDF завдяки llama-index-readers-file.
    """
    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Directory {directory_path} does not exist.")

    reader = SimpleDirectoryReader(
        input_dir=str(path), required_exts=[".md", ".txt", ".pdf"], recursive=True
    )
    return reader.load_data()
