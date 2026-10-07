"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

const TABS = [
  { key: "status", label: "كيف مستواي؟" },
  { key: "problems", label: "ما مشكلتي؟" },
  { key: "steps", label: "شنو لازم أسوي؟" },
  { key: "week", label: "خطة الأسبوع" },
];

const IMPROVEMENT = {
  up: "تحسّن",
  down: "تراجع",
  flat: "مستقر",
};

export default function AdvisorPage() {
  return (
    <Shell title="مرشدي">
      <AdvisorBody />
    </Shell>
  );
}

function AdvisorBody() {
  const router = useRouter();
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("status");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api("/api/advisor"));
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function apply(stepKey) {
    const step = (data?.steps || []).find((item) => item.key === stepKey);
    if (!step || !step.available || busy) return;
    if (step.requires_approval) {
      const ok = window.confirm("هذا التعديل يغيّر خطتك الحالية — نطبّقه؟");
      if (!ok) return;
    }
    setBusy(stepKey);
    setError("");
    setNotice(null);
    try {
      const result = await api(`/api/advisor/steps/${stepKey}/apply`, { method: "POST" });
      if (result.link && (result.link.startsWith("/quiz/") || result.link.startsWith("/exam/"))) {
        router.push(result.link);
        return;
      }
      setNotice(result);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  if (error && !data) return <div className="error-box">{error}</div>;
  if (!data)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  const report = data.report;
  const problems = report.problems || [];

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? (
        <div className="success-box">
          {notice.message}{" "}
          {notice.link ? (
            <Link href={notice.link}>
              <b>افتح ↗</b>
            </Link>
          ) : null}
        </div>
      ) : null}

      <div className="card advisor-hero">
        <div className="grow">
          <span className="tag">تحليل رحلتك كاملة</span>
          <div className="advisor-headline">{data.headline}</div>
          <div className="chip-row">
            <span className="chip">
              🔥 سلسلتك {data.context.streak} يوم
            </span>
            {data.context.next_exam ? (
              <span className="chip bad">
                📅 {data.context.next_exam.title} — باقي {data.context.next_exam.days_left} يوم
              </span>
            ) : null}
            <span className="chip">{data.context.daily_study_minutes} دقيقة يومياً</span>
          </div>
        </div>
        <div className={`kpi ${healthClass(data.plan_health)}`}>
          <b>{data.plan_health.completion !== null ? `${Math.round(data.plan_health.completion * 100)}%` : "—"}</b>
          <span>إنجاز خطتك</span>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={tab === item.key ? "on" : ""}
            onClick={() => setTab(item.key)}
          >
            {item.label}
            {item.key === "problems" && problems.length ? ` (${problems.length})` : ""}
          </button>
        ))}
      </div>

      {tab === "status" ? (
        <StatusTab data={data} report={report} />
      ) : tab === "problems" ? (
        <ProblemsTab problems={problems} busy={busy} onApply={apply} />
      ) : tab === "steps" ? (
        <StepsTab data={data} busy={busy} onApply={apply} />
      ) : (
        <WeekTab weekly={data.weekly} />
      )}
    </div>
  );
}

function healthClass(health) {
  if (health.overloaded) return "danger";
  if (health.completion !== null && health.completion >= 0.75) return "";
  return "";
}

function StatusTab({ data, report }) {
  const context = data.context;
  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>صورة المواد</h3>
          <span className="tag">{report.subjects.length} مواد مُختارة</span>
        </div>
        {report.subjects.length ? (
          report.subjects.map((subject) => (
            <div key={subject.subject_id} className="factor" style={{ marginBottom: 10 }}>
              <div className="row">
                <span className="grow">
                  <b>{subject.name_ar}</b>{" "}
                  <span className="muted" style={{ fontSize: 13 }}>
                    {subject.mastery !== null ? `تحكّم ${subject.mastery}%` : "لا يوجد تحكّم بعد"}
                    {subject.weak_topics ? ` — ${subject.weak_topics} مواضيع ضعيفة` : ""}
                  </span>
                </span>
                <span className="tag">
                  {subject.readiness?.band === "ready"
                    ? "جاهز"
                    : subject.readiness?.band === "ready_with_work"
                      ? "جاهز بشرط"
                      : subject.readiness?.band === "not_ready"
                        ? "يحتاج عملاً"
                        : subject.readiness?.band === "weak"
                          ? "يحتاج تأسيساً"
                          : "بلا بيانات"}
                </span>
              </div>
              <div className="bar">
                <span style={{ width: `${Math.round(subject.readiness?.score ?? subject.score ?? 0)}%` }} />
              </div>
            </div>
          ))
        ) : (
          <div className="empty">ما أضفت موادك بعد — أضفها من الإعدادات لتبدأ.</div>
        )}

        <div className="chip-row">
          {report.strong_subjects.map((item) => (
            <span key={item.subject_id} className="chip good">
              ✅ {item.name_ar} {item.score}%
            </span>
          ))}
          {report.weak_subjects.map((item) => (
            <span key={item.subject_id} className="chip bad">
              ⚠️ {item.name_ar} {item.score}%
            </span>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>أولوياتك هذا الأسبوع</h3>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          {data.priorities.message}
        </p>
        {data.priorities.subjects.map((row) => (
          <div key={row.subject_id} style={{ marginBottom: 10 }}>
            <div className="row">
              <span className="grow">
                <b>
                  {row.rank}. {row.name_ar}
                </b>{" "}
                <span className="muted" style={{ fontSize: 13 }}>
                  {row.weak_topics ? `${row.weak_topics} مواضيع ضعيفة` : ""}
                  {row.days_to_exam !== null && row.days_to_exam !== undefined
                    ? ` — امتحان بعد ${row.days_to_exam} يوم`
                    : ""}
                </span>
              </span>
              <span className="tag">{row.share}%</span>
            </div>
            <div className="bar">
              <span style={{ width: `${row.share}%` }} />
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>أهدافك</h3>
        </div>
        <p style={{ marginTop: 0 }}>
          {context.goal || "ما حددت هدفاً بعد — حدّده من صفحة الإعدادات ليقيسك عليه المرشد."}
        </p>
        <div className="chip-row">
          {context.subjects.map((subject) => (
            <span key={subject.id} className="chip">
              {subject.name_ar}
            </span>
          ))}
        </div>
        {context.stuck_at.length ? (
          <div className="chip-row">
            <span className="chip bad">تتعثر في: {context.stuck_at.join("، ")}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ProblemsTab({ problems, busy, onApply }) {
  if (!problems.length)
    return (
      <div className="card">
        <div className="empty">
          ما شفت مشاكل واضحة ببياناتك — كمّل نسقك الحالي ورجع بعد أسبوع.
        </div>
      </div>
    );
  return (
    <div>
      {problems.map((problem) => (
        <div key={problem.key} className={`problem ${problem.severity}`}>
          <div className="problem-head">
            <h4>{problem.title}</h4>
            <span className={`tag ${problem.severity === "high" ? "warn" : problem.severity === "low" ? "ok" : ""}`}>
              {problem.severity === "high" ? "عاجل" : problem.severity === "medium" ? "مهم" : "خفيف"}
            </span>
          </div>
          {problem.evidence.length ? (
            <ul className="evidence">
              {problem.evidence.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
          <div className="solution">
            <b>الحل: </b>
            {problem.solution}
          </div>
          <div className="row">
            <button
              className="btn sm"
              disabled={busy === problem.action_key}
              onClick={() => onApply(problem.action_key)}
            >
              {busy === problem.action_key ? "جاري التطبيق…" : problem.action_label}
            </button>
            {problem.requires_approval ? <span className="tag">يتطلب موافقتك</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function StepsTab({ data, busy, onApply }) {
  const health = data.plan_health;
  return (
    <div className="stack">
      <div className={`card ${health.overloaded ? "problem high" : ""}`}>
        <div className="card-title">
          <h3>صحة جدولك</h3>
          <span className={`tag ${health.overloaded ? "warn" : "ok"}`}>
            {health.available ? (health.realistic ? "واقعي" : "مثقل") : "بلا خطة"}
          </span>
        </div>
        <p style={{ marginTop: 0 }}>{health.message}</p>
        {health.suggestion ? (
          <p className="muted" style={{ marginTop: -6 }}>
            {health.suggestion}
          </p>
        ) : null}
      </div>

      {data.steps.map((step) => (
        <div key={step.key} className={`step ${step.available ? "" : "off"}`}>
          <div className="grow">
            <h4>{step.title}</h4>
            <p>{step.detail}</p>
            <div className="row" style={{ marginTop: 8 }}>
              {step.requires_approval ? <span className="tag">يتطلب موافقتك</span> : null}
              {!step.available ? <span className="tag">غير متاح بعد</span> : null}
            </div>
          </div>
          <button
            className="btn sm"
            disabled={!step.available || busy === step.key}
            onClick={() => onApply(step.key)}
          >
            {busy === step.key ? "جاري التطبيق…" : "طبّق"}
          </button>
        </div>
      ))}
    </div>
  );
}

function WeekTab({ weekly }) {
  const improveClass =
    weekly.improvement === "up" ? "improve-up" : weekly.improvement === "down" ? "improve-down" : "";
  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>ملخص أسبوعك</h3>
          <span className="tag">{IMPROVEMENT[weekly.improvement]}</span>
        </div>
        <div className="kpis">
          <div className="kpi">
            <b>{weekly.study_hours}</b>
            <span>ساعة دراسة</span>
          </div>
          <div className="kpi">
            <b>{weekly.completed_lessons}</b>
            <span>درس مُنجز</span>
          </div>
          <div className="kpi">
            <b>{weekly.quiz_average !== null ? `${weekly.quiz_average}%` : "—"}</b>
            <span>متوسط الاختبارات</span>
          </div>
          <div className="kpi">
            <b className={improveClass}>{IMPROVEMENT[weekly.improvement]}</b>
            <span>اتجاه التحسّن</span>
          </div>          <div className="kpi">
            <b>{weekly.missed_sessions}</b>
            <span>جلسة فائتة</span>
          </div>
          <div className="kpi">
            <b>
              +{weekly.mastery_changes.improved}/{weekly.mastery_changes.dropped}
            </b>
            <span>تحكّم تحسّن/تراجع</span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>خطة الأسبوع القادم</h3>
        </div>
        <ul className="week-plan">
          {weekly.next_week_plan.map((item) => (
            <li key={item.title}>
              <b>{item.title}</b> — {item.minutes} دقيقة
              <div className="why">{item.reason}</div>
            </li>
          ))}
        </ul>
      </div>

      {weekly.weak_topics.length ? (
        <div className="card">
          <div className="card-title">
            <h3>مواضع ضعيفة هذا الأسبوع</h3>
          </div>
          <div className="chip-row">
            {weekly.weak_topics.map((topic, index) => (
              <span key={`${topic.topic}-${index}`} className="chip bad">
                {topic.topic} × {topic.errors}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
