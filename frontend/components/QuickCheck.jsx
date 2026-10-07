"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";

const FLAG_KINDS = [
  { value: "wrong_answer", label: "الإجابة المعتمَدة غير صحيحة" },
  { value: "unclear", label: "صياغة السؤال غير واضحة" },
  { value: "bad_options", label: "الخيارات غير مناسبة" },
  { value: "other", label: "سبب آخر" },
];

/**
 * سؤال فهم واحد يظهر بعد محتوى الدرس مباشرة (فكرة Abwaab):
 * يولّد سؤالاً واحداً، يُجاب عليه في مكانه، ثم يعطي تغذية راجعة فورية
 * مع الإجابة الصحيحة وشرح الدرس — دون مغادرة الصفحة.
 */
export default function QuickCheck({ lessonId, subjectId, difficulty = 3 }) {
  const [phase, setPhase] = useState("loading");
  const [question, setQuestion] = useState(null);
  const [attemptId, setAttemptId] = useState(null);
  const [chosenId, setChosenId] = useState(null);
  const [pendingId, setPendingId] = useState(null);
  const [result, setResult] = useState(null);
  const [note, setNote] = useState("");
  const [flagOpen, setFlagOpen] = useState(false);
  const [flagKind, setFlagKind] = useState("wrong_answer");
  const [flagDetail, setFlagDetail] = useState("");
  const [flagSent, setFlagSent] = useState("");
  const startedAt = useRef(0);
  const ticket = useRef(0);

  const load = useCallback(async () => {
    const mine = ticket.current + 1;
    ticket.current = mine;
    setPhase("loading");
    setNote("");
    setResult(null);
    setChosenId(null);
    setFlagOpen(false);
    setFlagSent("");
    try {
      const quiz = await api("/api/quiz/generate", {
        method: "POST",
        body: {
          lesson_id: lessonId || undefined,
          subject_id: subjectId || undefined,
          kind: "practice",
          count: 1,
          difficulty,
          types: ["mcq"],
        },
      });
      const started = await api(`/api/quiz/${quiz.id}/start`, { method: "POST" });
      if (ticket.current !== mine) return;
      const first = (quiz.questions || [])[0];
      if (!first) {
        setNote("ما قدرنا نجهّز سؤالاً لهذا الدرس الآن — جرّب مرة ثانية.");
        setPhase("failed");
        return;
      }
      setAttemptId(started.attempt_id);
      setQuestion(first);
      startedAt.current = Date.now();
      setPhase("ready");
    } catch (err) {
      if (ticket.current !== mine) return;
      setNote(errorMessage(err));
      setPhase("failed");
    }
  }, [lessonId, subjectId, difficulty]);

  useEffect(() => {
    load();
  }, [load]);

  async function pick(option) {
    if (result || pendingId || !attemptId) return;
    setPendingId(option.id);
    try {
      const seconds = Math.max(
        0,
        Math.min(7200, Math.round((Date.now() - startedAt.current) / 1000)),
      );
      const res = await api(`/api/quiz/attempts/${attemptId}/answer`, {
        method: "POST",
        body: { question_id: question.id, answer: option.id, time_seconds: seconds },
      });
      setChosenId(option.id);
      setResult(res);
      setNote("");
    } catch (err) {
      setNote(errorMessage(err));
    } finally {
      setPendingId(null);
    }
  }

  async function sendFlag() {
    try {
      const res = await api(`/api/quiz/questions/${question.id}/flag`, {
        method: "POST",
        body: { kind: flagKind, detail: flagDetail },
      });
      setFlagSent(res.message || "وصل البلاغ — يراجعه فريق المحتوى.");
      setFlagOpen(false);
      setFlagDetail("");
    } catch (err) {
      setNote(errorMessage(err));
    }
  }

  const correct = result && result.correct_option ? result.correct_option : null;

  return (
    <div className="card" data-quick-check="1">
      <div className="card-title">
        <h3>سؤال سريع للفهم</h3>
        <span className="tag">سؤال واحد</span>
      </div>

      {note ? <div className="notice-box">{note}</div> : null}
      {flagSent ? <div className="notice-box">{flagSent}</div> : null}

      {phase === "loading" ? (
        <div className="row">
          <div className="spinner" />
          <span className="small muted">نجهّز لك سؤالاً من هذا الدرس…</span>
        </div>
      ) : null}

      {phase === "failed" && !note ? (
        <div className="row">
          <button className="btn soft sm" onClick={load}>
            أعد المحاولة
          </button>
        </div>
      ) : null}

      {phase === "ready" && question ? (
        <>
          <p style={{ fontSize: 17, fontWeight: 700, margin: "0 0 10px" }}>{question.prompt}</p>

          <div className="stack">
            {(question.options || []).map((option) => {
              let state = "";
              if (result) {
                if (option.id === chosenId) state = result.correct ? "correct" : "wrong";
                else if (correct && option.id === correct.id) state = "correct";
              } else if (pendingId === option.id) {
                state = "selected";
              }
              return (
                <button
                  key={option.id}
                  className={`option ${state}`}
                  disabled={!!result || !!pendingId}
                  onClick={() => pick(option)}
                >
                  <span>{option.text}</span>
                </button>
              );
            })}
          </div>

          {result ? (
            <div
              className="notice-box"
              style={{
                marginTop: 12,
                borderColor: result.correct ? "#c7f0e1" : "#ffd4d4",
                background: result.correct ? "#e9fbf4" : "#fff1f1",
                color: result.correct ? "#0f7b5a" : "#b91c1c",
              }}
            >
              <strong>{result.correct ? "إجابة صحيحة" : "ليست الإجابة الصحيحة"}</strong>
              {!result.correct && correct ? <div>الصحيح: {correct.text}</div> : null}
              {result.explanation ? <div style={{ marginTop: 4 }}>{result.explanation}</div> : null}
              {!result.correct ? (
                <div className="small" style={{ marginTop: 6, opacity: 0.85 }}>
                  قبل الشرح: شنو الفكرة اللي دفعتك تختار هذي؟ قارنها بالشرح ثم جرّب سؤالاً آخر.
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="row wrap" style={{ marginTop: 12 }}>
            {result ? (
              <button className="btn soft sm" onClick={load}>
                سؤال آخر
              </button>
            ) : null}
            <button className="btn ghost sm" onClick={() => setFlagOpen((v) => !v)}>
              🚩 إبلاغ عن السؤال
            </button>
          </div>

          {flagOpen ? (
            <div className="stack" style={{ marginTop: 10 }}>
              <select
                className="input"
                value={flagKind}
                onChange={(e) => setFlagKind(e.target.value)}
                aria-label="سبب البلاغ"
              >
                {FLAG_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
              <textarea
                className="input"
                rows={2}
                maxLength={500}
                placeholder="شرح مختصر (اختياري)"
                value={flagDetail}
                onChange={(e) => setFlagDetail(e.target.value)}
              />
              <div className="row wrap">
                <button className="btn sm" onClick={sendFlag}>
                  أرسل البلاغ
                </button>
                <button className="btn ghost sm" onClick={() => setFlagOpen(false)}>
                  إلغاء
                </button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
