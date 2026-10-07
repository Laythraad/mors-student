"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

export default function PapersPage() {
  return (
    <Shell title="أوراق">
      <PapersBody />
    </Shell>
  );
}

function PapersBody() {
  const [papers, setPapers] = useState([]);
  const [lessons, setLessons] = useState([]);
  const [open, setOpen] = useState(null);
  const [lessonId, setLessonId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api("/api/curriculum/next-lessons", { query: { limit: 20 } })
      .then((d) => setLessons(d.lessons || []))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await api("/api/library/papers");
      setPapers(data.papers || []);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function generate() {
    setBusy(true);
    try {
      const data = await api("/api/library/papers/generate", {
        method: "POST",
        body: { lesson_id: lessonId || null, kind: "worksheet", use_ai: false },
      });
      setNotice("أُنشئت ورقة العمل.");
      await load();
      setOpen(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function openPaper(id) {
    try {
      const data = await api(`/api/library/papers/${id}`);
      setOpen(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="card">
        <div className="card-title">
          <h3>ورقة عمل</h3>
          <Link className="btn ghost sm" href="/notes">
            ملاحظاتي
          </Link>
        </div>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 200, marginBottom: 0 }}>
            <label>اختر درساً (اختياري)</label>
            <select className="select" value={lessonId} onChange={(e) => setLessonId(e.target.value)}>
              <option value="">— اختر درساً —</option>
              {lessons.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.title}
                </option>
              ))}
            </select>
          </div>
          <button className="btn" disabled={busy} onClick={generate}>
            {busy ? "جاري الإنشاء…" : "أنشئ ورقة عمل"}
          </button>
        </div>
      </div>

      <div className="list">
        {papers.map((p) => (
          <div className="list-item" key={p.id}>
            <div className="grow">
              <div className="title ellip">
                {p.emoji || "📄"} {p.title}
              </div>
              <div className="small muted">
                {p.kind} · {p.page_count || 1} صفحة
              </div>
            </div>
            <button className="btn sm soft" onClick={() => openPaper(p.id)}>
              فتح
            </button>
          </div>
        ))}
        {!papers.length ? <div className="empty">لا أوراق عمل بعد.</div> : null}
      </div>

      {open ? (
        <div className="card">
          <div className="card-title">
            <h3>{open.title}</h3>
            <button className="btn ghost sm" onClick={() => setOpen(null)}>
              إغلاق
            </button>
          </div>
          {(open.pages || []).map((page) => (
            <div className="paper-canvas" key={page.id} style={{ marginBottom: 10 }}>
              {(page.blocks || []).length ? (
                page.blocks.map((block, i) => (
                  <div className="paper-block" key={block.id || i}>
                    {block.type === "heading" ? (
                      <strong>{(block.content && block.content.text) || ""}</strong>
                    ) : block.type === "text" ? (
                      <span>{(block.content && block.content.text) || ""}</span>
                    ) : block.type === "question" ? (
                      <span>❓ {(block.content && block.content.text) || ""}</span>
                    ) : block.type === "list" ? (
                      <ul>
                        {((block.content && block.content.items) || []).map((it, k) => (
                          <li key={k}>{it}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className="muted small">{JSON.stringify(block.content)}</span>
                    )}
                  </div>
                ))
              ) : (
                <div className="empty">صفحة فارغة</div>
              )}
            </div>
          ))}
          <Link className="btn ghost sm" href="/plan">
            ارجع لخطتك
          </Link>
        </div>
      ) : null}
    </div>
  );
}
