"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

const INTENTS = [
  { key: "explain", label: "اشرح", mode: "explain", prompt: "اشرح لي هذا المقطع بأسلوب بسيط." },
  { key: "summarize", label: "لخص", mode: "summarize", prompt: "لخص لي هذا المقطع في نقاط." },
  { key: "quiz", label: "اختبرني", mode: "quiz", prompt: "اختبرني على هذا المقطع بأسئلة قصيرة." },
  { key: "exam", label: "ما المهم للامتحان؟", mode: "explain", prompt: "ما المهم من هذا المقطع للامتحان؟" },
  { key: "example", label: "مثال", mode: "explain", prompt: "أعطني مثالاً واضحاً يوضّح هذا المقطع." },
];

const noteTitle = (bookTitle, pageNumber) => `${bookTitle} — ملاحظة صفحة ${pageNumber}`;

export default function BookReader() {
  const params = useParams();
  const bookId = params.id;

  const [book, setBook] = useState(null);
  const [page, setPage] = useState(null);
  const [progress, setProgress] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [tocOpen, setTocOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [goto, setGoto] = useState("");

  const [night, setNight] = useState(false);
  const [scale, setScale] = useState(1);
  const [selection, setSelection] = useState("");

  const [note, setNote] = useState("");
  const [noteId, setNoteId] = useState(null);
  const [noteBusy, setNoteBusy] = useState(false);

  const [askBusy, setAskBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [askError, setAskError] = useState("");

  const contentRef = useRef(null);

  const pageNumber = page ? page.page_number : 1;
  const pageCount = page ? page.page_count : 0;
  const bookmarked = progress
    ? (progress.bookmarks || []).some((b) => b.page === pageNumber)
    : false;
  const pageHighlights = useMemo(
    () => (progress ? (progress.highlights || []).filter((h) => h.page === pageNumber) : []),
    [progress, pageNumber]
  );

  const loadProgress = useCallback(async () => {
    if (!bookId) return;
    try {
      const data = await api(`/api/books/${bookId}/progress`);
      setProgress(data);
    } catch {
      /* progress is optional — the page still reads fine without it */
    }
  }, [bookId]);

  const loadPage = useCallback(
    async (number) => {
      if (!bookId) return;
      setLoading(true);
      try {
        const data = await api(`/api/books/${bookId}/page`, { query: { n: number } });
        setPage(data);
        setError("");
        setSelection("");
        setAnswer(null);
        await loadProgress();
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          url.searchParams.set("page", String(data.page_number));
          window.history.replaceState(null, "", url.toString());
        }
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [bookId, loadProgress]
  );

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api(`/api/books/${bookId}`);
        if (cancelled) return;
        setBook(data);
        const requested = Number(new URLSearchParams(window.location.search).get("page"));
        const start =
          requested > 0 ? requested : data.progress && data.progress.last_page > 1 ? data.progress.last_page : 1;
        await loadPage(start);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bookId, loadPage]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedNight = window.localStorage.getItem("mors_reader_night") === "1";
    const savedScale = Number(window.localStorage.getItem("mors_reader_scale"));
    if (savedNight) setNight(true);
    if (savedScale >= 0.8 && savedScale <= 1.6) setScale(savedScale);
  }, []);

  useEffect(() => {
    function capture() {
      const text = window.getSelection ? String(window.getSelection() || "") : "";
      setSelection(text.trim().length >= 2 ? text.trim().slice(0, 1500) : "");
    }
    document.addEventListener("mouseup", capture);
    document.addEventListener("keyup", capture);
    return () => {
      document.removeEventListener("mouseup", capture);
      document.removeEventListener("keyup", capture);
    };
  }, []);

  // page note (created through the regular notes API, one per page)
  useEffect(() => {
    setNote("");
    setNoteId(null);
    if (!book || !pageNumber) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api("/api/library/notes", { query: { q: `صفحة ${pageNumber}` } });
        const exact = (data.notes || []).find((n) => n.title === noteTitle(book.title, pageNumber));
        if (!cancelled && exact) {
          setNote(exact.body || "");
          setNoteId(exact.id);
        }
      } catch {
        /* notes are optional */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [book, pageNumber]);

  function go(number) {
    const target = Math.max(1, Math.min(pageCount || 1, Number(number) || 1));
    setTocOpen(false);
    setResults(null);
    setQuery("");
    loadPage(target);
  }

  function toggleNight() {
    setNight((value) => {
      const next = !value;
      if (typeof window !== "undefined") {
        window.localStorage.setItem("mors_reader_night", next ? "1" : "0");
      }
      return next;
    });
  }

  function changeScale(delta) {
    setScale((value) => {
      const next = Math.min(1.6, Math.max(0.8, Math.round((value + delta) * 10) / 10));
      if (typeof window !== "undefined") {
        window.localStorage.setItem("mors_reader_scale", String(next));
      }
      return next;
    });
  }

  async function runSearch() {
    if (!query.trim()) return;
    try {
      const data = await api(`/api/books/${bookId}/search`, { query: { q: query } });
      setResults(data.results || []);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function toggleBookmark() {
    if (!progress) return;
    try {
      const body = bookmarked
        ? { remove_bookmark: pageNumber }
        : { bookmark: { page: pageNumber, label: page.heading || `صفحة ${pageNumber}` } };
      const data = await api(`/api/books/${bookId}/progress`, { method: "PUT", body });
      setProgress(data);
      setNotice(bookmarked ? "أُزيل العلامة." : "وُضعت علامة على الصفحة.");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveHighlight() {
    if (!selection) return;
    try {
      const data = await api(`/api/books/${bookId}/progress`, {
        method: "PUT",
        body: { highlight: { page: pageNumber, text: selection } },
      });
      setProgress(data);
      setSelection("");
      setNotice("حُفظ التظليل.");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function removeHighlight(text) {
    try {
      const data = await api(`/api/books/${bookId}/progress`, {
        method: "PUT",
        body: { remove_highlight: pageNumber },
      });
      setProgress(data);
      void text;
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveNote() {
    if (!book) return;
    setNoteBusy(true);
    try {
      const title = noteTitle(book.title, pageNumber);
      if (noteId) {
        await api(`/api/library/notes/${noteId}`, {
          method: "PATCH",
          body: { title, body: note },
        });
      } else {
        const data = await api("/api/library/notes", {
          method: "POST",
          body: { title, body: note, lesson_id: page.lesson_id || null },
        });
        setNoteId(data.id || (data.note && data.note.id) || null);
      }
      setNotice("حُفظت ملاحظتك.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setNoteBusy(false);
    }
  }

  async function askMors(intent) {
    if (!bookId) return;
    setAskBusy(true);
    setAskError("");
    try {
      const body = {
        message: selection ? `${intent.prompt}\n\nالمقطع المحدد:\n${selection}` : intent.prompt,
        mode: intent.mode,
        book_id: bookId,
        page_number: pageNumber,
        selection,
      };
      const data = await api("/api/chat/messages", { method: "POST", body });
      setAnswer(data);
    } catch (err) {
      setAskError(errorMessage(err));
    } finally {
      setAskBusy(false);
    }
  }

  const paragraphs = useMemo(() => {
    if (!page) return [];
    return String(page.text || "")
      .split(/\n{2,}/)
      .map((block) => block.trim())
      .filter(Boolean);
  }, [page]);

  function withHighlights(block) {
    if (!pageHighlights.length) return block;
    const parts = [{ text: block, mark: false }];
    pageHighlights.forEach((h) => {
      const needle = (h.text || "").trim();
      if (!needle) return;
      for (let i = parts.length - 1; i >= 0; i -= 1) {
        const part = parts[i];
        if (part.mark) continue;
        const at = part.text.indexOf(needle);
        if (at < 0) continue;
        parts.splice(
          i,
          1,
          { text: part.text.slice(0, at), mark: false },
          { text: needle, mark: true },
          { text: part.text.slice(at + needle.length), mark: false }
        );
      }
    });
    return parts.filter((p) => p.text).map((p, index) => (p.mark ? <mark key={index}>{p.text}</mark> : <span key={index}>{p.text}</span>));
  }

  const toc = book ? book.toc || [] : [];

  return (
    <Shell title={book ? book.title : "القارئ"}>
      <div className={`reader${night ? " night" : ""}`}>
        {error ? <div className="error-box">{error}</div> : null}
        {notice ? <div className="success-box">{notice}</div> : null}

        <div className="reader-toolbar">
          <Link className="btn ghost sm" href="/library">
            ← المكتبة
          </Link>
          <span className="reader-place small muted">
            {page ? `${page.chapter || book?.subject || ""} · صفحة ${pageNumber} من ${pageCount}` : "…"}
          </span>
          <span className="row">
            <button className="btn ghost sm" onClick={() => setTocOpen(true)} title="جدول المحتويات">
              ☰
            </button>
            <button
              className={`btn ghost sm${searchOpen ? " soft" : ""}`}
              onClick={() => setSearchOpen((v) => !v)}
              title="بحث داخل الكتاب"
            >
              🔍
            </button>
            <button className="btn ghost sm" onClick={() => changeScale(-0.1)} title="تصغير">
              A−
            </button>
            <button className="btn ghost sm" onClick={() => changeScale(0.1)} title="تكبير">
              A+
            </button>
            <button className="btn ghost sm" onClick={toggleNight} title="الوضع الليلي">
              {night ? "☀️" : "🌙"}
            </button>
            <button
              className={`btn sm${bookmarked ? "" : " ghost"}`}
              onClick={toggleBookmark}
              title="علامة"
              disabled={!progress}
            >
              {bookmarked ? "★" : "☆"}
            </button>
          </span>
        </div>

        {searchOpen ? (
          <div className="reader-search">
            <div className="field" style={{ marginBottom: 0, flex: 1 }}>
              <input
                className="input"
                placeholder="ابحث داخل الكتاب…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
                autoFocus
              />
            </div>
            <button className="btn" onClick={runSearch}>
              بحث
            </button>
            {results ? (
              <div className="list" style={{ width: "100%" }}>
                {results.map((hit) => (
                  <button
                    key={hit.page_number}
                    className="list-item reader-hit"
                    onClick={() => go(hit.page_number)}
                  >
                    <div className="grow" style={{ textAlign: "right" }}>
                      <div className="title small">
                        صفحة {hit.page_number} · {hit.heading}
                      </div>
                      <div className="small muted ellip">{hit.snippet}</div>
                    </div>
                  </button>
                ))}
                {!results.length ? <div className="empty">ما لقينا هيج شي بهذا الكتاب.</div> : null}
              </div>
            ) : null}
          </div>
        ) : null}

        <div
          className={`reader-sheet${loading ? " loading" : ""}`}
          ref={contentRef}
          style={{ fontSize: `${scale}rem` }}
        >
          {page ? (
            <>
              <div className="reader-meta small muted">
                {[page.chapter, page.unit, page.lesson].filter(Boolean).join(" · ")}
                {page.is_demo ? <span className="tag demo">نص تجريبي</span> : null}
              </div>
              <h2 className="reader-heading">{page.heading || book?.title}</h2>
              {paragraphs.map((block, index) => (
                <p key={index} className="reader-p">
                  {withHighlights(block)}
                </p>
              ))}
              {page.is_demo ? (
                <p className="reader-note small muted">
                  هذه الصفحات تجريبية: أُنشئت من ملخص الدرس وأهدافه لعرض تجربة القارئ، والنص الرسمي
                  للكتاب يُرفع من لوحة الإدارة.
                </p>
              ) : null}
            </>
          ) : (
            <div className="empty">جاري فتح الصفحة…</div>
          )}
        </div>

        <div className="reader-nav">
          <button className="btn" disabled={!page || pageNumber <= 1} onClick={() => go(pageNumber - 1)}>
            → السابقة
          </button>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              go(goto);
            }}
          >
            <input
              className="input"
              style={{ width: 92, textAlign: "center" }}
              inputMode="numeric"
              placeholder="رقم"
              value={goto}
              onChange={(e) => setGoto(e.target.value.replace(/\D/g, ""))}
            />
            <button className="btn ghost sm" type="submit">
              انتقال
            </button>
          </form>
          <button
            className="btn"
            disabled={!page || pageNumber >= pageCount}
            onClick={() => go(pageNumber + 1)}
          >
            التالية ←
          </button>
        </div>

        {selection ? (
          <div className="reader-selection">
            <div className="small muted ellip">المحدد: {selection.slice(0, 120)}</div>
            <div className="row wrap">
              <button className="btn sm" onClick={() => askMors(INTENTS[0])}>
                اسأل مورس عن التحديد
              </button>
              <button className="btn ghost sm" onClick={saveHighlight}>
                ✨ ظلّل
              </button>
            </div>
          </div>
        ) : null}

        <div className="card">
          <div className="card-title">
            <h3>اسأل مورس</h3>
            <span className="tag">{page ? `صفحة ${pageNumber}` : ""}</span>
          </div>
          <div className="row wrap">
            {INTENTS.map((intent) => (
              <button
                key={intent.key}
                className="chip"
                disabled={askBusy}
                onClick={() => askMors(intent)}
              >
                {intent.label}
              </button>
            ))}
          </div>
          {askError ? <div className="error-box" style={{ marginTop: 10 }}>{askError}</div> : null}
          {askBusy ? <div className="empty" style={{ marginTop: 10 }}>مورس يقرأ الصفحة…</div> : null}
          {answer ? (
            <div className="reader-answer">
              <p style={{ whiteSpace: "pre-wrap" }}>{answer.reply}</p>
              {(answer.citations || []).length ? (
                <div className="small muted">
                  المصدر:{" "}
                  {answer.citations.map((c, i) => (
                    <span key={i} className="tag" style={{ marginInlineEnd: 6 }}>
                      {c.citation || c.title}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="card">
          <div className="card-title">
            <h3>ملاحظتي على هذه الصفحة</h3>
            <span className="small muted">{noteId ? "محفوظة" : "غير محفوظة"}</span>
          </div>
          <div className="field">
            <textarea
              className="textarea"
              placeholder="اكتب ملاحظتك هنا…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <button className="btn" disabled={noteBusy || !note.trim()} onClick={saveNote}>
            {noteBusy ? "جاري الحفظ…" : "حفظ الملاحظة"}
          </button>
        </div>

        {pageHighlights.length ? (
          <div className="card">
            <div className="card-title">
              <h3>تظليلات الصفحة</h3>
            </div>
            <div className="list">
              {pageHighlights.map((h, index) => (
                <div className="list-item" key={index}>
                  <div className="grow small">{h.text}</div>
                  <button className="btn ghost sm" onClick={() => removeHighlight(h.text)}>
                    🗑
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {tocOpen ? (
          <div className="reader-overlay" onClick={() => setTocOpen(false)}>
            <div className="reader-toc" onClick={(e) => e.stopPropagation()}>
              <div className="card-title">
                <h3>جدول المحتويات</h3>
                <button className="btn ghost sm" onClick={() => setTocOpen(false)}>
                  إغلاق
                </button>
              </div>
              <div className="reader-toc-scroll">
                {toc.map((chapter) => (
                  <div key={chapter.id || chapter.title} className="reader-toc-chapter">
                    <strong>{chapter.title}</strong>
                    {(chapter.units || []).map((unit) => (
                      <div key={unit.id || unit.title} className="reader-toc-unit">
                        <span className="small muted">{unit.title}</span>
                        {(unit.lessons || []).map((lesson) => (
                          <button
                            key={lesson.id}
                            className="reader-toc-lesson"
                            onClick={() => go(lesson.first_page || pageNumber)}
                          >
                            <span>{lesson.title}</span>
                            <span className="small muted">
                              {lesson.first_page ? `ص ${lesson.first_page}` : ""}
                            </span>
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                ))}
                {!toc.length ? <div className="empty">فهرس غير متاح.</div> : null}
              </div>
            </div>
          </div>
        ) : null}

        {progress && (progress.bookmarks || []).length ? (
          <div className="card">
            <div className="card-title">
              <h3>علاماتي</h3>
            </div>
            <div className="row wrap">
              {progress.bookmarks.map((b) => (
                <button key={b.page} className="chip" onClick={() => go(b.page)}>
                  ★ ص {b.page} {b.label ? `— ${b.label}` : ""}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </Shell>
  );
}
