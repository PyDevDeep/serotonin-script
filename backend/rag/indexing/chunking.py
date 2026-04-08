from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, Document, TextNode


def chunk_documents(
    documents: list[Document], chunk_size: int = 512, chunk_overlap: int = 50
) -> list[BaseNode]:
    """
    Розбиває список документів на вузли (чанки).

    Для MD-файлів з роздільником '---' використовує PostSplitter (один чанк = один пост).
    Для решти файлів — SentenceSplitter за розміром токенів.
    """
    if not documents:
        return []

    md_docs = [d for d in documents if _is_post_separated(d)]
    other_docs = [d for d in documents if not _is_post_separated(d)]

    nodes: list[BaseNode] = []

    for doc in md_docs:
        nodes.extend(_split_by_separator(doc))

    if other_docs:
        parser = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        nodes.extend(parser.get_nodes_from_documents(other_docs))

    return nodes


def _is_post_separated(doc: Document) -> bool:
    """Повертає True якщо документ містить роздільники '---' між постами."""
    return "\n---\n" in doc.text or doc.text.startswith("---\n")


def _split_by_separator(doc: Document, separator: str = "\n---\n") -> list[TextNode]:
    """Ділить документ по роздільнику '---', повертає непорожні TextNode зі збереженням метаданих."""
    parts = doc.text.split(separator)
    nodes: list[TextNode] = []
    for part in parts:
        text = part.strip()
        if text:
            nodes.append(TextNode(text=text, metadata=doc.metadata.copy()))
    return nodes
