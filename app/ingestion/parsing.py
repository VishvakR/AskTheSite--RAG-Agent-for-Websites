"""
Document loading and chunking.

Every chunk carries the metadata needed for citations and the knowledge graph:
``source_url``, ``page_title``, ``page_id``, ``heading``, ``chunk_index`` and
``content_hash``.  The old loader used ``DirectoryLoader`` + ``TextLoader``,
which attached only the file path, so a chunk could never be traced back to the
page it came from.

Chunking is header-aware: the markdown is first split on its heading structure
(so a chunk keeps the section it belongs to), then each section is split to
size.  ``MarkdownHeaderTextSplitter`` was already imported by the old module
but never actually used.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from langchain_core.documents import Document
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from pydantic import BaseModel, Field

from app.crawler.pages import WorkspaceStore, content_hash

logger = logging.getLogger(__name__)

HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]


class MetaDataParser:
    """Optional LLM pass that adds a title/summary/keywords to each chunk."""

    def __init__(self, llm):
        self.llm = llm

        class MetaDataSchema(BaseModel):
            title: str = Field(description="Title of the document")
            summary: str = Field(description="Summary of the document")
            keywords: List[str] = Field(description="Keywords of the document")

        self.parser = PydanticOutputParser(pydantic_object=MetaDataSchema)
        self.prompt = ChatPromptTemplate.from_template(
            """
                Extract metadata from the following text.

                Return output strictly in this JSON format:
                {format_instructions}

                TEXT:
                {text}
            """
        ).partial(format_instructions=self.parser.get_format_instructions())

    def add_metadata(self, documents: List[Document]) -> List[Document]:
        for doc in documents:
            try:
                response = self.llm.generate_response(
                    self.prompt.format(text=doc.page_content)
                )
                parsed = self.parser.parse(response)
                doc.metadata["title"] = parsed.title
                doc.metadata["summary"] = parsed.summary
                doc.metadata["keywords"] = ", ".join(parsed.keywords)
            except Exception:
                # A metadata failure must not sink the whole ingest.
                logger.warning("Metadata extraction failed for a chunk", exc_info=True)
        return documents


class Documents:
    """Loads a workspace's crawled pages and turns them into indexable chunks."""

    def __init__(
        self,
        input_files: Union[List[str], str, Path],
        workspace_id: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        llm=None,
        add_metadata: bool = False,
    ):
        from app.config import get_settings

        settings = get_settings()
        self.workspace_id = workspace_id

        if isinstance(input_files, list):
            self.files: Optional[List[Path]] = [Path(f) for f in input_files]
            self.input_dir: Optional[Path] = None
        else:
            self.files = None
            self.input_dir = Path(input_files)

        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=HEADERS_TO_SPLIT_ON,
            strip_headers=False,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size or settings.chunk_size,
            chunk_overlap=chunk_overlap or settings.chunk_overlap,
        )

        self.add_metadata = add_metadata
        if self.add_metadata:
            if llm is None:
                raise ValueError("LLM is required to add metadata")
            self.metadata_parser = MetaDataParser(llm)

    # ── loading ───────────────────────────────────────────────────────────

    def _page_paths(self) -> List[Path]:
        if self.files is not None:
            return self.files
        if self.input_dir is None:
            return []
        store = WorkspaceStore(self.input_dir)
        paths = list(store.iter_page_files())
        if paths:
            return paths
        # Fall back to any markdown under the directory (legacy layout).
        return sorted(self.input_dir.rglob("*.md"))

    def load_documents(self) -> List[Document]:
        """One :class:`Document` per crawled page, with front-matter metadata."""
        docs: List[Document] = []
        for path in self._page_paths():
            try:
                store = WorkspaceStore(path.parent.parent)
                meta, body = store.read_page(path)
            except Exception:
                logger.warning("Skipping unreadable page %s", path, exc_info=True)
                continue

            if not body.strip():
                continue

            docs.append(
                Document(
                    page_content=body,
                    metadata={
                        "source_url": str(meta.get("url", "")),
                        "page_title": str(meta.get("title") or meta.get("url", "")),
                        "page_id": str(meta.get("page_id", "")),
                        "depth": int(meta.get("depth", 0) or 0),
                        "content_hash": str(
                            meta.get("content_hash") or content_hash(body)
                        ),
                        "source": str(path),
                        **({"workspace_id": self.workspace_id} if self.workspace_id else {}),
                    },
                )
            )
        logger.info("Loaded %d page(s) for indexing", len(docs))
        return docs

    # ── chunking ──────────────────────────────────────────────────────────

    @staticmethod
    def _heading_of(header_meta: Dict[str, Any]) -> str:
        """Deepest heading present, e.g. 'Usage > Installation'."""
        parts = [header_meta.get(k) for _, k in HEADERS_TO_SPLIT_ON]
        return " > ".join(p for p in parts if p)

    def split(self) -> List[Document]:
        chunks: List[Document] = []
        for doc in self.load_documents():
            try:
                sections = self.header_splitter.split_text(doc.page_content)
            except Exception:
                logger.warning(
                    "Header split failed for %s; falling back to plain split",
                    doc.metadata.get("source_url"),
                    exc_info=True,
                )
                sections = [Document(page_content=doc.page_content, metadata={})]

            if not sections:
                sections = [Document(page_content=doc.page_content, metadata={})]

            index = 0
            for section in sections:
                heading = self._heading_of(section.metadata or {})
                for piece in self.text_splitter.split_text(section.page_content):
                    if not piece.strip():
                        continue
                    chunks.append(
                        Document(
                            page_content=piece,
                            metadata={
                                **doc.metadata,
                                "heading": heading,
                                "chunk_index": index,
                            },
                        )
                    )
                    index += 1

        logger.info("Produced %d chunk(s)", len(chunks))
        return chunks

    def create_nodes(self) -> List[Document]:
        chunks = self.split()
        if self.add_metadata:
            chunks = self.metadata_parser.add_metadata(chunks)
        return chunks
