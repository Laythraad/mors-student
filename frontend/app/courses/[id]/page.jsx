"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

const STATUS_TAG = {
  completed: { label: "مكتمل", cls: "ok" },
  started: { label: "بدأ", cls: "warn" },
  watched: { label: "شاهدته", cls: "warn" },
  quiz_failed: { label: "أعد المحاولة", cls: "warn" },
  new: { label: "متاح", cls: "" },
};

export default function CoursePage() {
  return (
    <Shell title="الكورس">
      <CourseBody />
    </Shell>
  );
}

function CourseBody() {
  const params = useParams();
  const courseId = params?.id;
  const [course, setCourse] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/media/courses/${courseId}`);
      setCourse(data);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [courseId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !course) return <div className="error-box">{error}</div>;
  if (!course)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  const percent = Math.round(course.progress_percent || 0);

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      <div className="card">
        <div className="card-title">
          <div className="grow">
            <h3>📚 {course.title}</h3>
            <div className="small muted">
              {course.subject ? `${course.subject} · ` : ""}
              {course.teacher ? `${course.teacher} · ` : ""}
              {course.video_total} فيديو
            </div>
          </div>
          <span className={`tag ${percent >= 100 ? "ok" : percent > 0 ? "warn" : ""}`}>
            {percent}%
          </span>
        </div>
        <p className="small muted" style={{ margin: "0 0 10px" }}>
          {course.description}
        </p>
        <div className="course-head">
          <div className="bar grow">
            <span style={{ width: `${percent}%` }} />
          </div>
          <span className="mono small">{course.watched}/{course.video_total} مكتمل</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>الوحدات (Modules)</h3>
        </div>
        {course.modules.map((m) => (
          <div className="module-block" key={m.key}>
            <div className="module-head">
              <b>▣ {m.title}</b>
              <span className="mono small">{Math.round(m.percent)}%</span>
            </div>
            <div className="bar">
              <span style={{ width: `${Math.round(m.percent)}%` }} />
            </div>
            <div className="small muted" style={{ marginTop: 6 }}>
              {m.total} فيديو · {m.completed ?? 0} مكتمل
            </div>
          </div>
        ))}
        {!course.modules.length ? <div className="empty">ما توجد وحدات معرفة.</div> : null}
      </div>

      {course.lessons?.length ? (
        <div className="card">
          <div className="card-title">
            <h3>الدروس (Lessons)</h3>
          </div>
          <div className="list">
            {course.lessons.map((l) => {
              const tag = STATUS_TAG[l.status] || STATUS_TAG.new;
              return (
                <div className="lesson-row" key={l.lesson_id}>
                  <span className="grow">{l.title || l.lesson_id}</span>
                  <span className="count">{l.videos} فيديو</span>
                  <span className={`tag ${tag.cls}`}>{l.status_label}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="card">
        <div className="card-title">
          <h3>الفيديوهات</h3>
        </div>
        <div className="list">
          {course.videos.map((v) => {
            const tag = STATUS_TAG[v.status] || STATUS_TAG.new;
            return (
              <Link className="video-row" key={v.id} href={`/videos/${v.id}`}>
                <span className="vtitle">▶ {v.title}</span>
                <span className="count small muted">
                  {Math.round((v.duration_seconds || 0) / 60)} د
                </span>
                <span className={`tag ${tag.cls}`}>{tag.label}</span>
              </Link>
            );
          })}
          {!course.videos.length ? <div className="empty">الكورس بدون فيديوهات.</div> : null}
        </div>
      </div>
    </div>
  );
}
