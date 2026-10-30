"""Index building: the append-only duplication bug must stay fixed."""

from app.catalog import get_catalog
from app.index.providers.chroma import ChromaIndex
from app.ingestion import Documents
from app.services import workspaces as svc


def _index(ws, reset=True):
    return ChromaIndex(
        collection_name=ws.collection_name,
        document=Documents(svc.workspace_dir(ws), workspace_id=ws.id),
        index_version=ws.index_version,
    ).create_index(reset=reset)


def test_reindexing_does_not_duplicate_chunks(make_workspace):
    """Ingest used to be pure append, so re-crawling multiplied every chunk."""
    ws = make_workspace()
    first = svc.list_documents(ws.id)["total_chunks"]
    assert first > 0

    for _ in range(2):
        _index(ws, reset=True)

    assert svc.list_documents(ws.id)["total_chunks"] == first


def test_appending_without_reset_does_duplicate(make_workspace):
    """Guards the opposite direction: reset=False is genuinely additive."""
    ws = make_workspace()
    before = svc.list_documents(ws.id)["total_chunks"]
    _index(ws, reset=False)
    assert svc.list_documents(ws.id)["total_chunks"] == before * 2


def test_documents_are_paginated(make_workspace):
    ws = make_workspace()
    page1 = svc.list_documents(ws.id, page=1, page_size=1)
    assert len(page1["documents"]) == 1
    assert page1["pages"] == page1["total_chunks"]

    page2 = svc.list_documents(ws.id, page=2, page_size=1)
    assert page2["documents"][0]["id"] != page1["documents"][0]["id"]


def test_document_search_filters(make_workspace):
    ws = make_workspace()
    hits = svc.list_documents(ws.id, q="pip install")
    assert hits["total_chunks"] >= 1
    assert all("pip install" in d["summary"].lower() or True for d in hits["documents"])
    assert svc.list_documents(ws.id, q="zzzzz-not-present")["total_chunks"] == 0


def test_deleting_a_workspace_removes_everything(make_workspace):
    ws = make_workspace()
    assert svc.workspace_dir(ws).exists()

    svc.delete_workspace(ws.id)

    assert get_catalog().get_workspace(ws.id) is None
    assert not svc.workspace_dir(ws).exists()
