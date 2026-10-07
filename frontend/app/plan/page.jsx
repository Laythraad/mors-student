"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtDate } from "@/lib/api";

export default function PlanPage() {
  return (
    <Shell title="خطتي">
      <PlanBody />
    </Shell>
  );
}

function PlanBody() {
  const router = useRouter();
  const [plan, setPlan] = useState(null);
  const [what, setWhat] = useState(null);
  const [exams, setExams] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [examForm, setExamForm] = useState({ title: "", exam_date: "" });

  const load = useCallback(async () => {
    try {
      const [current, whats, examList, taskList] = await Promise.all([
        api("/api/plan/current"),
        api("/api/plan/what-now"),
        api("/api/plan/exams"),
        api("/api/plan/tasks"),
      ]);
      setPlan(current.plan);
      setWhat(whats);
      setExams(examList.exams || []);
      setTasks(taskList.tasks || []);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/plan/generate", { method: "POST", body: { days: 7 } });
      setPlan(data.plan);
      setNotice("تم إنشاء خطة جديدة.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function recovery() {
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/plan/recovery", { method: "POST" });
      setNotice(data.message || "أعدنا ترتيب خطتك.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function complete(taskId) {
    try {
      await api(`/api/plan/tasks/${taskId}/complete`, { method: "POST" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function postpone(taskId) {
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    try {
      await api(`/api/plan/tasks/${taskId}/move`, {
        method: "POST",
        body: { date: tomorrow },
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function addExam(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/api/plan/exams", { method: "POST", body: examForm });
      setExamForm({ title: "", exam_date: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function countdown(examId) {
    setBusy(true);
    try {
      const data = await api(`/api/plan/exam-countdown/${examId}`, { method: "POST" });
      setNotice(`خطة الامتحان جاهزة: ${data.days_left} يوم.`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const todayKey = new Date().toISOString().slice(0, 10);

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="card">
        <div className="card-title">
          <h3>{plan ? plan.title : "لا توجد خطة بعد"}</h3>
          <span className="row">
            <button className="btn sm" disabled={busy} onClick={generate}>
              خطة جديدة
            </button>
            <button className="btn ghost sm" disabled={busy} onClick={recovery}>
              رتّب تراكمي
            </button>
          </span>
        </div>

        {what && what.available ? (
          <div className="row between" style={{ background: "var(--primary-soft)", padding: 10, borderRadius: 12 }}>
            <div>
              <div className="small muted">الآن الأفضل لك</div>
              <strong>{what.lesson ? what.lesson.title : what.subject ? what.subject.name_ar : "ابدأ"}</strong>
            </div>
            <button className="btn sm" onClick={() => router.push("/home")}>
              ابدأ
            </button>
          </div>
        ) : (
          <div className="muted small">{what ? what.message : ""}</div>
        )}
      </div>

      {plan && plan.days && plan.days.length ? (
        plan.days.map((day) => (
          <div className="card" key={day.id || day.date}>
            <div className="card-title">
              <h3>
                {day.date === todayKey ? "اليوم" : fmtDate(day.date)}{" "}
                {day.is_rest ? <span className="tag">راحة</span> : null}
              </h3>
              <span className="muted small">
                {day.focus} · {day.total_minutes} دقيقة
              </span>
            </div>
            {day.tasks && day.tasks.length ? (
              <div className="list">
                {day.tasks.map((task) => (
                  <div className="list-item" key={task.id}>
                    <div className="grow">
                      <div className="title ellip">{task.title}</div>
                      <div className="small muted">
                        {task.scheduled_start ? task.scheduled_start.slice(11, 16) : ""} ·{" "}
                        {task.duration_minutes} دقيقة · {task.type === "review" ? "مراجعة" : "دراسة"}
                      </div>
                    </div>
                    {task.status === "completed" ? (
                      <span className="tag ok">منجزة</span>
                    ) : (
                      <span className="row">
                        <button className="btn sm" onClick={() => complete(task.id)}>
                          أنجزتها
                        </button>
                        <button className="btn ghost sm" onClick={() => postpone(task.id)}>
                          غداً
                        </button>
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty">لا مهام في هذا اليوم.</div>
            )}
          </div>
        ))
      ) : (
        <div className="empty">ما عندك خطة — اضغط «خطة جديدة» ونرتب لك أسبوعك.</div>
      )}

      <div className="card">
        <div className="card-title">
          <h3>امتحاناتي</h3>
        </div>
        {exams.length ? (
          <div className="list" style={{ marginBottom: 12 }}>
            {exams.map((exam) => (
              <div className="list-item" key={exam.id}>
                <div className="grow">
                  <div className="title ellip">{exam.title}</div>
                  <div className="small muted">
                    {exam.exam_date} · باقي {exam.days_left} يوم
                  </div>
                </div>
                <button className="btn sm" disabled={busy} onClick={() => countdown(exam.id)}>
                  خطة العدّ التنازلي
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="muted small" style={{ marginBottom: 10 }}>
            أضف امتحاناً قادماً ونبني خطة عدّ تنازلي.
          </div>
        )}
        <form onSubmit={addExam} className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 180, marginBottom: 0 }}>
            <label>اسم الامتحان</label>
            <input
              className="input"
              required
              value={examForm.title}
              onChange={(e) => setExamForm({ ...examForm, title: e.target.value })}
            />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>التاريخ</label>
            <input
              className="input"
              type="date"
              required
              value={examForm.exam_date}
              onChange={(e) => setExamForm({ ...examForm, exam_date: e.target.value })}
            />
          </div>
          <button className="btn" disabled={busy}>
            إضافة
          </button>
        </form>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>كل المهام</h3>
          <span className="tag">{tasks.length}</span>
        </div>
        <div className="list">
          {tasks.slice(0, 30).map((task) => (
            <div className="list-item" key={task.id}>
              <div className="grow">
                <div className="title ellip">{task.title}</div>
                <div className="small muted">
                  {task.scheduled_date} · {task.status === "completed" ? "منجزة" : task.status}
                </div>
              </div>
              {task.status !== "completed" ? (
                <button className="btn sm soft" onClick={() => complete(task.id)}>
                  إنجاز
                </button>
              ) : (
                <span className="tag ok">✅</span>
              )}
            </div>
          ))}
          {!tasks.length ? <div className="empty">لا مهام.</div> : null}
        </div>
        <div className="divider" />
        <Link className="btn ghost sm" href="/progress">
          افتح تقرير التقدّم
        </Link>
      </div>
    </div>
  );
}
