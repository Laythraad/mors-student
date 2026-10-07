"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";

const STEPS = [
  { key: "stage", label: "المرحلة" },
  { key: "subjects", label: "موادك" },
  { key: "schedule", label: "جدولك" },
  { key: "diagnostic", label: "تشخيص" },
  { key: "plan", label: "خطتك" },
];

export default function OnboardingPage() {
  return (
    <Shell title="الإعداد الأول">
      <OnboardingBody />
    </Shell>
  );
}

function OnboardingBody() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [stages, setStages] = useState([]);
  const [branches, setBranches] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [stageId, setStageId] = useState("");
  const [branchId, setBranchId] = useState("");
  const [picked, setPicked] = useState([]);
  const [schedule, setSchedule] = useState({
    school_start: "08:00",
    school_end: "14:00",
    sleep_start: "23:00",
    sleep_end: "07:00",
    daily_study_minutes: 90,
    study_days: [0, 1, 2, 3, 4],
    free_windows: [{ start: "16:00", end: "19:00" }],
  });
  const [diagnostic, setDiagnostic] = useState(null);
  const [plan, setPlan] = useState(null);

  useEffect(() => {
    api("/api/curriculum/stages")
      .then((data) => setStages(data.stages || []))
      .catch((err) => setError(errorMessage(err)));
  }, []);

  useEffect(() => {
    if (!stageId) return;
    api("/api/curriculum/branches", { query: { stage_id: stageId } })
      .then((data) => setBranches(data.branches || []))
      .catch(() => setBranches([]));
  }, [stageId]);

  useEffect(() => {
    if (!branchId) return;
    api("/api/curriculum/subjects", { query: { branch_id: branchId } })
      .then((data) => setSubjects(data.subjects || []))
      .catch(() => setSubjects([]));
  }, [branchId]);

  async function next(action) {
    setError("");
    setBusy(true);
    try {
      await action();
      setStep((s) => Math.min(STEPS.length - 1, s + 1));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const saveStage = () =>
    next(async () => {
      await api("/api/auth/profile", {
        method: "PATCH",
        body: { stage_id: stageId, branch_id: branchId || null },
      });
      await api("/api/onboarding/step/stage", { method: "POST" });
      const rec = await api("/api/onboarding/recommend");
      setPicked((rec.subjects || []).filter((s) => s.chosen).map((s) => s.id));
    });

  const saveSubjects = () =>
    next(async () => {
      await api("/api/auth/subjects", { method: "PUT", body: { subject_ids: picked } });
      await api("/api/onboarding/step/subjects", { method: "POST" });
    });

  const saveSchedule = () =>
    next(async () => {
      await api("/api/onboarding/schedule", { method: "PUT", body: schedule });
      await api("/api/onboarding/step/schedule", { method: "POST" });
    });

  const runDiagnostic = (count) =>
    next(async () => {
      const result = await api("/api/onboarding/diagnostic", {
        method: "POST",
        body: { count },
      });
      setDiagnostic(result);
    });

  const buildPlan = () =>
    next(async () => {
      const result = await api("/api/onboarding/first-plan", { method: "POST" });
      setPlan(result);
      await api("/api/onboarding/step/plan", { method: "POST" });
    });

  const current = STEPS[step];

  return (
    <div className="stack">
      <div className="steps">
        {STEPS.map((s, i) => (
          <span key={s.key} className={i <= step ? "on" : ""} />
        ))}
      </div>

      {error ? <div className="error-box">{error}</div> : null}

      <div className="card">
        <div className="card-title">
          <h3>
            {step + 1}. {current.label}
          </h3>
          <span className="tag">{step + 1}/{STEPS.length}</span>
        </div>

        {current.key === "stage" ? (
          <div className="stack">
            <div className="field">
              <label>المرحلة الدراسية</label>
              <select className="select" value={stageId} onChange={(e) => setStageId(e.target.value)}>
                <option value="">اختر مرحلتك…</option>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name_ar}
                  </option>
                ))}
              </select>
            </div>
            {branches.length ? (
              <div className="field">
                <label>الفرع</label>
                <select
                  className="select"
                  value={branchId}
                  onChange={(e) => setBranchId(e.target.value)}
                >
                  <option value="">اختر فرعك…</option>
                  {branches.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name_ar}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <button className="btn" disabled={!stageId || busy} onClick={saveStage}>
              التالي
            </button>
          </div>
        ) : null}

        {current.key === "subjects" ? (
          <div className="stack">
            <p className="muted small">اختر موادك — نقترحها حسب مرحلتك وفرعك.</p>
            <div className="row wrap">
              {subjects.map((s) => {
                const on = picked.includes(s.id);
                return (
                  <button
                    key={s.id}
                    className={`chip ${on ? "on" : ""}`}
                    onClick={() =>
                      setPicked((prev) => (on ? prev.filter((x) => x !== s.id) : [...prev, s.id]))
                    }
                  >
                    <span>{s.icon}</span> {s.name_ar}
                  </button>
                );
              })}
            </div>
            <button className="btn" disabled={!picked.length || busy} onClick={saveSubjects}>
              حفظ واختيار
            </button>
          </div>
        ) : null}

        {current.key === "schedule" ? (
          <div className="stack">
            <div className="grid cols-2">
              <div className="field">
                <label>بداية الدوام</label>
                <input
                  className="input"
                  type="time"
                  value={schedule.school_start}
                  onChange={(e) => setSchedule({ ...schedule, school_start: e.target.value })}
                />
              </div>
              <div className="field">
                <label>نهاية الدوام</label>
                <input
                  className="input"
                  type="time"
                  value={schedule.school_end}
                  onChange={(e) => setSchedule({ ...schedule, school_end: e.target.value })}
                />
              </div>
              <div className="field">
                <label>موعد النوم</label>
                <input
                  className="input"
                  type="time"
                  value={schedule.sleep_start}
                  onChange={(e) => setSchedule({ ...schedule, sleep_start: e.target.value })}
                />
              </div>
              <div className="field">
                <label>موعد الاستيقاظ</label>
                <input
                  className="input"
                  type="time"
                  value={schedule.sleep_end}
                  onChange={(e) => setSchedule({ ...schedule, sleep_end: e.target.value })}
                />
              </div>
            </div>
            <div className="field">
              <label>دقائق الدراسة اليومية: {schedule.daily_study_minutes}</label>
              <input
                type="range"
                min={30}
                max={300}
                step={15}
                value={schedule.daily_study_minutes}
                onChange={(e) =>
                  setSchedule({ ...schedule, daily_study_minutes: Number(e.target.value) })
                }
              />
            </div>
            <div className="row wrap">
              {["أحد", "اثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت"].map((d, i) => {
                const on = schedule.study_days.includes(i);
                return (
                  <button
                    key={d}
                    className={`chip ${on ? "on" : ""}`}
                    onClick={() =>
                      setSchedule({
                        ...schedule,
                        study_days: on
                          ? schedule.study_days.filter((x) => x !== i)
                          : [...schedule.study_days, i],
                      })
                    }
                  >
                    {d}
                  </button>
                );
              })}
            </div>
            <button className="btn" disabled={busy} onClick={saveSchedule}>
              حفظ الجدول
            </button>
          </div>
        ) : null}

        {current.key === "diagnostic" ? (
          <div className="stack">
            {!diagnostic ? (
              <>
                <p className="muted">
                  اختبار تشخيصي قصير يحدّد مستوى كل مادة — يساعدنا نرتّب أولوياتك.
                </p>
                <div className="row wrap">
                  <button className="btn" disabled={busy} onClick={() => runDiagnostic(10)}>
                    ابدأ التشخيص (١٠ أسئلة)
                  </button>
                  <button className="btn ghost" disabled={busy} onClick={() => next(async () => {})}>
                    تخطّي
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="success-box">
                  أنشأنا لك اختباراً تشخيصياً: {diagnostic.question_count} أسئلة.
                </div>
                <Link className="btn" href={`/quiz/${diagnostic.id}`}>
                  ابدأ الاختبار التشخيصي
                </Link>
              </>
            )}
          </div>
        ) : null}

        {current.key === "plan" ? (
          <div className="stack">
            {!plan ? (
              <>
                <p className="muted">نبني لك خطة أسبوعية حسب موادك ووقتك المتاح.</p>
                <button className="btn" disabled={busy} onClick={buildPlan}>
                  أنشئ خطتي
                </button>
              </>
            ) : (
              <>
                <div className="success-box">جاهزة! {plan.days?.length || 0} أيام مرتّبة لك.</div>
                <div className="row wrap">
                  <Link className="btn" href="/plan">
                    افتح خطتي
                  </Link>
                  <Link className="btn ghost" href="/home">
                    الرئيسية
                  </Link>
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>

      <div className="row between">
        <button className="btn ghost" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          رجوع
        </button>
        <Link className="btn soft" href="/home">
          تخطّي للتطبيق
        </Link>
      </div>
    </div>
  );
}
