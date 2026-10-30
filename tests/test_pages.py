"""Front-matter round-trip, hashing and the link graph."""

from pathlib import Path

from app.crawler.pages import PageRecord, WorkspaceStore, content_hash, page_id_for


def test_page_id_is_stable_and_url_specific():
    assert page_id_for("https://a.dev/x") == page_id_for("https://a.dev/x")
    assert page_id_for("https://a.dev/x") != page_id_for("https://a.dev/y")


def test_front_matter_round_trip(tmp_path: Path):
    store = WorkspaceStore(tmp_path)
    rec = PageRecord(url="https://a.dev/x", title="X", depth=2, outlinks=["https://a.dev/y"])
    store.write_page(rec, "# X\n\nbody text")

    meta, body = store.read_page(tmp_path / rec.file)
    assert meta["url"] == "https://a.dev/x"
    assert meta["title"] == "X"
    assert meta["depth"] == 2
    assert meta["outlinks"] == ["https://a.dev/y"]
    assert body.strip() == "# X\n\nbody text"
    assert meta["content_hash"] == content_hash("# X\n\nbody text")


def test_content_hash_detects_change():
    assert content_hash("a") != content_hash("b")
    assert content_hash("a") == content_hash("a")


def test_graph_drops_external_and_uncrawled_links(tmp_path: Path):
    store = WorkspaceStore(tmp_path)
    a = PageRecord(url="https://a.dev", title="A", outlinks=["https://a.dev/b", "https://other.com/z"])
    b = PageRecord(url="https://a.dev/b", title="B", outlinks=["https://a.dev"])
    for rec, body in ((a, "# A"), (b, "# B")):
        store.write_page(rec, body)
    store.write_manifest("https://a.dev", [a, b], mode="site")

    graph = store.graph()
    assert len(graph["nodes"]) == 2
    # a->b and b->a are kept; the external link is not.
    assert len(graph["edges"]) == 2
    assert all(
        e["source"] in {a.page_id, b.page_id} and e["target"] in {a.page_id, b.page_id}
        for e in graph["edges"]
    )


def test_graph_depth_is_link_distance_from_seed(tmp_path: Path):
    """Sitemap-discovered pages all carry depth 0; the graph must derive real distance."""
    store = WorkspaceStore(tmp_path)
    seed = PageRecord(url="https://a.dev", title="seed", depth=0, outlinks=["https://a.dev/one"])
    one = PageRecord(url="https://a.dev/one", title="one", depth=0, outlinks=["https://a.dev/two"])
    two = PageRecord(url="https://a.dev/two", title="two", depth=0, outlinks=[])
    for rec in (seed, one, two):
        store.write_page(rec, f"# {rec.title}")
    store.write_manifest("https://a.dev", [seed, one, two], mode="site")

    depths = {n["url"]: n["depth"] for n in store.graph()["nodes"]}
    assert depths["https://a.dev"] == 0
    assert depths["https://a.dev/one"] == 1
    assert depths["https://a.dev/two"] == 2


def test_failed_pages_are_recorded_not_silently_dropped(tmp_path: Path):
    store = WorkspaceStore(tmp_path)
    ok = PageRecord(url="https://a.dev", title="A")
    store.write_page(ok, "# A")
    bad = PageRecord(url="https://a.dev/gone", error="404")

    manifest = store.write_manifest("https://a.dev", [ok, bad], mode="site")
    assert manifest["page_count"] == 1
    assert len(manifest["pages"]) == 2
    assert not bad.ok and ok.ok
    # A failed page must not become a graph node.
    assert len(store.graph()["nodes"]) == 1
