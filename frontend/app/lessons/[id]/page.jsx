"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import QuickCheck from "@/components/QuickCheck";
import { api, errorMessage } from "@/lib/api";

export default function LessonPage() {
  return (
    <Shell title="الدرس">
      <LessonBody />
    </Shell>
  );
}

function LessonBody() {
  const { id } = useParams();
  const router = useRouter();
  const [lesson, setLesson] = useState(null);
  const [mastery, setMastery] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/curriculum/lessons/${id}`);
      setLesson(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    load();
    api("/api/progress/mastery")
      .then((data) => {
        const row = (data.mastery || []).find((m) => m.lesson_id === id);
        setMastery(row || null);
      })
      .catch(() => setMastery(null));
  }, [load, id]);

  async function startSession() {
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/study/start", {
        method: "POST",
        body: { lesson_id: id, goal: lesson.title },
      });
      router.push(`/study?session=${data.session.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function makeQuiz() {
    setBusy(true);
    setError("");
    try {
      const quiz = await api("/api/quiz/generate", {
        method: "POST",
        body: { lesson_id: id, count: 8, difficulty: 3 },
      });
      router.push(`/quiz/${quiz.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function saveNote() {
    setBusy(true);
    try {
      await api("/api/library/notes", {
        method: "POST",
        body: {
          title: `ملخص: ${lesson.title}`,
          body: `${lesson.summary}\n\nالأهداف:\n• ${(lesson.objectives || []).join("\n• ")}`,
          lesson_id: id,
          subject_id: lesson.subject_id,
        },
      });
      setNotice("حُفظ الملخص في مكتبتك.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (error && !lesson) return <div className="error-box">{error}</div>;
  if (!lesson)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="card">
        <div className="card-title">
          <h2>{lesson.title}</h2>
          {lesson.is_demo ? <span className="tag demo">تجريبي</span> : null}
        </div>
        <p>{lesson.summary}</p>

        <div className="row wrap" style={{ marginBottom: 10 }}>
          <span className="chip">⏱ {lesson.estimated_minutes} دقيقة</span>
          <span className="chip">🎯 صعوبة {lesson.difficulty}/5</span>
          {mastery ? (
            <span className="chip">إتقان {Math.round(mastery.score)}%</span>
          ) : (
            <span className="chip">لم يُدرَّس بعد</span>
          )}
        </div>

        {mastery ? (
          <div className="bar" style={{ marginBottom: 12 }}>
            <span style={{ width: `${mastery.score}%` }} />
          </div>
        ) : null}

        <div className="row wrap">
          <button className="btn" disabled={busy} onClick={startSession}>
            📖 ابدأ جلسة دراسة
          </button>
          <button className="btn soft" disabled={busy} onClick={makeQuiz}>
            ✍️ اختبار فوري
          </button>
          <button className="btn ghost" disabled={busy} onClick={saveNote}>
            📝 احفظ ملخصاً
          </button>
          <Link className="btn ghost" href={`/chat?lesson=${id}`}>
            💬 اسأل مورس
          </Link>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>أهداف الدرس</h3>
        </div>
        <ul style={{ margin: 0, paddingInlineStart: 20 }}>
          {(lesson.objectives || []).map((o, i) => (
            <li key={i}>{o}</li>
          ))}
        </ul>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>كلمات مفتاحية</h3>
        </div>
        <div className="row wrap">
          {(lesson.keywords || []).map((k, i) => (
            <span key={i} className="chip">
              {k}
            </span>
          ))}
        </div>
        {lesson.page_start ? (
          <div className="muted small" style={{ marginTop: 10 }}>
            الكتاب: ص {lesson.page_start}–{lesson.page_end}
          </div>
        ) : null}
      </div>

      <QuickCheck lessonId={id} subjectId={lesson.subject_id} difficulty={lesson.difficulty || 3} />

      <div className="row wrap">
        <Link className="btn ghost sm" href="/plan">
          رجوع للخطة
        </Link>
        <Link className="btn ghost sm" href="/library">
          المكتبة
        </Link>
      </div>
    </div>
  );
}
