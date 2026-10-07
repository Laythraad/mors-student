"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Shell from "@/components/Shell";
import Provenance from "@/components/Provenance";
import { api, errorMessage, fmtTime } from "@/lib/api";

const BANDS = {
  no_data: "لا توجد بيانات",
  weak: "تحتاج تأسيساً",
  not_ready: "لست جاهزاً بعد",
  ready_with_work: "جاهز بشرط",
  ready: "جاهز",
};

export default function ExamPage() {
  return (
    <Shell title="محاكاة امتحان">
      <ExamBody />
    </Shell>
  );
}

function ExamBody() {
  const { attemptId } = useParams();
  const router = useRouter();
  const [session, setSession] = useState(null);
  const [index, setIndex] = useState(0);
  const [left, setLeft] = useState(null);
  const [answered, setAnswered] = useState({});
  const [marked, setMarked] = useState([]);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const expiredOnce = useRef(false);

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/exams/attempts/${attemptId}`);
      setSession(data);
      setAnswered(data.answered || {});
      setMarked(data.marked || []);
      setIndex(Math.min(data.current_index || 0, Math.max(0, (data.questions || []).length - 1)));
      setLeft(data.time_left_seconds);
      if (data.status !== "in_progress" && data.report && data.report.accuracy !== undefined) {
        setReport(data.report);
      }
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [attemptId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (left === null || report) return undefined;
    const timer = setInterval(() => {
      setLeft((prev) => {
        if (prev === null || prev === undefined) return prev;
        if (prev <= 1) {
          if (!expiredOnce.current) {
            expiredOnce.current = true;
            api(`/api/exams/attempts/${attemptId}`)
              .then((data) => {
                setSession(data);
                setAnswered(data.answered || {});
                if (data.report && data.report.accuracy !== undefined) setReport(data.report);
              })
              .catch((err) => setError(errorMessage(err)));
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [left === null, report, attemptId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function pick(optionId) {
    if (!session || report || busy) return;
    const question = session.questions[index];
    setBusy(true);
    setError("");
    try {
      await api(`/api/exams/attempts/${attemptId}/answer`, {
        method: "POST",
        body: { question_id: question.id, answer: optionId, time_seconds: 15 },
      });
      setAnswered((prev) => ({ ...prev, [question.id]: optionId }));
      setSaved(question.id);
      setTimeout(() => setSaved(""), 2400);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleMark() {
    if (!session || report) return;
    const question = session.questions[index];
    try {
      const result = await api(`/api/exams/attempts/${attemptId}/mark`, {
        method: "POST",
        body: { question_id: question.id },
      });
      setMarked(result.marked || []);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function finish() {
    if (busy) return;
    const remaining = session.questions.length - Object.keys(answered).length;
    const warning = remaining
      ? `لم تُجب ${remaining} سؤالاً. إرسال نهائي يقفل الامتحان. متابعة؟`
      : "إرسال نهائي يقفل الامتحان ولن تتمكن من التعديل. متابعة؟";
    if (!window.confirm(warning)) return;
    setBusy(true);
    setError("");
    try {
      const analysis = await api(`/api/exams/attempts/${attemptId}/submit`, { method: "POST" });
      setReport(analysis);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (error && !session) return <div className="error-box">{error}</div>;
  if (!session)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  if (report) return <Analysis report={report} onAgain={() => router.push("/exams")} />;

  const questions = session.questions || [];
  const question = questions[index];
  const total = questions.length;
  const low = left !== null && left <= 60;

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      <div className="card exam-head">
        <div className="row between">
          <div>
            <strong>{session.title || "امتحان"}</strong>
            <div className="small muted">
              {session.mode === "mock" ? "محاكاة" : "تدريب"} · {session.answered_count || 0} من {total}
              {session.overtime ? " · انتهى الوقت" : ""}
            </div>
          </div>
          <div className={`exam-timer ${low ? "low" : ""}`} aria-live="polite">
            {fmtTime(left)}
          </div>
        </div>
        <div className="bar" style={{ marginTop: 10 }}>
          <span style={{ width: `${(Object.keys(answered).length / total) * 100}%` }} />
        </div>
      </div>

      <div className="exam-grid">
        {questions.map((q, i) => (
          <button
            key={q.id}
            className={`exam-nav-btn ${i === index ? "on" : ""} ${answered[q.id] ? "done" : ""} ${
              marked.includes(q.id) ? "marked" : ""
            }`}
            onClick={() => setIndex(i)}
            aria-label={`السؤال ${i + 1}`}
          >
            {i + 1}
          </button>
        ))}
      </div>

      {question ? (
        <div className="card">
          <div className="card-title">
            <span className="tag">السؤال {index + 1} / {total}</span>
            <button className="chip" onClick={toggleMark}>
              {marked.includes(question.id) ? "📌 مُعلَّم للمراجعة" : "علّم للمراجعة"}
            </button>
          </div>

          <p style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>{question.prompt}</p>
          <Provenance provenance={question.provenance} style={{ marginBottom: 12 }} />

          <div className="stack">
            {(question.options || []).map((option) => {
              const state = answered[question.id] === option.id ? "selected" : "";
              return (
                <button
                  key={option.id}
                  className={`option ${state}`}
                  disabled={busy || !!answered[question.id]}
                  onClick={() => pick(option.id)}
                >
                  <span>{option.text}</span>
                  {answered[question.id] === option.id ? <span className="tag">مُحفوظة</span> : null}
                </button>
              );
            })}
          </div>

          {saved === question.id ? (
            <div className="success-box" style={{ marginTop: 10 }}>
              تم حفظ إجابتك — التقييم يظهر بعد الإرسال النهائي.
            </div>
          ) : answered[question.id] ? (
            <div className="small muted" style={{ marginTop: 8 }}>
              أجبت عن هذا السؤال — يمكنك التراجع بإجابة أخرى قبل الإرسال النهائي.
            </div>
          ) : null}

          <div className="row between" style={{ marginTop: 14 }}>
            <button className="btn ghost sm" disabled={index === 0} onClick={() => setIndex(index - 1)}>
              السابق
            </button>
            <button
              className="btn ghost sm"
              disabled={index === total - 1}
              onClick={() => setIndex(index + 1)}
            >
              التالي
            </button>
          </div>
        </div>
      ) : null}

      <button className="btn" style={{ width: "100%" }} disabled={busy} onClick={finish}>
        {busy ? "جاري الإرسال…" : "إنهاء وإرسال الامتحان"}
      </button>

      <p className="small muted" style={{ textAlign: "center" }}>
        المؤقّت يُحسب من الخادم — عند انتهاء الوقت يُرسل تلقائياً بكل ما أجبت عنه.
      </p>
    </div>
  );
}

function Analysis({ report, onAgain }) {
  const accuracy = report.accuracy || 0;
  const readiness = report.readiness || {};
  const difficulties = Object.entries(report.by_difficulty || {}).filter(
    ([, bucket]) => bucket.total > 0
  );

  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h2>{accuracy >= 70 ? "أداء جيد 🎯" : "تحتاج مراجعة 💪"}</h2>
          <span className="tag">{accuracy}%</span>
        </div>
        <div className="small muted">{report.title}</div>

        <div className="grid cols-3" style={{ marginTop: 12 }}>
          <div className="stat">
            <div className="value">{report.correct}</div>
            <div className="label">صحيحة</div>
          </div>
          <div className="stat">
            <div className="value">{report.wrong}</div>
            <div className="label">خاطئة</div>
          </div>
          <div className="stat">
            <div className="value">{report.skipped}</div>
            <div className="label">متروكة</div>
          </div>
        </div>

        <div className="bar" style={{ marginTop: 14 }}>
          <span style={{ width: `${accuracy}%` }} />
        </div>

        <div className="row wrap" style={{ marginTop: 12 }}>
          <span className="chip">الوقت: {fmtTime(report.time_seconds)}</span>
          {report.time_limit_seconds ? (
            <span className="chip">الحد: {fmtTime(report.time_limit_seconds)}</span>
          ) : null}
          {report.overtime ? <span className="chip">انتهى الوقت</span> : null}
          {report.previous_accuracy !== null && report.previous_accuracy !== undefined ? (
            <span className="chip">
              {report.delta >= 0 ? "▲" : "▼"} {Math.abs(report.delta)} عن سابقتك
            </span>
          ) : null}
          {report.new_mistakes ? (
            <span className="chip">+{report.new_mistakes} في دفتر الأخطاء</span>
          ) : null}
        </div>
      </div>

      {difficulties.length ? (
        <div className="card">
          <div className="card-title">
            <h3>حسب مستوى الصعوبة</h3>
          </div>
          <div className="list">
            {difficulties.map(([level, bucket]) => {
              const percent = Math.round((bucket.correct / bucket.total) * 100);
              return (
                <div className="list-item" key={level}>
                  <div className="grow">
                    <div className="title">مستوى {level}</div>
                    <div className="bar" style={{ marginTop: 6 }}>
                      <span style={{ width: `${percent}%` }} />
                    </div>
                  </div>
                  <span className="tag">
                    {bucket.correct}/{bucket.total}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {report.recommendations?.length ? (
        <div className="card">
          <div className="card-title">
            <h3>خطوتك التالية</h3>
          </div>
          <div className="list">
            {report.recommendations.map((rec, i) => (
              <div className="list-item" key={i}>
                <div className="grow">
                  <div className="title">{rec.topic}</div>
                  <div className="small muted">{rec.hint}</div>
                </div>
                {rec.lesson_id ? (
                  <Link className="btn ghost sm" href={`/lessons/${rec.lesson_id}`}>
                    افتح الدرس
                  </Link>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {report.mistakes?.length ? (
        <div className="card">
          <div className="card-title">
            <h3>مراجعة الأخطاء</h3>
            <span className="tag warn">{report.mistakes.length}</span>
          </div>
          <div className="list">
            {report.mistakes.map((row, i) => (
              <div className="list-item" key={i} style={{ display: "block" }}>
                <div className="title">{row.prompt}</div>
                <div className="small" style={{ color: "var(--danger)" }}>
                  {row.reason === "skipped" ? "لم تُجب" : `إجابتك: ${row.given || "(فارغة)"}`}
                  {row.correct ? ` · الصحيحة: ${row.correct}` : ""}
                </div>
                {row.explanation ? <div className="small muted">{row.explanation}</div> : null}
                <div className="row wrap" style={{ gap: 6, marginTop: 4 }}>
                  {row.topic ? <span className="tag">{row.topic}</span> : null}
                  <Provenance provenance={row.provenance} />
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {readiness.message ? (
        <div className="card">
          <div className="card-title">
            <h3>استعدادك {readiness.score === null ? "" : `(${Math.round(readiness.score)}%)`}</h3>
            <span className="tag">{BANDS[readiness.band] || readiness.band}</span>
          </div>
          <p className="small">{readiness.message}</p>
          {readiness.next_steps?.length ? (
            <ul className="readiness-steps">
              {readiness.next_steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="row wrap">
        <button className="btn" onClick={onAgain}>
          العودة للامتحانات
        </button>
        <Link className="btn ghost" href="/exams">
          دفتر أخطائي
        </Link>
        <Link className="btn ghost" href="/progress">
          تقرير تقدّمي
        </Link>
      </div>
    </div>
  );
}
