"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

export default function ProgressPage() {
  return (
    <Shell title="تقدّمي">
      <ProgressBody />
    </Shell>
  );
}

function ProgressBody() {
  const [report, setReport] = useState(null);
  const [week, setWeek] = useState(null);
  const [achievements, setAchievements] = useState([]);
  const [weak, setWeak] = useState([]);
  const [mastery, setMastery] = useState([]);
  const [actions, setActions] = useState([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, w, a, m, ac] = await Promise.all([
        api("/api/progress/report"),
        api("/api/progress/week"),
        api("/api/progress/achievements"),
        api("/api/progress/mastery"),
        api("/api/progress/coach/actions"),
      ]);
      setReport(r);
      setWeek(w);
      setAchievements(a.achievements || []);
      setMastery(m.mastery || []);
      setActions(ac.actions || []);
    } catch (err) {
      setError(errorMessage(err));
    }
    try {
      const weakData = await api("/api/progress/weak");
      setWeak(weakData.topics || []);
    } catch {
      setWeak([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function resolve(topic) {
    try {
      await api("/api/progress/weak/resolve", { method: "POST", body: { topic } });
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (error && !report) return <div className="error-box">{error}</div>;
  if (!report)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  const totals = report.totals || {};
  const streak = report.streak || {};

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      <div className="grid cols-3">
        <div className="stat">
          <div className="value">{totals.sessions || 0}</div>
          <div className="label">جلسات مكتملة</div>
        </div>
        <div className="stat">
          <div className="value">{totals.study_minutes || 0}</div>
          <div className="label">دقيقة دراسة</div>
        </div>
        <div className="stat">
          <div className="value">{streak.current || 0}</div>
          <div className="label">سلسلة الأيام 🔥</div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>هذا الأسبوع</h3>
        </div>
        <div className="grid cols-3">
          <div className="stat">
            <div className="value">{week ? week.sessions : 0}</div>
            <div className="label">جلسات</div>
          </div>
          <div className="stat">
            <div className="value">{week ? week.minutes : 0}</div>
            <div className="label">دقيقة</div>
          </div>
          <div className="stat">
            <div className="value">{week && week.average_accuracy != null ? `${week.average_accuracy}%` : "—"}</div>
            <div className="label">متوسط الاختبارات</div>
          </div>
        </div>
        {week ? (
          <div className="row wrap" style={{ marginTop: 10 }}>
            <span className="chip">الاتجاه: {week.trend === "up" ? "صاعد ⬆️" : week.trend === "down" ? "هابط ⬇️" : "مستقر ➡️"}</span>
            <span className="chip">أفضل نتيجة: {week.best}%</span>
          </div>
        ) : null}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>المواد</h3>
        </div>
        <div className="list">
          {(report.subjects || []).map((s) => (
            <div className="list-item" key={s.subject_id}>
              <div className="grow">
                <div className="title">{s.name_ar || s.subject_id}</div>
                <div className="small muted">{s.sessions} جلسات · {Math.round(s.seconds / 60)} دقيقة</div>
                <div className="bar" style={{ marginTop: 6 }}>
                  <span style={{ width: `${Math.min(100, (s.seconds / 3600) * 100)}%` }} />
                </div>
              </div>
            </div>
          ))}
          {!(report.subjects || []).length ? <div className="empty">لا بيانات بعد.</div> : null}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>نقاط الضعف النشطة</h3>
        </div>
        {weak.length ? (
          <div className="list">
            {weak.map((w) => (
              <div className="list-item" key={w.id}>
                <div className="grow">
                  <div className="title">{w.topic}</div>
                  <div className="small muted">{w.errors} أخطاء · شدة {w.severity}</div>
                </div>
                <button className="btn sm soft" onClick={() => resolve(w.topic)}>
                  أتقنتها
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">لا نقاط ضعف نشطة.</div>
        )}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>الإتقان حسب الدرس</h3>
        </div>
        <div className="list">
          {mastery.slice(0, 12).map((m, i) => (
            <div className="list-item" key={i}>
              <div className="grow">
                <div className="title ellip">{m.topic || m.lesson_id}</div>
                <div className="bar" style={{ marginTop: 6 }}>
                  <span
                    style={{
                      width: `${m.score}%`,
                      background: m.score >= 85 ? "var(--success)" : m.score >= 55 ? "var(--warning)" : "var(--danger)",
                    }}
                  />
                </div>
              </div>
              <strong>{Math.round(m.score)}%</strong>
            </div>
          ))}
          {!mastery.length ? <div className="empty">لا بيانات إتقان بعد.</div> : null}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>إنجازاتي</h3>
        </div>
        <div className="grid cols-3">
          {achievements.map((a) => (
            <div
              key={a.code}
              className="stat"
              style={{ opacity: a.earned_at ? 1 : 0.55 }}
              title={a.description}
            >
              <div style={{ fontSize: 24 }}>{a.icon}</div>
              <div className="label" style={{ fontWeight: 700, color: "var(--text)" }}>
                {a.name}
              </div>
              <div className="small muted">{Math.round(a.progress)}%</div>
              <div className="bar" style={{ marginTop: 6 }}>
                <span style={{ width: `${a.progress}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>خطوات موصى بها</h3>
        </div>
        <div className="list">
          {actions.map((a, i) => (
            <div className="list-item" key={i}>
              <div className="grow">
                <div className="title">{a.title}</div>
                <div className="small muted">{a.meta}</div>
              </div>
              <span className="tag">{a.kind}</span>
            </div>
          ))}
          {!actions.length ? <div className="empty">لا إجراءات حالياً.</div> : null}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>تصدير بياناتي</h3>
        </div>
        <div className="row wrap">
          <a className="btn ghost sm" href="/api/progress/export/json">
            JSON
          </a>
          <a className="btn ghost sm" href="/api/progress/export/ics">
            تقويم ICS
          </a>
          <a className="btn ghost sm" href="/api/progress/export/pdf">
            تقرير PDF
          </a>
        </div>
      </div>
    </div>
  );
}
