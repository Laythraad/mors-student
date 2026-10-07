"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtDate } from "@/lib/api";

const STATUS_TAG = {
  new: { label: "غير مبدأ", cls: "" },
  started: { label: "بدأ", cls: "warn" },
  watched: { label: "شاهدته", cls: "warn" },
  quiz_failed: { label: "أعد المحاولة", cls: "warn" },
  completed: { label: "مكتمل", cls: "ok" },
};

const REPORT_KINDS = [
  { value: "not_working", label: "الفيديو لا يعمل" },
  { value: "not_linked", label: "الدرس غير مرتبط" },
  { value: "unclear", label: "الشرح غير واضح" },
  { value: "other", label: "مشكلة أخرى" },
];

function youtubeId(url) {
  const match = /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/shorts\/)([\w-]{11})/.exec(
    url || "",
  );
  return match ? match[1] : null;
}

function hostedUrl(url) {
  return typeof url === "string" && url.startsWith("/") ? url : null;
}

function loadYouTubeAPI() {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (!window.__morsYTPromise) {
    window.__morsYTPromise = new Promise((resolve) => {
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        if (previous) previous();
        resolve(window.YT);
      };
      const tag = document.createElement("script");
      tag.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(tag);
    });
  }
  return window.__morsYTPromise;
}

export default function VideoPage() {
  return (
    <Shell title="فيديو">
      <VideoBody />
    </Shell>
  );
}

function VideoBody() {
  const params = useParams();
  const router = useRouter();
  const videoId = params?.id;
  const [video, setVideo] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [watched, setWatched] = useState(0);
  const [saving, setSaving] = useState(false);
  const [quizBusy, setQuizBusy] = useState(false);
  const [keyIdea, setKeyIdea] = useState("");
  const [reportOpen, setReportOpen] = useState(false);
  const [reportForm, setReportForm] = useState({ kind: "not_working", detail: "" });
  const [reportBusy, setReportBusy] = useState(false);

  const playerRef = useRef(null);
  const holderRef = useRef(null);
  const videoRef = useRef(null);
  const lastSavedRef = useRef(0);

  const ytId = video ? video.youtube_id || youtubeId(video.url) : null;
  const hostedSrc = video ? hostedUrl(video.url) : null;
  const duration = video?.duration_seconds || 0;

  const save = useCallback(
    async (pos, watch, idea) => {
      if (!videoId) return;
      setSaving(true);
      try {
        const data = await api(`/api/media/videos/${videoId}/progress`, {
          method: "POST",
          body: {
            position: Math.max(0, Math.round(pos)),
            watched_seconds: Math.max(0, Math.round(watch)),
            key_idea: idea === undefined ? "" : idea,
          },
        });
        setVideo((prev) => (prev ? { ...prev, progress: data.progress, status: data.status, status_label: data.status_label } : prev));
        lastSavedRef.current = Math.round(pos);
      } catch {
        /* the next tick will retry — never block playback */
      } finally {
        setSaving(false);
      }
    },
    [videoId],
  );

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/media/videos/${videoId}`);
      setVideo(data);
      const resume =
        data.status === "completed" || data.status === "watched"
          ? 0
          : data.progress?.last_position || 0;
      setPosition(resume);
      setWatched(Math.max(data.progress?.watched_seconds || 0, resume));
      setKeyIdea(data.progress?.key_idea || "");
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [videoId]);

  useEffect(() => {
    load();
  }, [load]);

  // A file we host ourselves plays in a native <video>; its own time updates
  // drive progress, so there is never a fake clock ticking without playback.
  function onHostedTime(e) {
    const el = e.currentTarget;
    const time = Math.round(el.currentTime || 0);
    setPosition((prev) => Math.max(prev, time));
    setWatched((prev) => Math.max(prev, time));
    if (Math.abs(time - lastSavedRef.current) >= 15) {
      save(time, Math.max(duration, time, watched));
    }
  }

  function onHostedEnded() {
    setPlaying(false);
    save(duration, Math.max(duration, watched));
  }

  // YouTube player (§36: keep the official embed + its features intact)
  useEffect(() => {
    if (!video || !ytId || !holderRef.current) return;
    let disposed = false;
    let interval = null;
    loadYouTubeAPI()
      .then((YT) => {
        if (disposed || !holderRef.current) return;
        playerRef.current = new YT.Player(holderRef.current, {
          videoId: ytId,
          playerVars: {
            start: video.progress?.last_position || 0,
            rel: 0,
            modestbranding: 1,
          },
          events: {
            onStateChange: (event) => {
              if (!playerRef.current) return;
              const time = Math.round(playerRef.current.getCurrentTime() || 0);
              if (event.data === 0) {
                // ended → full credit
                save(duration || time, Math.max(duration, time));
                setPlaying(false);
              } else if (event.data === 1) {
                setPlaying(true);
              } else if (event.data === 2) {
                setPlaying(false);
                save(time, Math.max(watched, time));
              }
            },
          },
        });
        interval = setInterval(() => {
          if (!playerRef.current || !playerRef.current.getCurrentTime) return;
          const time = Math.round(playerRef.current.getCurrentTime() || 0);
          setPosition((prev) => Math.max(prev, time));
          setWatched((prev) => Math.max(prev, time));
          if (Math.abs(time - lastSavedRef.current) >= 15) {
            save(time, Math.max(duration, time, watched));
          }
        }, 5000);
      })
      .catch(() => {
        /* offline / blocked CDN: the external link below still works */
      });
    return () => {
      disposed = true;
      if (interval) clearInterval(interval);
      if (playerRef.current && playerRef.current.destroy) {
        try {
          playerRef.current.destroy();
        } catch {
          /* player already gone */
        }
      }
      playerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [video, ytId]);

  async function startQuiz() {
    if (quizBusy) return;
    setQuizBusy(true);
    setError("");
    try {
      if (keyIdea.trim()) await save(position, watched, keyIdea.trim());
      const result = await api(`/api/media/videos/${videoId}/quiz`, { method: "POST" });
      router.push(`/quiz/${result.quiz_id}`);
    } catch (err) {
      setError(errorMessage(err));
      setQuizBusy(false);
    }
  }

  async function sendReport() {
    if (reportBusy) return;
    setReportBusy(true);
    setError("");
    try {
      const result = await api(`/api/media/videos/${videoId}/report`, {
        method: "POST",
        body: reportForm,
      });
      setNotice(result.message);
      setReportOpen(false);
      setReportForm({ kind: "not_working", detail: "" });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setReportBusy(false);
    }
  }

  if (error && !video) return <div className="error-box">{error}</div>;
  if (!video)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  const stateTag = STATUS_TAG[video.status] || STATUS_TAG.new;
  const percent = duration ? Math.min(100, Math.round((watched / duration) * 100)) : 0;
  const quizReady = video.status !== "new" && video.status !== "completed";

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="card">
        <div className="card-title">
          <div className="grow">
            <h3>{video.title}</h3>
            <div className="small muted">
              {video.course ? `${video.course.title} · ` : ""}
              {video.lesson ? video.lesson.title : ""}
              {video.duration_seconds ? ` · ${Math.round(video.duration_seconds / 60)} دقيقة` : ""}
            </div>
          </div>
          <span className={`tag ${stateTag.cls}`}>{stateTag.label}</span>
        </div>

        <div className="video-frame">
          {ytId ? (
            <div ref={holderRef} />
          ) : hostedSrc ? (
            <video
              ref={videoRef}
              className="hosted-player"
              src={hostedSrc}
              controls
              onPlay={() => setPlaying(true)}
              onPause={() => {
                setPlaying(false);
                save(position, watched);
              }}
              onTimeUpdate={onHostedTime}
              onEnded={onHostedEnded}
            />
          ) : (
            <div className="empty" role="status">
              <strong>الفيديو غير متوفر لهذا الدرس.</strong>
              <div className="small muted" style={{ marginTop: 6 }}>
                لا يوجد رابط مشغّل مُوثَّق لهذا الدرس بعد — تقدّمك في الاختبار
                محفوظ كالمعتاد.
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <button
                  className="btn ghost sm"
                  onClick={() => {
                    setReportOpen(true);
                    setReportForm((f) => ({ ...f, kind: "not_working" }));
                  }}
                >
                  🚩 أبلغ فريق المحتوى
                </button>
                <a
                  className="btn ghost sm"
                  href={`https://www.youtube.com/results?search_query=${encodeURIComponent(
                    video.lesson?.title || video.title || "",
                  )}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  ابحث عن الدرس على يوتيوب ↗
                </a>
              </div>
            </div>
          )}
        </div>

        {video.description ? (
          <p className="small muted" style={{ marginTop: 8, whiteSpace: "pre-line" }}>
            {video.description}
          </p>
        ) : null}

        <div className="row" style={{ marginTop: 10 }}>
          <div className="bar grow">
            <span style={{ width: `${percent}%` }} />
          </div>
          <span className="mono small">{percent}%</span>
          <span className="small muted">{saving ? "جاري الحفظ…" : "محفوظ"}</span>
        </div>
        {video.progress?.last_position > 0 && video.status !== "completed" ? (
          <div className="small muted" style={{ marginTop: 6 }}>
            آخر موضع توقفت عنده: {fmtClock(video.progress.last_position)}
            {playing ? null : (
              <button
                className="btn ghost sm"
                style={{ marginInlineStart: 8 }}
                onClick={() => setPosition(video.progress.last_position)}
              >
                ارجع له
              </button>
            )}
          </div>
        ) : null}
      </div>

      {video.status === "completed" ? (
        <div className="card">
          <div className="card-title">
            <h3>الدرس مكتمل ✅</h3>
            {video.progress?.quiz_score !== null && video.progress?.quiz_score !== undefined ? (
              <span className="tag ok">درجة الاختبار {Math.round(video.progress.quiz_score)}%</span>
            ) : null}
          </div>
          <p className="muted" style={{ margin: 0 }}>
            أنهيت الفيديو واجتزت اختبار الفهم — {fmtDate(new Date().toISOString())}.
          </p>
        </div>
      ) : quizReady ? (
        <div className="card problem">
          <div className="card-title">
            <h3>قبل ما ننتقل، خليني أشوف فهمك.</h3>
            {video.status === "quiz_failed" ? <span className="tag warn">السابق دون {Math.round(60)}%</span> : null}
          </div>
          <div className="field">
            <label>اكتب الفكرة الأساسية بجملة (اختياري)</label>
            <input
              className="input"
              value={keyIdea}
              maxLength={400}
              onChange={(e) => setKeyIdea(e.target.value)}
              placeholder="مثال: المتتالية الحسابية فرقها ثابت"
            />
          </div>
          <div className="row">
            <button className="btn" onClick={startQuiz} disabled={quizBusy}>
              {quizBusy ? "جاري التحضير…" : "اختبر فهمي (5 أسئلة)"}
            </button>
            <span className="small muted">النجاح من 60% يغلق الدرس.</span>
          </div>
        </div>
      ) : null}

      <div className="card">
        <div className="card-title">
          <h3>الإعدادات والروابط</h3>
        </div>
        <div className="row wrap">
          {video.prev ? (
            <Link className="btn ghost sm" href={`/videos/${video.prev.id}`}>
              ↩ {video.prev.title}
            </Link>
          ) : null}
          {video.next ? (
            <Link className="btn ghost sm" href={`/videos/${video.next.id}`}>
              {video.next.title} ↪
            </Link>
          ) : null}
          {video.course ? (
            <Link className="btn soft sm" href={`/courses/${video.course.id}`}>
              تقدّم الكورس
            </Link>
          ) : null}
          <button className="btn ghost sm" onClick={() => setReportOpen((v) => !v)}>
            🚩 بلاغ عن الفيديو
          </button>
        </div>

        {reportOpen ? (
          <div className="field" style={{ marginTop: 12 }}>
            <label>نوع البلاغ</label>
            <select
              className="input"
              value={reportForm.kind}
              onChange={(e) => setReportForm((f) => ({ ...f, kind: e.target.value }))}
            >
              {REPORT_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
            <label style={{ marginTop: 8 }}>تفاصيل (اختياري)</label>
            <input
              className="input"
              value={reportForm.detail}
              maxLength={500}
              onChange={(e) => setReportForm((f) => ({ ...f, detail: e.target.value }))}
              placeholder="مثال: الرابط يفتح صفحة محذوفة"
            />
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn sm" onClick={sendReport} disabled={reportBusy}>
                {reportBusy ? "جاري الإرسال…" : "أرسل البلاغ"}
              </button>
              <span className="small muted">يدخل البلاغ إلى قائمة مراجعة المحتوى.</span>
            </div>
          </div>
        ) : null}

        {video.transcript ? (
          <>
            <div className="divider" />
            <strong className="small">النص المفرّغ</strong>
            <p className="small muted">{video.transcript}</p>
          </>
        ) : null}
      </div>
    </div>
  );
}

function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const rest = String(s % 60).padStart(2, "0");
  return `${String(m).padStart(2, "0")}:${rest}`;
}
