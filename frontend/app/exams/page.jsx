"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import Provenance from "@/components/Provenance";
import { api, errorMessage, fmtDate } from "@/lib/api";

const BANDS = {
  no_data: "لا توجد بيانات",
  weak: "تحتاج تأسيساً",
  not_ready: "لست جاهزاً بعد",
  ready_with_work: "جاهز بشرط",
  ready: "جاهز",
};

const DIFFICULTIES = [
  { value: 2, label: "سهل" },
  { value: 3, label: "متوسط" },
  { value: 4, label: "صعب" },
];

const DURATIONS = [15, 30, 45, 60];
const SIZES = [10, 20, 30];

export default function ExamsPage() {
  return (
    <Shell title="الامتحانات">
      <ExamsBody />
    </Shell>
  );
}

function ExamsBody() {
  const router = useRouter();
  const [home, setHome] = useState(null);
  const [mistakes, setMistakes] = useState({ total: 0, items: [] });
  const [tab, setTab] = useState("readiness");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ subject_id: "", count: 20, difficulty: 3, duration_minutes: 30 });

  const load = useCallback(async () => {
    try {
      const data = await api("/api/exams");
      setHome(data);
      setForm((prev) => ({ ...prev, subject_id: prev.subject_id || data.subjects?.[0]?.id || "" }));
      const book = await api("/api/exams/mistakes");
      setMistakes(book);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function startExam() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const quiz = await api("/api/exams/generate", { method: "POST", body: form });
      const session = await api("/api/exams/start", {
        method: "POST",
        body: { quiz_id: quiz.id, mode: "mock" },
      });
      router.push(`/exam/${session.exam_attempt_id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function resolve(mistakeId) {
    try {
      await api(`/api/exams/mistakes/${mistakeId}/resolve`, { method: "POST" });
      setNotice("أضفنا الخطأ إلى المُنجز — راجعه بعد يومين للتأكد.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (error && !home) return <div className="error-box">{error}</div>;
  if (!home)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  const overall = home.readiness_overall;

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="tabs">
        <button className={tab === "readiness" ? "on" : ""} onClick={() => setTab("readiness")}>
          استعدادي
        </button>
        <button className={tab === "new" ? "on" : ""} onClick={() => setTab("new")}>
          امتحان جديد
        </button>
        <button className={tab === "mistakes" ? "on" : ""} onClick={() => setTab("mistakes")}>
          دفتر أخطائي{home.mistakes_count ? ` (${home.mistakes_count})` : ""}
        </button>
      </div>

      {home.active_attempt ? (
        <div className="card exam-resume">
          <div className="card-title">
            <h3>لديك امتحان جارٍ: {home.active_attempt.title}</h3>
            <span className="tag warn">متبقٍ {formatLeft(home.active_attempt.time_left_seconds)}</span>
          </div>
          <Link className="btn" href={`/exam/${home.active_attempt.exam_attempt_id}`}>
            أكمل الامتحان
          </Link>
        </div>
      ) : null}

      {tab === "readiness" ? (
        <ReadinessTab home={home} />
      ) : tab === "new" ? (
        <NewExamTab form={form} setForm={setForm} home={home} busy={busy} onStart={startExam} />
      ) : (
        <MistakesTab mistakes={mistakes} onResolve={resolve} />
      )}

      <div className="small muted" style={{ textAlign: "center" }}>
        بنك الأسئلة: {home.bank?.total || 0} سؤالاً مُتحقَّقاً منها · {home.bank?.published || 0} جاهزاً للاستخدام
      </div>
    </div>
  );
}

function ReadinessTab({ home }) {
  const overall = home.readiness_overall;
  const score = overall.score;
  const pct = typeof score === "number" ? Math.max(0, Math.min(100, score)) : 0;

  return (
    <div className="stack">
      <div className="card readiness-card">
        <div className="row" style={{ gap: 18, alignItems: "center" }}>
          <div
            className="readiness-ring"
            style={{
              background: `conic-gradient(var(--primary) ${pct}%, var(--surface-2) 0deg)`,
            }}
          >
            <div className="readiness-inner">
              <div className="readiness-value">{score === null ? "—" : Math.round(pct)}</div>
              <div className="readiness-band">{BANDS[overall.band] || overall.band}</div>
            </div>
          </div>
          <div className="grow">
            <p style={{ fontWeight: 700, marginBottom: 6 }}>{overall.message}</p>
            {overall.next_steps?.length ? (
              <ul className="readiness-steps">
                {overall.next_steps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ul>
            ) : null}
            <div className="small muted">مبني على {overall.data_points} محاولة مُقيَّمة — بلا مبالغة.</div>
          </div>
        </div>

        <div className="factors">
          {overall.factors.map((factor) => (
            <div className="factor" key={factor.key}>
              <div className="row between">
                <span className="small">{factor.label}</span>
                <span className="small muted">
                  {factor.score === null ? "لا بيانات" : `${Math.round(factor.score)}%`}
                </span>
              </div>
              <div className="bar">
                <span style={{ width: `${factor.score === null ? 0 : factor.score}%` }} />
              </div>
              <div className="small muted">{factor.detail}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>امتحاناتي القادمة</h3>
        </div>
        {home.upcoming.length ? (
          <div className="list">
            {home.upcoming.map((exam) => (
              <div className="list-item" key={exam.id}>
                <div className="grow">
                  <div className="title">{exam.title}</div>
                  <div className="small muted">
                    {fmtDate(exam.exam_date)} · {exam.duration_minutes} دقيقة
                    {exam.topics?.length ? ` · ${exam.topics.slice(0, 2).join("، ")}` : ""}
                  </div>
                </div>
                <span className={`tag ${exam.days_left <= 3 ? "warn" : ""}`}>
                  {exam.days_left === null ? "" : exam.days_left <= 0 ? "اليوم" : `بعد ${exam.days_left} يوم`}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="small muted">
            لا توجد امتحانات مجدولة — أضِفها من <Link href="/plan">خطتي</Link> ليعمل العدّ التنازلي.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>محاكاة سابقة</h3>
        </div>
        {home.recent.length ? (
          <div className="list">
            {home.recent.map((row) => (
              <Link href={`/exam/${row.exam_attempt_id}`} className="list-item" key={row.exam_attempt_id}>
                <div className="grow">
                  <div className="title">{row.title || "امتحان"}</div>
                  <div className="small muted">
                    {row.finished_at ? fmtDate(row.finished_at) : ""}
                    {row.overtime ? " · انتهى الوقت" : ""}
                  </div>
                </div>
                <span className="tag">{row.accuracy === null ? "—" : `${row.accuracy}%`}</span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="small muted">ما حللت امتحاناً محاكياً بعد — ابدأ واحداً لتظهر نتائجك هنا.</p>
        )}
      </div>

      {home.subjects.length ? (
        <div className="card">
          <div className="card-title">
            <h3>الاستعداد حسب المادة</h3>
          </div>
          <div className="list">
            {home.subjects.map((row) => (
              <div className="list-item" key={row.id}>
                <div className="grow">
                  <div className="title">{row.name_ar}</div>
                  <div className="bar" style={{ marginTop: 6 }}>
                    <span
                      style={{
                        width: `${row.readiness.score === null ? 0 : row.readiness.score}%`,
                      }}
                    />
                  </div>
                </div>
                <span className="tag">
                  {row.readiness.score === null ? "—" : `${Math.round(row.readiness.score)}%`}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NewExamTab({ form, setForm, home, busy, onStart }) {
  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>محاكاة امتحان جديد</h3>
          <span className="tag">تقييم يظهر بعد الإرسال</span>
        </div>

        <label className="small muted">المادة</label>
        <select
          className="input"
          value={form.subject_id}
          onChange={(e) => setForm({ ...form, subject_id: e.target.value })}
        >
          {home.subjects.map((subject) => (
            <option key={subject.id} value={subject.id}>
              {subject.name_ar}
            </option>
          ))}
        </select>

        <label className="small muted">عدد الأسئلة</label>
        <div className="row wrap">
          {SIZES.map((size) => (
            <button
              key={size}
              className={`chip ${form.count === size ? "on" : ""}`}
              onClick={() => setForm({ ...form, count: size })}
            >
              {size} سؤالاً
            </button>
          ))}
        </div>

        <label className="small muted">الصعوبة</label>
        <div className="row wrap">
          {DIFFICULTIES.map((level) => (
            <button
              key={level.value}
              className={`chip ${form.difficulty === level.value ? "on" : ""}`}
              onClick={() => setForm({ ...form, difficulty: level.value })}
            >
              {level.label}
            </button>
          ))}
        </div>

        <label className="small muted">المدة (دقيقة)</label>
        <div className="row wrap">
          {DURATIONS.map((minutes) => (
            <button
              key={minutes}
              className={`chip ${form.duration_minutes === minutes ? "on" : ""}`}
              onClick={() => setForm({ ...form, duration_minutes: minutes })}
            >
              {minutes}
            </button>
          ))}
        </div>

        <p className="small muted">
          الأسئلة تُسحب من بنك الأسئلة ثم تُبنى من المنهج — مستوى الصعوبة يُضبط حسب نتائجك الأخيرة،
          والمؤقّت يعمل من لحظة البدء ويرسل تلقائياً عند انتهاء الوقت.
        </p>

        <button className="btn" disabled={busy} onClick={onStart} style={{ width: "100%" }}>
          {busy ? "جاري بناء الامتحان…" : "ابدأ المحاكاة"}
        </button>
      </div>
    </div>
  );
}

function MistakesTab({ mistakes, onResolve }) {
  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>دفتر الأخطاء</h3>
          <span className="tag">{mistakes.total} خطأ نشط</span>
        </div>
        {mistakes.items.length ? (
          <div className="list">
            {mistakes.items.map((row) => (
              <div className="list-item" key={row.id} style={{ display: "block" }}>
                <div className="title">{row.prompt}</div>
                <div className="small" style={{ color: "var(--danger)" }}>
                  إجابتك: {row.student_answer || "(متروكة)"} · الصحيحة: {row.correct_answer || "—"}
                </div>
                {row.explanation ? <div className="small muted">{row.explanation}</div> : null}
                <div className="row between" style={{ marginTop: 8 }}>
                  <div className="row wrap" style={{ gap: 6 }}>
                    <span className="tag">{row.topic || (row.reason === "skipped" ? "متروك" : "خطأ")}</span>
                    <Provenance kind={row.source_kind} />
                  </div>
                  <button className="btn ghost sm" onClick={() => onResolve(row.id)}>
                    عالجتُه ✅
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="small muted">ما عندك أخطاء نشطة — علامات ممتازة. حافظ على المراجعات.</p>
        )}
      </div>
    </div>
  );
}

function formatLeft(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
