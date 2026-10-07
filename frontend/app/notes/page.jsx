"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtShortDate } from "@/lib/api";

const TABS = [
  { key: "notes", label: "ملاحظاتي" },
  { key: "summaries", label: "ملخصات" },
  { key: "cards", label: "بطاقات" },
];

export default function NotesPage() {
  return (
    <Shell title="ملاحظاتي">
      <NotesBody />
    </Shell>
  );
}

function NotesBody() {
  const [tab, setTab] = useState("notes");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [lessons, setLessons] = useState([]);

  useEffect(() => {
    api("/api/curriculum/next-lessons", { query: { limit: 20 } })
      .then((data) => setLessons(data.lessons || []))
      .catch(() => setLessons([]));
  }, []);

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "notes" ? <NotesTab onError={setError} onNotice={setNotice} /> : null}
      {tab === "summaries" ? (
        <SummariesTab lessons={lessons} onError={setError} onNotice={setNotice} />
      ) : null}
      {tab === "cards" ? <CardsTab onError={setError} /> : null}
    </div>
  );
}

function NotesTab({ onError, onNotice }) {
  const [notes, setNotes] = useState([]);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ title: "", body: "" });
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api("/api/library/notes", { query: { q: query } });
      setNotes(data.notes || []);
    } catch (err) {
      onError(errorMessage(err));
    }
  }, [query, onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function save(e) {
    e.preventDefault();
    try {
      if (editing) {
        await api(`/api/library/notes/${editing}`, { method: "PATCH", body: form });
      } else {
        await api("/api/library/notes", { method: "POST", body: form });
      }
      setForm({ title: "", body: "" });
      setEditing(null);
      onNotice("حُفظت الملاحظة.");
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  async function remove(id) {
    try {
      await api(`/api/library/notes/${id}`, { method: "DELETE" });
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <form onSubmit={save}>
          <div className="field">
            <label>{editing ? "تعديل الملاحظة" : "ملاحظة جديدة"}</label>
            <input
              className="input"
              placeholder="العنوان"
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </div>
          <div className="field">
            <textarea
              className="textarea"
              placeholder="اكتب ما تريد — أفكار، خطط، ملاحظات…"
              required
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
            />
          </div>
          <div className="row">
            <button className="btn">{editing ? "حفظ التعديل" : "إضافة"}</button>
            {editing ? (
              <button
                type="button"
                className="btn ghost"
                onClick={() => {
                  setEditing(null);
                  setForm({ title: "", body: "" });
                }}
              >
                إلغاء
              </button>
            ) : null}
          </div>
        </form>
      </div>

      <div className="card">
        <div className="field">
          <input
            className="input"
            placeholder="ابحث في ملاحظاتك…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="list">
          {notes.map((note) => (
            <div className="list-item" key={note.id} style={{ display: "block" }}>
              <div className="row between">
                <div className="title ellip">{note.title}</div>
                <span className="row">
                  <button
                    className="btn ghost sm"
                    onClick={() => {
                      setEditing(note.id);
                      setForm({ title: note.title, body: note.body });
                    }}
                  >
                    ✏️
                  </button>
                  <button className="btn ghost sm" onClick={() => remove(note.id)}>
                    🗑
                  </button>
                </span>
              </div>
              <div className="small muted ellip">{note.body}</div>
              <div className="small muted">{fmtShortDate(note.updated_at)}</div>
            </div>
          ))}
          {!notes.length ? <div className="empty">لا ملاحظات بعد.</div> : null}
        </div>
      </div>
    </div>
  );
}

function SummariesTab({ lessons, onError, onNotice }) {
  const [summaries, setSummaries] = useState([]);
  const [lessonId, setLessonId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api("/api/library/summaries");
      setSummaries(data.summaries || []);
    } catch (err) {
      onError(errorMessage(err));
    }
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    if (!lessonId) return;
    setBusy(true);
    try {
      await api("/api/library/summaries", {
        method: "POST",
        body: { lesson_id: lessonId, kind: "quick", use_ai: false },
      });
      onNotice("تم إنشاء الملخص.");
      load();
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>ملخص درس</h3>
        </div>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 200, marginBottom: 0 }}>
            <label>اختر درساً</label>
            <select className="select" value={lessonId} onChange={(e) => setLessonId(e.target.value)}>
              <option value="">—</option>
              {lessons.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.title} ({l.subject})
                </option>
              ))}
            </select>
          </div>
          <button className="btn" disabled={!lessonId || busy} onClick={create}>
            أنشئ الملخص
          </button>
        </div>
      </div>

      {summaries.map((s) => (
        <div className="card" key={s.id}>
          <div className="card-title">
            <h3>{s.title}</h3>
            <span className="tag">{s.kind}</span>
          </div>
          <div style={{ whiteSpace: "pre-wrap" }}>{s.body}</div>
        </div>
      ))}
      {!summaries.length ? <div className="empty">لا ملخصات بعد.</div> : null}
    </div>
  );
}

function CardsTab({ onError }) {
  const [cards, setCards] = useState([]);
  const [flipped, setFlipped] = useState(false);
  const [index, setIndex] = useState(0);
  const [lessonId, setLessonId] = useState("");
  const [lessons, setLessons] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/curriculum/next-lessons", { query: { limit: 20 } })
      .then((d) => setLessons(d.lessons || []))
      .catch(() => {});
    api("/api/library/flashcards/due")
      .then((d) => setCards(d.cards || []))
      .catch(() => {});
  }, []);

  async function generate() {
    if (!lessonId) return;
    setBusy(true);
    try {
      const data = await api("/api/library/flashcards/generate", {
        method: "POST",
        body: { lesson_id: lessonId, count: 8, use_ai: false },
      });
      setCards(data.cards || []);
      setIndex(0);
      setFlipped(false);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function review(quality) {
    const card = cards[index];
    if (!card) return;
    try {
      await api(`/api/library/flashcards/${card.id}/review`, {
        method: "POST",
        body: { quality },
      });
      setFlipped(false);
      setIndex((i) => (i + 1) % cards.length);
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  const card = cards[index];

  return (
    <div className="stack">
      <div className="card">
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 200, marginBottom: 0 }}>
            <label>ولّد بطاقات من درس</label>
            <select className="select" value={lessonId} onChange={(e) => setLessonId(e.target.value)}>
              <option value="">—</option>
              {lessons.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.title}
                </option>
              ))}
            </select>
          </div>
          <button className="btn" disabled={!lessonId || busy} onClick={generate}>
            توليد
          </button>
        </div>
      </div>

      {card ? (
        <div className="card" style={{ textAlign: "center" }}>
          <div className="tag">
            {index + 1} / {cards.length}
          </div>
          <div
            onClick={() => setFlipped((v) => !v)}
            style={{
              minHeight: 160,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
              fontWeight: 700,
              cursor: "pointer",
              padding: 16,
            }}
          >
            {flipped ? card.back : card.front}
          </div>
          <div className="muted small">اضغط البطاقة للقلب</div>
          {flipped ? (
            <div className="row" style={{ justifyContent: "center", marginTop: 12 }}>
              <button className="btn danger sm" onClick={() => review(1)}>
                نسيتها
              </button>
              <button className="btn ghost sm" onClick={() => review(3)}>
                صعبة
              </button>
              <button className="btn sm" onClick={() => review(5)}>
                سهلة
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="empty">لا بطاقات مستحقة — ولّد بطاقات من درس.</div>
      )}
    </div>
  );
}
