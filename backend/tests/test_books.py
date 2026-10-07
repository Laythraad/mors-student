"""Textbook library: listing, reading, progress, in-book search, page-aware chat."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_books_require_auth(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/books").status_code == 401


def test_library_lists_books(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/books", headers=demo_headers).json()
    books = data["books"]
    assert books and data["subjects"]
    first = books[0]
    assert first["page_count"] > 0
    # real (ingested) books carry pages without a chapter map; the demo books
    # still do — the shelf as a whole must offer both
    assert any(b["chapter_count"] > 0 for b in books)
    assert first["progress"]["last_page"] == 1 and first["progress"]["percent"] == 0
    assert all(b["id"] and b["title"] for b in books)

    filtered = client.get(
        "/api/books", params={"q": first["title"][:5]}, headers=demo_headers
    ).json()["books"]
    assert any(b["id"] == first["id"] for b in filtered)


def test_book_detail_toc_and_pages(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    book = client.get("/api/books", headers=demo_headers).json()["books"][0]
    detail = client.get(f"/api/books/{book['id']}", headers=demo_headers).json()
    assert detail["toc"] and detail["page_count"] > 0
    assert detail["is_indexed"] is True
    assert any(unit["lessons"] for chapter in detail["toc"] for unit in chapter["units"])

    page = client.get(
        f"/api/books/{book['id']}/page", params={"n": 2}, headers=demo_headers
    ).json()
    assert page["page_number"] == 2
    assert len(page["text"]) > 40 and page["heading"]
    assert page["book_id"] == book["id"]
    assert page["citation"].startswith(book["title"])
    assert "صفحة 2" in page["citation"]
    assert page["next"] == 3

    clamped = client.get(
        f"/api/books/{book['id']}/page", params={"n": 99999}, headers=demo_headers
    ).json()
    assert 1 <= clamped["page_number"] <= detail["page_count"]

    missing = client.get("/api/books/does-not-exist", headers=demo_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_reading_progress_roundtrip(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    book = client.get("/api/books", headers=demo_headers).json()["books"][1]

    saved = client.put(
        f"/api/books/{book['id']}/progress",
        headers=demo_headers,
        json={
            "last_page": 4,
            "bookmark": {"page": 4, "label": "مراجعة"},
            "highlight": {"page": 4, "text": "نص مهم", "note": ""},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["last_page"] == 4

    got = client.get(f"/api/books/{book['id']}/progress", headers=demo_headers).json()
    assert got["last_page"] == 4
    assert got["bookmarks"][0]["page"] == 4
    assert got["highlights"][0]["page"] == 4
    assert got["percent"] > 0

    removed = client.put(
        f"/api/books/{book['id']}/progress",
        headers=demo_headers,
        json={"remove_bookmark": 4, "remove_highlight": 4},
    ).json()
    assert removed["bookmarks"] == [] and removed["highlights"] == []


def test_in_book_search(client: TestClient, demo_headers: dict[str, str]) -> None:
    book = client.get("/api/books", headers=demo_headers).json()["books"][0]
    empty = client.get(f"/api/books/{book['id']}/search", headers=demo_headers).json()
    assert empty["results"] == []

    word = "الدرس"
    found = client.get(
        f"/api/books/{book['id']}/search", params={"q": word}, headers=demo_headers
    ).json()
    assert found["results"]
    hit = found["results"][0]
    assert hit["page_number"] >= 1 and hit["snippet"]
    assert word in hit["snippet"] or word in hit["heading"]


def test_chat_cites_the_open_page(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    book = client.get("/api/books", headers=demo_headers).json()["books"][0]
    page = client.get(
        f"/api/books/{book['id']}/page", params={"n": 1}, headers=demo_headers
    ).json()

    response = client.post(
        "/api/chat/messages",
        headers=demo_headers,
        json={
            "message": "ما الهدف الأول من هذا الدرس؟",
            "mode": "explain",
            "book_id": book["id"],
            "page_number": 1,
            "selection": page["text"][:60],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["reply"] and not data["refused"]
    assert any(c.get("page") == 1 and c.get("citation") for c in data["citations"])
    assert any(c.get("title") == book["title"] for c in data["citations"])


def test_reindex_is_admin_only(
    client: TestClient, demo_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    book = client.get("/api/books", headers=demo_headers).json()["books"][0]

    forbidden = client.post(f"/api/books/{book['id']}/reindex", headers=demo_headers)
    assert forbidden.status_code == 403

    ok = client.post(f"/api/books/{book['id']}/reindex", headers=admin_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["indexed"] > 0


# --- P1 2.1: the shelf itself ---------------------------------------------


def test_shelf_is_scoped_to_the_students_own_branch(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    """The stage used to be OR-ed with the branch, leaking the literary shelf."""
    data = client.get("/api/books", headers=demo_headers).json()
    books = data["books"]
    assert books
    branches = {b["branch"] for b in books}
    assert "" not in branches
    assert len(branches) == 1, f"cross-branch duplicates: {branches}"

    chip_names = [s["name"] for s in data["subjects"]]
    assert len(chip_names) == len(set(chip_names)), f"duplicate filter chips: {chip_names}"


def test_a_real_book_replaces_its_demo_twin(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    books = client.get("/api/books", headers=demo_headers).json()["books"]
    by_subject: dict[str, list[bool]] = {}
    for book in books:
        by_subject.setdefault(book["subject"], []).append(book["is_demo"])
    twins = {name: flags for name, flags in by_subject.items() if len(flags) > 1}
    assert not twins, f"duplicate entries per subject: {twins}"


def test_books_are_labeled_from_the_curriculum_tree(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    books = client.get("/api/books", headers=demo_headers).json()["books"]
    for book in books:
        assert book["subject"] and book["grade"] and book["branch"], book
    detail = client.get(f"/api/books/{books[0]['id']}", headers=demo_headers).json()
    assert detail["subject"] and detail["grade"] and detail["branch"]


def test_every_shelf_entry_opens(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    """No dead entry: every card leads to a readable first page."""
    books = client.get("/api/books", headers=demo_headers).json()["books"]
    assert books
    for book in books:
        detail = client.get(f"/api/books/{book['id']}", headers=demo_headers)
        assert detail.status_code == 200, book["title"]
        assert detail.json()["page_count"] > 0, book["title"]

        page = client.get(
            f"/api/books/{book['id']}/page", params={"n": 1}, headers=demo_headers
        )
        assert page.status_code == 200, book["title"]
        body = page.json()
        assert body["text"].strip(), f"blank page in {book['title']}"


def test_search_and_filter_actually_work(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    shelf = client.get("/api/books", headers=demo_headers).json()
    assert shelf["subjects"]

    # the UI promises "كتاب أو مادة" — the subject name must be searchable
    name = shelf["subjects"][0]["name"]
    hits = client.get("/api/books", params={"q": name}, headers=demo_headers).json()
    assert hits["books"], name
    assert any(b["subject"] == name for b in hits["books"])

    # the filter bar must survive a search that matches nothing
    miss = client.get("/api/books", params={"q": "zzzz-no-such-book"}, headers=demo_headers).json()
    assert miss["books"] == []
    assert miss["subjects"], "the subject chips vanished on an empty result"

    # and a subject filter narrows the shelf without losing the bar
    one = client.get(
        "/api/books", params={"subject_id": shelf["subjects"][0]["id"]}, headers=demo_headers
    ).json()
    assert one["books"] and all(b["subject"] == name for b in one["books"])
    assert len(one["subjects"]) == len(shelf["subjects"])


def test_reading_a_page_saves_the_place(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    """Regression: the reader's position used to be flushed and rolled back."""
    books = client.get("/api/books", headers=demo_headers).json()["books"]
    book = next((b for b in books if b["page_count"] >= 3), books[0])
    opened = client.get(f"/api/books/{book['id']}", headers=demo_headers).json()
    assert opened["progress"]["opened_count"] >= 1

    client.get(f"/api/books/{book['id']}/page", params={"n": 2}, headers=demo_headers)
    progress = client.get(f"/api/books/{book['id']}/progress", headers=demo_headers).json()
    assert progress["last_page"] == 2, progress
    assert progress["percent"] > 0, progress

    listed = next(
        b
        for b in client.get("/api/books", headers=demo_headers).json()["books"]
        if b["id"] == book["id"]
    )
    assert listed["progress"]["last_page"] == 2, "the shelf card does not offer resume"
