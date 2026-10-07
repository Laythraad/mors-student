"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtTime } from "@/lib/api";

export default function StudyPage() {
  return (
    <Shell title="جلسة دراسة">
      <Suspense fallback={null}>
        <StudyBody />
      </Suspense>
    </Shell>
  );
}

function StudyBody() {
  const params = useSearchParams();
  const router = useRouter();
  const sessionId = params.get("session");

  const [session, setSession] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState(null);
  const [feedback, setFeedback] = useState("medium");
  const [comment, setComment] = useState("");
  const startedAt = useRef(Date.now());
  const [tick, setTick] = useState(0);

  const load = useCallback(async () => {
    if (!sessionId) {
      try {
        const data = await api("/api/study/active");
        if (data.session) setSession(data.session);
        else setError("لا توجد جلسة نشطة.");
      } catch (err) {
        setError(errorMessage(err));
      }
      return;
    }
    try {
      const data = await api("/api/study/active");
      if (data.session && data.session.id === sessionId) {
        setSession(data.session);
        startedAt.current = Date.now();
      } else {
        const recent = await api("/api/study/recent");
        const match = (recent.sessions || []).find((s) => s.id === sessionId);
        if (match) setSession(match);
        else setError("الجلسة غير موجودة.");
      }
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [sessionId]);

  useEffect(() => {
    load();
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    const beat = setInterval(() => {
      if (session && session.status === "active") {
        api(`/api/study/${session.id}/heartbeat`, {
          method: "POST",
          body: { elapsed_seconds: elapsed() },
        }).catch(() => {});
      }
    }, 30000);
    return () => {
      clearInterval(timer);
      clearInterval(beat);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, session && session.id]);

  function elapsed() {
    if (!session) return 0;
    const base = session.elapsed_seconds || 0;
    if (session.status !== "active") return base;
    return base + Math.floor((Date.now() - startedAt.current) / 1000);
  }

  async function finish() {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/study/${session.id}/end`, {
        method: "POST",
        body: {
          status: "completed",
          feedback,
          comment,
          understanding: feedback === "easy" ? 0.9 : feedback === "medium" ? 0.7 : 0.4,
          mistakes: 0,
        },
      });
      setFinished(data);
      setSession({ ...session, status: "completed", elapsed_seconds: elapsed() });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function startBreak() {
    try {
      await api("/api/study/break", { method: "POST" });
      setNotice("أخذنا بريك — ريح شوي.");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const [notice, setNotice] = useState("");
  const seconds = elapsed();

  if (error && !session) return <div className="error-box">{error}</div>;
  if (!session)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  if (finished) {
    return (
      <div className="stack">
        <div className="card">
          <div className="card-title">
            <h2>أحسنت! 🎉</h2>
          </div>
          <div className="grid cols-3">
            <div className="stat">
              <div className="value">{finished.minutes}</div>
              <div className="label">دقيقة دراسة</div>
            </div>
            <div className="stat">
              <div className="value">{finished.streak ? finished.streak.current : 1}</div>
              <div className="label">سلسلة الأيام</div>
            </div>
            <div className="stat">
              <div className="value">{finished.mors ? "✓" : "—"}</div>
              <div className="label">رد فعل مورس</div>
            </div>
          </div>
          {finished.mors ? (
            <div className="row" style={{ marginTop: 14 }}>
              <img src={finished.mors.sprite} alt="مورس" width={72} height={72} style={{ borderRadius: "50%" }} />
              <div className="muted">{finished.mors.text || finished.mors.message || ""}</div>
            </div>
          ) : null}
          <div className="row wrap" style={{ marginTop: 16 }}>
            <button className="btn" onClick={() => router.push("/home")}>
              الرئيسية
            </button>
            <button className="btn ghost" onClick={() => router.push("/plan")}>
              خطتي
            </button>
            <button className="btn ghost" onClick={startBreak}>
              بريك ٥ دقائق
            </button>
          </div>
        </div>
        {notice ? <div className="success-box">{notice}</div> : null}
      </div>
    );
  }

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      <div className="card">
        <div className="card-title">
          <h2>{session.title}</h2>
          <span className="tag">{session.status === "active" ? "نشطة" : "منتهية"}</span>
        </div>
        {session.goal ? <p className="muted">الهدف: {session.goal}</p> : null}

        <div style={{ textAlign: "center", padding: "18px 0" }}>
          <div style={{ fontSize: 56, fontWeight: 800, fontFamily: "monospace" }} dir="ltr">
            {fmtTime(seconds)}
          </div>
          <div className="muted small">الزمن المستهدف: {session.planned_minutes} دقيقة</div>
          <div className="bar" style={{ marginTop: 10 }}>
            <span
              style={{
                width: `${Math.min(100, (seconds / (session.planned_minutes * 60)) * 100)}%`,
              }}
            />
          </div>
        </div>

        <div className="row wrap" style={{ justifyContent: "center" }}>
          <button className="btn" disabled={busy} onClick={finish}>
            أنهي الجلسة
          </button>
          <button className="btn ghost" onClick={startBreak}>
            بريك
          </button>
          <button
            className="btn ghost"
            onClick={() => router.push(session.lesson_id ? `/lessons/${session.lesson_id}` : "/plan")}
          >
            فتح الدرس
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>كيف كان الأداء؟</h3>
        </div>
        <div className="row wrap" style={{ marginBottom: 10 }}>
          {[
            { key: "easy", label: "سهل 🙂" },
            { key: "medium", label: "متوسط 😐" },
            { key: "hard", label: "صعب 😓" },
            { key: "not_understood", label: "ما فهمت 🤯" },
          ].map((opt) => (
            <button
              key={opt.key}
              className={`chip ${feedback === opt.key ? "on" : ""}`}
              onClick={() => setFeedback(opt.key)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <textarea
          className="textarea"
          placeholder="شنو اللي واجهتك؟ (اختياري)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
    </div>
  );
}
