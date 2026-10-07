"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

export default function LibraryPage() {
  return (
    <Shell title="المكتبة">
      <LibraryBody />
    </Shell>
  );
}

function LibraryBody() {
  const [books, setBooks] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [subject, setSubject] = useState("");
  const [query, setQuery] = useState("");
  const [attempt, setAttempt] = useState(0);

  // the backend owns search + filtering (title, author, edition, subject) so
  // what you type is what the shelf actually contains
  useEffect(() => {
    let alive = true;
    setBusy(true);
    const timer = setTimeout(() => {
      api("/api/books", {
        query: {
          q: query.trim() || undefined,
          subject_id: subject || undefined,
          limit: 200,
        },
      })
        .then((data) => {
          if (!alive) return;
          setBooks(Array.isArray(data.books) ? data.books : []);
          setSubjects(Array.isArray(data.subjects) ? data.subjects : []);
          setError("");
        })
        .catch((err) => {
          if (alive) setError(errorMessage(err));
        })
        .finally(() => {
          if (!alive) return;
          setLoading(false);
          setBusy(false);
        });
    }, 300);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query, subject, attempt]);

  const hasFilter = Boolean(query.trim() || subject);

  return (
    <div className="stack">
      {error ? (
        <div className="error-box">
          {error}{" "}
          <button className="btn sm" onClick={() => setAttempt((n) => n + 1)}>
            إعادة المحاولة
          </button>
        </div>
      ) : null}

      <div className="card">
        <div className="card-title">
          <h3>كتب المنهج</h3>
          <span className="small muted">{books.length} كتاب</span>
        </div>
        <div className="field">
          <input
            className="input"
            placeholder="ابحث عن كتاب أو مادة…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="row wrap">
          <button className={`chip${subject === "" ? " on" : ""}`} onClick={() => setSubject("")}>
            الكل
          </button>
          {subjects.map((s) => (
            <button
              key={s.id}
              className={`chip${subject === s.id ? " on" : ""}`}
              onClick={() => setSubject(s.id)}
            >
              {s.name}
              {s.recommended ? " ⭐" : ""}
            </button>
          ))}
        </div>
      </div>

      {loading ? <div className="empty">جاري تحميل الكتب…</div> : null}

      {!loading && busy && books.length ? (
        <div className="small muted">جاري البحث…</div>
      ) : null}

      {!loading && !error && books.length ? (
        <div className="grid cols-3">
          {books.map((book) => (
            <BookCard key={book.id} book={book} />
          ))}
        </div>
      ) : null}

      {!loading && !error && !books.length ? (
        <div className="empty">
          {hasFilter
            ? "ما لقينا كتاب بهالمواصفات — جرّب كلمة ثانية أو اضغط «الكل»."
            : "ما في كتب متاحة حالياً."}
        </div>
      ) : null}
    </div>
  );
}

function BookCard({ book }) {
  const percent = book.progress ? book.progress.percent || 0 : 0;
  const lastPage = book.progress ? book.progress.last_page || 1 : 1;
  const resume = lastPage > 1;
  const href = `/books/${book.id}${resume ? `?page=${lastPage}` : ""}`;
  const where = [book.grade, book.branch].filter(Boolean).join(" · ");
  // ingested PDFs have pages but no chapter map — "0 فصل" reads as a bug
  const hasChapters = (book.chapter_count || 0) > 0;

  return (
    <Link className="book-card card" href={href}>
      <div className="book-cover" style={{ "--cover": book.subject_color || "#2f8ff7" }}>
        <span className="book-subject">{book.subject || "الكتاب"}</span>
        <strong className="book-title">{book.title}</strong>
        <span className="book-edition small">{book.edition || ""}</span>
      </div>
      <div className="book-body">
        <div className="row wrap small muted">
          {where ? <span>{where}</span> : null}
          {where && hasChapters ? <span>·</span> : null}
          {hasChapters ? <span>{book.chapter_count} فصل</span> : null}
          {hasChapters ? <span>·</span> : null}
          <span>{book.page_count} صفحة</span>
          {book.recommended ? <span className="tag ok">موادك</span> : null}
          {book.is_demo ? <span className="tag demo">تجريبي</span> : null}
        </div>
        <div className="bar" style={{ marginTop: 8 }}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <div className="row between small" style={{ marginTop: 6 }}>
          <span className="muted">{resume ? `آخر قراءة: صفحة ${lastPage}` : "ابدأ القراءة"}</span>
          <strong style={{ color: "var(--primary)" }}>{percent}%</strong>
        </div>
      </div>
    </Link>
  );
}
