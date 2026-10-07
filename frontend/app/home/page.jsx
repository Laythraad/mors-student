"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtShortDate } from "@/lib/api";

export default function HomePage() {
  return (
    <Shell title="الرئيسية">
      <HomeBody />
    </Shell>
  );
}

function HomeBody() {
  const router = useRouter();
  const [data, setData] = useState(null);
  const [coach, setCoach] = useState(null);
  const [daily, setDaily] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dailyBusy, setDailyBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [home, day] = await Promise.all([
        api("/api/progress/home"),
        api("/api/progress/coach/daily"),
      ]);
      setData(home);
      setCoach(day);
    } catch (err) {
      setError(errorMessage(err));
    }
    api("/api/quiz/daily")
      .then(setDaily)
      .catch(() => setDaily(null));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function startNext() {
    const next = data && data.next;
    if (!next || !next.available) {
      router.push("/plan");
      return;
    }
    setBusy(true);
    try {
      const lessonId = next.lesson ? next.lesson.id : null;
      const session = await api("/api/study/start", {
        method: "POST",
        body: {
          lesson_id: lessonId,
          subject_id: next.subject ? next.subject.id : null,
          goal: next.lesson ? next.lesson.title : "",
        },
      });
      router.push(`/study?session=${session.session.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function startDaily() {
    setDailyBusy(true);
    try {
      const quiz = await api("/api/quiz/daily", { method: "POST" });
      router.push(`/quiz/${quiz.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setDailyBusy(false);
    }
  }

  if (error && !data) return <div className="error-box">{error}</div>;
  if (!data)
    return (
      <div className="loading-page">
        <div className="spinner" />
        <span>نجهّز لك صفحتك…</span>
      </div>
    );

  const next = data.next || {};
  const streak = data.streak || { current: 0, longest: 0 };

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      <div className="card">
        <div className="row between">
          <div>
            <h2 style={{ margin: 0 }}>{data.greeting}</h2>
            <div className="muted small">{data.mors ? data.mors.message : ""}</div>
          </div>
          <img
            src={data.mors ? data.mors.sprite : "/mors/neutral.png"}
            alt="مورس"
            width={64}
            height={64}
            style={{ borderRadius: "50%", border: "2px solid var(--border)" }}
          />
        </div>
      </div>

      <div className="grid cols-3">
        <div className="stat">
          <div className="value">{streak.current}</div>
          <div className="label">سلسلة الأيام 🔥</div>
        </div>
        <div className="stat">
          <div className="value">{data.weekly_minutes || 0}</div>
          <div className="label">دقائق هذا الأسبوع</div>
        </div>
        <div className="stat">
          <div className="value">{data.reviews ? data.reviews.due : 0}</div>
          <div className="label">مراجعات مستحقة</div>
        </div>
      </div>

      {daily ? (
        <div className="card" data-daily-quiz="1">
          <div className="card-title">
            <h3>اختبار اليوم</h3>
            <span className="tag">{daily.question_count || 3} أسئلة</span>
          </div>
          {daily.completed ? (
            <>
              <p className="small muted" style={{ margin: 0 }}>
                أنجزت اختبار اليوم — نتيجتك {Math.round(daily.accuracy || 0)}%.
              </p>
              <div className="row wrap" style={{ marginTop: 10 }}>
                <Link className="btn ghost sm" href="/progress">
                  افتح تقريري
                </Link>
              </div>
            </>
          ) : (
            <>
              <p className="small muted" style={{ margin: 0 }}>
                أسئلة سريعة من موادك — دقيقة واحدة فقط، ويتحدّث كل يوم.
              </p>
              <div className="row wrap" style={{ marginTop: 10 }}>
                <button className="btn sm" disabled={dailyBusy} onClick={startDaily}>
                  {dailyBusy ? "نجهّز الاختبار…" : "ابدأ اختبار اليوم"}
                </button>
              </div>
            </>
          )}
        </div>
      ) : null}

      <div className="card">
        <div className="card-title">
          <h3>الخطوة التالية</h3>
          <Link href="/plan" className="btn ghost sm">
            خطتي
          </Link>
        </div>
        {next.available ? (
          <>
            <div className="row between">
              <div>
                <div className="tag">{next.kind === "review" ? "مراجعة" : "دراسة"}</div>
                <div style={{ fontWeight: 800, fontSize: 18, marginTop: 6 }}>
                  {next.lesson ? next.lesson.title : next.subject ? next.subject.name_ar : "ابدأ الآن"}
                </div>
                <div className="muted small">{next.reason || ""}</div>
              </div>
              {next.subject ? (
                <span
                  className="tag"
                  style={{
                    background: next.subject.color || "var(--primary-soft)",
                    color: "#fff",
                  }}
                >
                  {next.subject.name_ar}
                </span>
              ) : null}
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={startNext} disabled={busy}>
                {busy ? "جاري البدء…" : "ابدأ الآن"}
              </button>
              <Link className="btn ghost" href="/chat">
                اسأل مورس
              </Link>
            </div>
          </>
        ) : (
          <div className="empty">{next.message || "ما عندك مهمة حالياً — أنشئ خطة جديدة."}</div>
        )}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-title">
            <h3>مهام اليوم</h3>
            <span className="tag">{(data.today && data.today.tasks ? data.today.tasks.length : 0)}</span>
          </div>
          {data.today && data.today.tasks && data.today.tasks.length ? (
            <div className="list">
              {data.today.tasks.slice(0, 5).map((task) => (
                <Link key={task.id} href="/plan" className="list-item">
                  <div className="grow">
                    <div className="title ellip">{task.title}</div>
                    <div className="small muted">
                      {task.duration_minutes} دقيقة · {task.status === "completed" ? "منجزة" : "بالانتظار"}
                    </div>
                  </div>
                  <span>{task.status === "completed" ? "✅" : "⏳"}</span>
                </Link>
              ))}
            </div>
          ) : (
            <div className="empty">لا مهام اليوم.</div>
          )}
        </div>

        <div className="card">
          <div className="card-title">
            <h3>نبذة اليوم</h3>
            <Link href="/progress" className="btn ghost sm">
              التقرير
            </Link>
          </div>
          {coach ? (
            <div className="stack small">
              <strong>{coach.headline}</strong>
              {(coach.lines || []).slice(1, 5).map((line, i) => (
                <div key={i} className="muted">
                  • {line}
                </div>
              ))}
            </div>
          ) : (
            <div className="muted small">…</div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>نقاط ضعفك</h3>
          <Link href="/progress" className="btn ghost sm">
            كل التفاصيل
          </Link>
        </div>
        {data.weak_topics && data.weak_topics.length ? (
          <div className="row wrap">
            {data.weak_topics.map((w, i) => (
              <span key={i} className="chip">
                {w.topic} <span className="tag warn">{w.errors} أخطاء</span>
              </span>
            ))}
          </div>
        ) : (
          <div className="empty">لا نقاط ضعف — استمرّ هكذا.</div>
        )}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>آخر النتائج</h3>
        </div>
        {data.recent_results && data.recent_results.length ? (
          <div className="list">
            {data.recent_results.map((r, i) => (
              <div key={i} className="list-item">
                <div className="grow">
                  <div className="title ellip">{r.title || "اختبار"}</div>
                  <div className="small muted">{fmtShortDate(r.finished_at)}</div>
                </div>
                <strong style={{ color: r.accuracy >= 70 ? "var(--success)" : "var(--danger)" }}>
                  {Math.round(r.accuracy)}%
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">لا نتائج بعد — ابدأ اختباراً من صفحة الدرس.</div>
        )}
      </div>
    </div>
  );
}
