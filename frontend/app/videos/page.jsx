"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtDate } from "@/lib/api";

const STATUS_TAG = {
  completed: { label: "مكتمل", cls: "ok" },
  started: { label: "بدأ", cls: "warn" },
  watched: { label: "شاهدته", cls: "warn" },
  quiz_failed: { label: "أعد المحاولة", cls: "warn" },
  new: { label: "متاح", cls: "" },
};

export default function VideosPage() {
  return (
    <Shell title="الفيديوهات">
      <VideosBody />
    </Shell>
  );
}

function VideosBody() {
  const [teachers, setTeachers] = useState([]);
  const [courses, setCourses] = useState([]);
  const [videos, setVideos] = useState([]);
  const [current, setCurrent] = useState(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [t, c, v] = await Promise.all([
        api("/api/media/teachers"),
        api("/api/media/courses"),
        api("/api/media/videos"),
      ]);
      setTeachers(t.teachers || []);
      setCourses(c.courses || []);
      setVideos(v.videos || []);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let alive = true;
    api("/api/media/continue")
      .then((data) => {
        if (alive) setCurrent(data.video || null);
      })
      .catch(() => {
        /* continue watching is optional */
      });
    return () => {
      alive = false;
    };
  }, []);

  async function searchTranscripts() {
    if (!query.trim()) return;
    try {
      const data = await api("/api/media/videos-search", { query: { q: query } });
      setHits(data.results || []);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      {current ? (
        <div className="card continue-card">
          <div className="grow">
            <div className="small muted">متابعة المشاهدة</div>
            <div className="title">{current.title}</div>
            <div className="row" style={{ marginTop: 6 }}>
              <div className="bar grow">
                <span style={{ width: `${Math.round(current.progress?.percent || 0)}%` }} />
              </div>
              <span className="mono small">{Math.round(current.progress?.percent || 0)}%</span>
            </div>
            {current.course ? (
              <div className="small muted">كورس {current.course.title}</div>
            ) : null}
          </div>
          <Link className="btn" href={`/videos/${current.id}`}>
            {current.resume_from > 0 ? `تابع من ${Math.round(current.resume_from / 60)} د` : "افتح"}
          </Link>
        </div>
      ) : null}

      <div className="card">
        <div className="card-title">
          <h3>ابحث داخل تفريغ الفيديوهات</h3>
        </div>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <input
              className="input"
              placeholder="مثال: الفرق المشترك"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && searchTranscripts()}
            />
          </div>
          <button className="btn" onClick={searchTranscripts}>
            بحث
          </button>
        </div>
        {hits ? (
          <div className="list" style={{ marginTop: 10 }}>
            {hits.map((h, i) => (
              <Link className="list-item" key={i} href={`/videos/${h.video_id || h.id}`}>
                <div className="grow">
                  <div className="title">{h.title}</div>
                  <div className="small muted">{h.snippet || h.text}</div>
                </div>
                <span className="tag">فتح ↗</span>
              </Link>
            ))}
            {!hits.length ? <div className="empty">ما لقينا شي بهالمطلوب.</div> : null}
          </div>
        ) : null}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>معلّمون</h3>
        </div>
        <div className="grid cols-3">
          {teachers.map((t) => (
            <div className="stat" key={t.id}>
              <div style={{ fontWeight: 800 }}>{t.name}</div>
              <div className="small muted">{t.headline}</div>
              {t.subjects?.length ? (
                <div className="small muted">{t.subjects.join(" · ")}</div>
              ) : null}
              <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
                {t.rating ? <span className="chip">⭐ {t.rating}</span> : null}
                {t.level ? <span className="chip">{t.level}</span> : null}
                {t.duration_minutes ? (
                  <span className="chip">
                    {t.duration_minutes} د ×{t.lessons_count}
                  </span>
                ) : null}
                {t.is_demo ? (
                  <span className="tag warn">ديمو</span>
                ) : t.link_status === "official" && t.channel_url ? (
                  <a
                    className="tag ok"
                    href={t.channel_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    رابط رسمي موثّق ↗
                  </a>
                ) : t.link_status === "search" ? (
                  <a
                    className="tag"
                    href={t.search_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    اقتراح بحث فقط ↗
                  </a>
                ) : null}
              </div>
            </div>
          ))}
          {!teachers.length ? <div className="empty">ما عندنا معلمين بعد.</div> : null}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>دورات</h3>
        </div>
        <div className="stack">
          {courses.map((c) => (
            <Link className="list-item" key={c.id} href={`/courses/${c.id}`}>
              <div className="grow">
                <div className="title">📚 {c.title}</div>
                <div className="small muted">
                  {c.subject ? `${c.subject} · ` : ""}
                  {c.teacher ? `${c.teacher} · ` : ""}
                  {c.video_count || 0} فيديو
                  {c.duration_minutes ? ` · ${c.duration_minutes} د` : ""}
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <div className="bar grow">
                    <span style={{ width: `${Math.round(c.progress_percent || 0)}%` }} />
                  </div>
                  <span className="mono small">{Math.round(c.progress_percent || 0)}%</span>
                </div>
              </div>
              <span className="tag">فتح ↗</span>
            </Link>
          ))}
          {!courses.length ? <div className="empty">ما عندنا دورات بعد.</div> : null}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>كل الفيديوهات</h3>
          <span className="small muted">{fmtDate(new Date().toISOString())}</span>
        </div>
        <div className="list">
          {videos.map((v) => {
            const tag = STATUS_TAG[v.status] || STATUS_TAG.new;
            return (
              <Link className="list-item" key={v.id} href={`/videos/${v.id}`}>
                <div className="grow">
                  <div className="title ellip">▶ {v.title}</div>
                  <div className="small muted">
                    {Math.round((v.duration_seconds || 0) / 60)} دقيقة
                    {v.progress ? ` · شاهدت ${Math.round(v.progress.percent || 0)}%` : ""}
                  </div>
                </div>
                <span className={`tag ${tag.cls}`}>{tag.label}</span>
              </Link>
            );
          })}
          {!videos.length ? <div className="empty">لا فيديوهات بعد.</div> : null}
        </div>
      </div>
    </div>
  );
}
