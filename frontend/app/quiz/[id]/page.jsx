"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import Provenance from "@/components/Provenance";
import { api, errorMessage } from "@/lib/api";

export default function QuizPage() {
  return (
    <Shell title="اختبار">
      <QuizBody />
    </Shell>
  );
}

function QuizBody() {
  const { id } = useParams();
  const router = useRouter();
  const [quiz, setQuiz] = useState(null);
  const [attemptId, setAttemptId] = useState(null);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [picked, setPicked] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/quiz/${id}`);
      setQuiz(data);
      const started = await api(`/api/quiz/${id}/start`, { method: "POST" });
      setAttemptId(started.attempt_id);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !quiz) return <div className="error-box">{error}</div>;
  if (!quiz)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  if (report) return <QuizReport report={report} onRetry={() => router.push("/home")} />;

  const question = quiz.questions[index];
  const total = quiz.questions.length;
  const isLast = index === total - 1;

  async function submitAnswer(optionId) {
    setPicked(optionId);
    setBusy(true);
    try {
      const result = await api(`/api/quiz/attempts/${attemptId}/answer`, {
        method: "POST",
        body: { question_id: question.id, answer: optionId, time_seconds: 20 },
      });
      setAnswers((prev) => ({ ...prev, [question.id]: { optionId, correct: result.correct } }));
      await new Promise((r) => setTimeout(r, 450));
      setPicked(null);
      if (isLast) {
        const finished = await api(`/api/quiz/attempts/${attemptId}/finish`, { method: "POST" });
        setReport(finished);
      } else {
        setIndex((i) => i + 1);
      }
    } catch (err) {
      setError(errorMessage(err));
      setPicked(null);
    } finally {
      setBusy(false);
    }
  }

  const answered = answers[question.id];

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      <div className="card">
        <div className="card-title">
          <h3>{quiz.title || "اختبار"}</h3>
          <span className="tag">
            {index + 1} / {total}
          </span>
        </div>
        <div className="bar" style={{ marginBottom: 14 }}>
          <span style={{ width: `${((index + (answered ? 1 : 0)) / total) * 100}%` }} />
        </div>

        <p style={{ fontSize: 18, fontWeight: 700 }}>{question.prompt}</p>
        <Provenance provenance={question.provenance} style={{ margin: "6px 0 10px" }} />

        <div className="stack">
          {(question.options || []).map((option) => {
            const state = answered
              ? option.id === answered.optionId
                ? answered.correct
                  ? "correct"
                  : "wrong"
                : ""
              : picked === option.id
                ? "selected"
                : "";
            return (
              <button
                key={option.id}
                className={`option ${state}`}
                disabled={busy || !!answered}
                onClick={() => submitAnswer(option.id)}
              >
                <span>{option.text}</span>
              </button>
            );
          })}
        </div>

        {answered ? (
          <div className={answered.correct ? "success-box" : "error-box"} style={{ marginTop: 12 }}>
            {answered.correct ? "إجابة صحيحة 👏" : "ليست الصحيحة — راجع الشرح بعد الاختبار."}
          </div>
        ) : null}

        <div className="row between" style={{ marginTop: 12 }}>
          <button className="btn ghost sm" disabled={index === 0} onClick={() => setIndex((i) => i - 1)}>
            السابق
          </button>
          <span className="small muted">الأسئلة تُقيَّم فور الإجابة</span>
        </div>
      </div>
    </div>
  );
}

function MistakeFlag({ questionId }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("wrong_answer");
  const [detail, setDetail] = useState("");
  const [sent, setSent] = useState("");
  const [error, setError] = useState("");

  async function send() {
    setError("");
    try {
      const res = await api(`/api/quiz/questions/${questionId}/flag`, {
        method: "POST",
        body: { kind, detail },
      });
      setSent(res.message || "وصل البلاغ — يراجعه فريق المحتوى.");
      setOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (sent) return <div className="notice-box" style={{ marginTop: 6 }}>{sent}</div>;

  if (!open)
    return (
      <div style={{ marginTop: 6 }}>
        <button className="btn ghost sm" onClick={() => setOpen(true)}>
          🚩 إبلاغ عن السؤال
        </button>
      </div>
    );

  return (
    <div className="stack" style={{ marginTop: 6 }}>
      {error ? <div className="notice-box">{error}</div> : null}
      <select
        className="input"
        value={kind}
        onChange={(e) => setKind(e.target.value)}
        aria-label="سبب البلاغ"
      >
        <option value="wrong_answer">الإجابة المعتمَدة غير صحيحة</option>
        <option value="unclear">صياغة السؤال غير واضحة</option>
        <option value="bad_options">الخيارات غير مناسبة</option>
        <option value="other">سبب آخر</option>
      </select>
      <textarea
        className="input"
        rows={2}
        maxLength={500}
        placeholder="شرح مختصر (اختياري)"
        value={detail}
        onChange={(e) => setDetail(e.target.value)}
      />
      <div className="row wrap">
        <button className="btn sm" onClick={send}>
          أرسل البلاغ
        </button>
        <button className="btn ghost sm" onClick={() => setOpen(false)}>
          إلغاء
        </button>
      </div>
    </div>
  );
}


function QuizReport({ report, onRetry }) {
  const passed = report.accuracy >= 60;
  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h2>{passed ? "ناجح! 🎉" : "تحتاج مراجعة 💪"}</h2>
          <span className="tag">{report.accuracy}%</span>
        </div>

        <div className="grid cols-3">
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
          <span style={{ width: `${report.accuracy}%` }} />
        </div>

        {report.weak_topics && report.weak_topics.length ? (
          <div style={{ marginTop: 14 }}>
            <strong className="small">نقاط تحتاج تدريب:</strong>
            <div className="row wrap" style={{ marginTop: 6 }}>
              {report.weak_topics.map((t, i) => (
                <span key={i} className="chip">
                  {t}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <div className="row wrap" style={{ marginTop: 16 }}>
          <button className="btn" onClick={onRetry}>
            العودة للرئيسية
          </button>
          <Link className="btn ghost" href="/progress">
            افتح تقريري
          </Link>
        </div>
      </div>

      {report.mistakes && report.mistakes.length ? (
        <div className="card">
          <div className="card-title">
            <h3>مراجعة الأخطاء</h3>
          </div>
          <div className="list">
            {report.mistakes.map((m, i) => (
              <div className="list-item" key={i} style={{ display: "block" }}>
                <div className="title">{m.question}</div>
                <div className="small" style={{ color: "var(--danger)" }}>
                  إجابتك: {m.given || "(فارغة)"}
                </div>
                {m.explanation ? <div className="small muted">{m.explanation}</div> : null}
                {m.topic ? <span className="tag">{m.topic}</span> : null}
                {m.question_id ? <MistakeFlag questionId={m.question_id} /> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
