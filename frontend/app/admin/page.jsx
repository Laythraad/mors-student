"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtShortDate } from "@/lib/api";

const TABS = [
  { key: "stats", label: "الإحصاءات" },
  { key: "publish", label: "نشر المحتوى" },
  { key: "scheduler", label: "المجدول" },
  { key: "prompts", label: "برومبتات الذكاء" },
  { key: "usage", label: "استهلاك AI" },
  { key: "flags", label: "بلاغات الأسئلة" },
  { key: "events", label: "الأحداث" },
  { key: "users", label: "المستخدمون" },
  { key: "settings", label: "إعدادات المنصة" },
];

const FLAG_LABELS = {
  wrong_answer: "الإجابة المعتمَدة غير صحيحة",
  unclear: "صياغة غير واضحة",
  bad_options: "خيارات غير مناسبة",
  other: "سبب آخر",
};

export default function AdminPage() {
  return (
    <Shell title="لوحة الإدارة">
      <AdminBody />
    </Shell>
  );
}

function AdminBody() {
  const [tab, setTab] = useState("stats");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "stats" ? <Stats onError={setError} /> : null}
      {tab === "publish" ? <Publish onError={setError} onNotice={setNotice} /> : null}
      {tab === "scheduler" ? <Scheduler onError={setError} onNotice={setNotice} /> : null}
      {tab === "prompts" ? <Prompts onError={setError} onNotice={setNotice} /> : null}
      {tab === "usage" ? <Usage onError={setError} /> : null}
      {tab === "flags" ? <QuestionFlags onError={setError} onNotice={setNotice} /> : null}
      {tab === "events" ? <Events onError={setError} /> : null}
      {tab === "users" ? <Users onError={setError} onNotice={setNotice} /> : null}
      {tab === "settings" ? <Settings onError={setError} onNotice={setNotice} /> : null}
    </div>
  );
}

function Stats({ onError }) {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    api("/api/admin/stats")
      .then(setStats)
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  if (!stats) return <div className="loading-page"><div className="spinner" /></div>;
  const items = [
    ["المراتح", stats.stages],
    ["المواد", stats.subjects],
    ["الكتب", stats.books],
    ["الفصول", stats.chapters],
    ["الوحدات", stats.units],
    ["الدروس", stats.lessons],
    ["المستخدمون", stats.users],
    ["الرفوف المفهرسة", stats.chunks],
    ["الملفات المرفوعة", stats.uploads],
    ["وحدات فارغة", stats.empty_units],
  ];
  return (
    <div className="grid cols-3">
      {items.map(([label, value]) => (
        <div className="stat" key={label}>
          <div className="value">{value}</div>
          <div className="label">{label}</div>
        </div>
      ))}
    </div>
  );
}

function Prompts({ onError, onNotice }) {
  const [prompts, setPrompts] = useState([]);
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(() => {
    api("/api/admin/prompts")
      .then((d) => setPrompts(d.prompts || []))
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function save(key) {
    try {
      await api(`/api/admin/prompts/${key}`, { method: "PUT", body: { template: draft } });
      setEditing(null);
      onNotice("حُفظ البرومبت (نسخة جديدة).");
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  async function reset(key) {
    try {
      await api(`/api/admin/prompts/${key}`, { method: "DELETE" });
      onNotice("أُعيد للنسخة الأصلية.");
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  return (
    <div className="stack">
      {prompts.map((p) => (
        <div className="card" key={p.key}>
          <div className="card-title">
            <h3>{p.name_ar || p.name}</h3>
            <span className="row">
              <span className={`tag ${p.overridden ? "" : "ok"}`}>
                {p.overridden ? `معدّل · v${p.version}` : "أصلي"}
              </span>
              <button
                className="btn ghost sm"
                onClick={() => {
                  setEditing(p.key);
                  setDraft(p.template);
                }}
              >
                تعديل
              </button>
              {p.overridden ? (
                <button className="btn ghost sm" onClick={() => reset(p.key)}>
                  إعادة
                </button>
              ) : null}
            </span>
          </div>
          {editing === p.key ? (
            <>
              <textarea
                className="textarea"
                style={{ minHeight: 220, fontFamily: "monospace", direction: "ltr" }}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn sm" onClick={() => save(p.key)}>
                  حفظ
                </button>
                <button className="btn ghost sm" onClick={() => setEditing(null)}>
                  إلغاء
                </button>
              </div>
            </>
          ) : (
            <pre
              className="small muted"
              style={{ whiteSpace: "pre-wrap", margin: 0, maxHeight: 140, overflow: "hidden" }}
            >
              {p.template.slice(0, 400)}…
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

function Usage({ onError }) {
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    api("/api/admin/usage", { query: { days: 7 } })
      .then(setUsage)
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  if (!usage) return <div className="loading-page"><div className="spinner" /></div>;

  return (
    <div className="stack">
      <div className="grid cols-3">
        <div className="stat">
          <div className="value">{usage.requests}</div>
          <div className="label">طلبات AI (7 أيام)</div>
        </div>
        <div className="stat">
          <div className="value">{usage.prompt_tokens}</div>
          <div className="label">توكنات إدخال</div>
        </div>
        <div className="stat">
          <div className="value">{usage.completion_tokens}</div>
          <div className="label">توكنات إخراج</div>
        </div>
      </div>
      <div className="card">
        <div className="card-title">
          <h3>حسب اليوم</h3>
          <span className="tag">المزود: {usage.provider}</span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>اليوم</th>
              <th>الطلبات</th>
              <th>إدخال</th>
              <th>إخراج</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(usage.by_day || {}).map(([day, data]) => (
              <tr key={day}>
                <td>{day}</td>
                <td>{data.requests}</td>
                <td>{data.prompt_tokens}</td>
                <td>{data.completion_tokens}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Events({ onError }) {
  const [events, setEvents] = useState([]);
  useEffect(() => {
    api("/api/admin/events", { query: { limit: 60 } })
      .then((d) => setEvents(d.events || []))
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  return (
    <div className="card">
      <table className="table">
        <thead>
          <tr>
            <th>الحدث</th>
            <th>المصدر</th>
            <th>المعالجات</th>
            <th>الوقت</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{e.type}</td>
              <td>{e.source}</td>
              <td>{(e.handled || []).join(", ")}</td>
              <td className="small muted">{fmtShortDate(e.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!events.length ? <div className="empty">لا أحداث.</div> : null}
    </div>
  );
}

function QuestionFlags({ onError, onNotice }) {
  const [flags, setFlags] = useState([]);
  const load = useCallback(() => {
    api("/api/admin/question-flags", { query: { status: "open" } })
      .then((d) => setFlags(d.flags || []))
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function resolve(flag) {
    try {
      await api(`/api/admin/question-flags/${flag.id}/resolve`, { method: "POST" });
      onNotice("أُغلق البلاغ.");
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        <h3>بلاغات الطلاب عن الأسئلة</h3>
        <span className="tag">{flags.length} مفتوح</span>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>السؤال</th>
            <th>السبب</th>
            <th>الطالب</th>
            <th>تفاصيل</th>
            <th>الوقت</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {flags.map((f) => (
            <tr key={f.id}>
              <td>{(f.question && f.question.prompt) || "\u2014"}</td>
              <td>{FLAG_LABELS[f.kind] || f.kind}</td>
              <td>{f.student || "\u2014"}</td>
              <td className="small muted">{f.detail || "\u2014"}</td>
              <td className="small muted">{fmtShortDate(f.created_at)}</td>
              <td>
                <button className="btn ghost sm" onClick={() => resolve(f)}>
                  إغلاق
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!flags.length ? <div className="empty">لا بلاغات مفتوحة.</div> : null}
    </div>
  );
}

function Users({ onError, onNotice }) {
  const [users, setUsers] = useState([]);
  const load = useCallback(() => {
    api("/api/admin/users")
      .then((d) => setUsers(d.users || []))
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggle(user) {
    try {
      await api(`/api/admin/users/${user.id}`, {
        method: "PATCH",
        body: { is_active: !user.is_active },
      });
      onNotice("حُدّث الحساب.");
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  return (
    <div className="card">
      <table className="table">
        <thead>
          <tr>
            <th>الاسم</th>
            <th>البريد</th>
            <th>الصلاحية</th>
            <th>الحالة</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.full_name}</td>
              <td dir="ltr" className="small">{u.email}</td>
              <td>{u.role}</td>
              <td>{u.is_active ? "نشط" : "معطّل"}</td>
              <td>
                <button className="btn ghost sm" onClick={() => toggle(u)}>
                  {u.is_active ? "تعطيل" : "تفعيل"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Settings({ onError, onNotice }) {
  const [key, setKey] = useState("demo_banner");
  const [value, setValue] = useState("");
  const [current, setCurrent] = useState(null);

  async function get() {
    try {
      const data = await api(`/api/admin/settings/${key}`);
      setCurrent(data.value);
      setValue(typeof data.value === "string" ? data.value : JSON.stringify(data.value));
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  async function put() {
    try {
      let parsed = value;
      try {
        parsed = JSON.parse(value);
      } catch {
        /* keep as string */
      }
      const data = await api(`/api/admin/settings/${key}`, {
        method: "PUT",
        body: { value: parsed },
      });
      setCurrent(data.value);
      onNotice("حُفظ الإعداد.");
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  return (
    <div className="card">
      <div className="field">
        <label>مفتاح الإعداد</label>
        <input className="input" dir="ltr" value={key} onChange={(e) => setKey(e.target.value)} />
      </div>
      <div className="field">
        <label>القيمة (JSON أو نص)</label>
        <textarea
          className="textarea"
          dir="ltr"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </div>
      <div className="row">
        <button className="btn ghost" onClick={get}>
          جلب
        </button>
        <button className="btn" onClick={put}>
          حفظ
        </button>
      </div>
      {current !== null ? (
        <div className="divider" />
      ) : null}
      {current !== null ? (
        <pre className="small muted" style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(current, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

const ENTITY_OPTIONS = [
  ["lesson", "درس"],
  ["chapter", "فصل"],
  ["unit", "وحدة"],
  ["subject", "مادة"],
  ["source", "مصدر"],
  ["teacher", "معلم"],
  ["video", "فيديو"],
  ["course", "كورس"],
];

const ENTITY_FIELDS = {
  lesson: [{ k: "subject_id", label: "معرّف المادة", req: true }],
  chapter: [{ k: "book_id", label: "معرّف الكتاب", req: true }],
  unit: [{ k: "chapter_id", label: "معرّف الفصل", req: true }],
  subject: [
    { k: "branch_id", label: "معرّف الفرع", req: true },
    { k: "code", label: "رمز المادة", req: true },
  ],
  source: [{ k: "url", label: "الرابط", req: false }],
  teacher: [],
  video: [{ k: "url", label: "رابط الفيديو", req: true }],
  course: [],
};

const STATUS_AR = {
  draft: "مسودة",
  processing: "معالجة",
  validated: "تم التحقق",
  scheduled: "مجدول",
  published: "منشور",
  rejected: "مرفوض",
};

const STATUS_CLS = {
  draft: "",
  processing: "",
  validated: "ok",
  scheduled: "warn",
  published: "ok",
  rejected: "bad",
};

function Publish({ onError, onNotice }) {
  const [drafts, setDrafts] = useState([]);
  const [entity, setEntity] = useState("lesson");
  const [title, setTitle] = useState("");
  const [fields, setFields] = useState({});
  const [extra, setExtra] = useState("");
  const [sched, setSched] = useState({});

  const load = useCallback(() => {
    api("/api/admin/drafts", { query: { limit: 100 } })
      .then((d) => setDrafts(d.drafts || []))
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function act(path, body, msg) {
    try {
      await api(path, body);
      onNotice(msg);
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  async function create() {
    let extras = {};
    if (extra.trim()) {
      try {
        extras = JSON.parse(extra);
      } catch {
        onError("حقول JSON الإضافية غير صالحة.");
        return;
      }
    }
    const payload = { ...extras };
    if (title.trim()) payload.title = title.trim();
    for (const def of ENTITY_FIELDS[entity] || []) {
      const value = (fields[def.k] || "").trim();
      if (value) payload[def.k] = value;
    }
    try {
      await api("/api/admin/drafts", {
        method: "POST",
        body: { entity, payload, title: title.trim() || undefined },
      });
      onNotice("أُنشئت المسودة — نفّذ المعالجة ثم المراجعة.");
      setTitle("");
      setFields({});
      setExtra("");
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  function schedule(d) {
    const when = sched[d.id];
    if (!when) {
      onError("حدد وقت النشر أولاً.");
      return;
    }
    act(
      `/api/admin/drafts/${d.id}/review`,
      { method: "POST", body: { approve: true, publish_at: new Date(when).toISOString() } },
      "جُدول النشر — سينشره المجدول تلقائياً."
    );
  }

  const defs = ENTITY_FIELDS[entity] || [];

  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>مسودة جديدة</h3>
          <span className="tag">Draft → Published</span>
        </div>
        <div className="field">
          <label>نوع المحتوى</label>
          <select
            className="input"
            value={entity}
            onChange={(e) => {
              setEntity(e.target.value);
              setFields({});
            }}
          >
            {ENTITY_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>العنوان *</label>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="عنوان المحتوى"
          />
        </div>
        {defs.map((def) => (
          <div className="field" key={def.k}>
            <label>
              {def.label}
              {def.req ? " *" : ""}
            </label>
            <input
              className="input"
              dir="ltr"
              value={fields[def.k] || ""}
              onChange={(e) => setFields((f) => ({ ...f, [def.k]: e.target.value }))}
            />
          </div>
        ))}
        <div className="field">
          <label>حقول إضافية (JSON اختياري — مثلاً summary / difficulty)</label>
          <textarea
            className="textarea"
            dir="ltr"
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            placeholder='{"summary": "...", "difficulty": 3}'
          />
        </div>
        <div className="row">
          <button className="btn" onClick={create}>
            إنشاء مسودة
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>طابور النشر</h3>
          <span className="tag">{drafts.length}</span>
        </div>
        {!drafts.length ? <div className="empty">لا مسودات بعد.</div> : null}
        {drafts.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>العنوان</th>
                <th>النوع</th>
                <th>الحالة</th>
                <th>النشر</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => (
                <tr key={d.id}>
                  <td>
                    <strong>{d.title}</strong>
                    {d.issues && d.issues.length ? (
                      <div className="small" style={{ color: "var(--danger)" }}>
                        {d.issues.join(" · ")}
                      </div>
                    ) : null}
                    {d.ai_notes && d.status !== "published" ? (
                      <div className="small muted" style={{ maxHeight: 56, overflow: "hidden" }}>
                        {d.ai_notes}
                      </div>
                    ) : null}
                    {d.entity_id ? (
                      <div className="small muted" dir="ltr">
                        #{d.entity_id}
                      </div>
                    ) : null}
                  </td>
                  <td>{(ENTITY_OPTIONS.find(([v]) => v === d.entity) || [d.entity, d.entity])[1]}</td>
                  <td>
                    <span className={`tag ${STATUS_CLS[d.status] || ""}`}>
                      {STATUS_AR[d.status] || d.status}
                    </span>
                  </td>
                  <td className="small muted">
                    {d.status === "scheduled" && d.publish_at
                      ? new Date(d.publish_at).toLocaleString("ar-IQ")
                      : d.published_at
                        ? new Date(d.published_at).toLocaleString("ar-IQ")
                        : "—"}
                  </td>
                  <td>
                    <span className="row">
                      {d.status === "draft" || d.status === "rejected" ? (
                        <button
                          className="btn sm"
                          onClick={() =>
                            act(
                              `/api/admin/drafts/${d.id}/process`,
                              { method: "POST" },
                              "نُفّذت المعالجة والتحقق."
                            )
                          }
                        >
                          معالجة
                        </button>
                      ) : null}
                      {d.status === "validated" || d.status === "scheduled" ? (
                        <>
                          <button
                            className="btn sm"
                            onClick={() =>
                              act(
                                `/api/admin/drafts/${d.id}/review`,
                                { method: "POST", body: { approve: true, note: "نشر مباشر" } },
                                "نُشر المحتوى."
                              )
                            }
                          >
                            نشر الآن
                          </button>
                          <input
                            type="datetime-local"
                            className="input"
                            style={{ maxWidth: 190 }}
                            value={sched[d.id] || ""}
                            onChange={(e) => setSched((s) => ({ ...s, [d.id]: e.target.value }))}
                          />
                          <button className="btn ghost sm" onClick={() => schedule(d)}>
                            جدولة
                          </button>
                          <button
                            className="btn ghost sm"
                            onClick={() =>
                              act(
                                `/api/admin/drafts/${d.id}/review`,
                                { method: "POST", body: { approve: false, note: "يحتاج تعديل" } },
                                "رُفضت المسودة."
                              )
                            }
                          >
                            رفض
                          </button>
                        </>
                      ) : null}
                      {d.status !== "published" && d.status !== "processing" ? (
                        <button
                          className="btn ghost sm"
                          onClick={() =>
                            act(`/api/admin/drafts/${d.id}`, { method: "DELETE" }, "حُذفت المسودة.")
                          }
                        >
                          حذف
                        </button>
                      ) : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </div>
  );
}

function Scheduler({ onError, onNotice }) {
  const [data, setData] = useState(null);

  const load = useCallback(() => {
    api("/api/admin/scheduler")
      .then(setData)
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(name) {
    try {
      const res = await api(`/api/admin/scheduler/${name}/run`, { method: "POST" });
      if (res.status === "ok") onNotice(`نجحت المهمة: ${name}`);
      else onError(`فشلت المهمة (${name}): ${res.error || "خطأ غير معروف"}`);
      load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  if (!data) return <div className="loading-page"><div className="spinner" /></div>;

  return (
    <div className="stack">
      <div className="card">
        <div className="card-title">
          <h3>المهام الخلفية</h3>
          <span className={`tag ${data.enabled ? "ok" : "warn"}`}>
            {data.enabled ? "مفعّل" : "متوقف"}
          </span>
        </div>
        <p className="small muted">
          يفحص المجدول المهام المستحقة تلقائياً كل {data.interval_seconds} ثانية، ويمكن تشغيل أي
          مهمة يدوياً الآن.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>المهمة</th>
              <th>الوصف</th>
              <th>الفاصل</th>
              <th>آخر تشغيل</th>
              <th>الحالة</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(data.jobs || []).map((job) => (
              <tr key={job.name}>
                <td dir="ltr" className="small">
                  {job.name}
                </td>
                <td>{job.description}</td>
                <td className="small">
                  {job.interval_seconds >= 60
                    ? `${Math.round(job.interval_seconds / 60)} دقيقة`
                    : `${job.interval_seconds} ثانية`}
                </td>
                <td className="small muted">
                  {job.last_run_at
                    ? new Date(job.last_run_at).toLocaleString("ar-IQ")
                    : "لم يُشغّل بعد"}
                </td>
                <td>
                  {job.last_status ? (
                    <span className={`tag ${job.last_status === "ok" ? "ok" : "bad"}`}>
                      {job.last_status === "ok" ? "نجح" : "فشل"}
                    </span>
                  ) : (
                    <span className="tag">—</span>
                  )}
                </td>
                <td>
                  <button className="btn sm" onClick={() => run(job.name)}>
                    شغّل الآن
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
