"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage, fmtShortDate } from "@/lib/api";

const STATUS_LABELS = {
  due: "حان وقته",
  snoozed: "مؤجَّل",
  done: "منجز",
  pending: "قادم",
};

function toLocalInput(value) {
  const d = value instanceof Date ? value : new Date(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function fmtDue(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString("ar-IQ", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(value);
  }
}

export default function InboxPage() {
  return (
    <Shell title="الإشعارات">
      <InboxBody />
    </Shell>
  );
}

function InboxBody() {
  const [notifications, setNotifications] = useState([]);
  const [history, setHistory] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [n, h, p] = await Promise.all([
        api("/api/inbox/notifications"),
        api("/api/inbox/mors/history", { query: { limit: 30 } }),
        api("/api/inbox/delivery-policy"),
      ]);
      setNotifications(n.notifications || []);
      setHistory(h.messages || []);
      setPolicy(p);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function markAll() {
    try {
      await api("/api/inbox/notifications/read", { method: "POST", body: { all: true } });
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}

      {policy ? (
        <div className="card">
          <div className="row wrap">
            <span className={`chip ${policy.focus_mode ? "on" : ""}`}>
              وضع التركيز: {policy.focus_mode ? "تشغيل" : "إيقاف"}
            </span>
            <span className={`chip ${policy.quiet ? "on" : ""}`}>
              ساعات الهدوء: {policy.quiet_hours[0]}:00–{policy.quiet_hours[1]}:00
            </span>
            <span className="chip">التنبيهات مسموحة: {policy.can_nudge ? "نعم" : "لا"}</span>
          </div>
        </div>
      ) : null}

      <Reminders onError={setError} />

      <div className="card">
        <div className="card-title">
          <h3>الإشعارات</h3>
          <button className="btn ghost sm" onClick={markAll}>
            تعليم الكل كمقروء
          </button>
        </div>
        <div className="list">
          {notifications.map((n) => (
            <div className="list-item" key={n.id} style={{ opacity: n.read_at ? 0.6 : 1 }}>
              <div className="grow">
                <div className="title">{n.title}</div>
                <div className="small muted">{n.body}</div>
                <div className="small muted">{fmtShortDate(n.created_at)}</div>
              </div>
              <span className="tag">{n.kind}</span>
            </div>
          ))}
          {!notifications.length ? <div className="empty">لا إشعارات.</div> : null}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>رسائل مورس</h3>
        </div>
        <div className="list">
          {history.map((m) => (
            <div className="list-item" key={m.id}>
              <img src={m.sprite} alt={m.expression} width={44} height={44} style={{ borderRadius: "50%" }} />
              <div className="grow">
                <div className="title small">{m.text}</div>
                <div className="small muted">
                  {m.tone} · {fmtShortDate(m.created_at)}
                </div>
              </div>
            </div>
          ))}
          {!history.length ? <div className="empty">لا رسائل بعد.</div> : null}
        </div>
      </div>
    </div>
  );
}

function Reminders({ onError }) {
  const [rows, setRows] = useState([]);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDue, setEditDue] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await api("/api/reminders");
      setRows(data.reminders || []);
    } catch (err) {
      onError(errorMessage(err));
    }
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!due) setDue(toLocalInput(new Date(Date.now() + 60 * 60 * 1000)));
  }, [due]);

  async function add() {
    if (!title.trim() || !due) {
      onError("اكتب عنوان التذكير وحدّد وقته.");
      return;
    }
    setBusy(true);
    try {
      await api("/api/reminders", {
        method: "POST",
        body: { title: title.trim(), due_at: new Date(due).toISOString(), note: note.trim() },
      });
      setTitle("");
      setNote("");
      await load();
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function patch(id, body) {
    try {
      await api(`/api/reminders/${id}`, { method: "PATCH", body });
      await load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  async function snooze(id, minutes) {
    try {
      await api(`/api/reminders/${id}/snooze`, { method: "POST", body: { minutes } });
      await load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  async function remove(id) {
    try {
      await api(`/api/reminders/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  function startEdit(row) {
    setEditing(row.id);
    setEditTitle(row.title);
    setEditDue(toLocalInput(row.due_at));
  }

  async function saveEdit(id) {
    if (!editTitle.trim() || !editDue) {
      onError("العنوان والوقت لا يجوز أن يكونا فارغين.");
      return;
    }
    await patch(id, { title: editTitle.trim(), due_at: new Date(editDue).toISOString() });
    setEditing(null);
  }

  return (
    <div className="card" data-reminders="1">
      <div className="card-title">
        <h3>تذكيراتي</h3>
        <span className="tag">{rows.length} تذكير</span>
      </div>

      <div className="row wrap" style={{ marginBottom: 12 }}>
        <input
          className="input"
          data-reminder-title
          placeholder="وين تبي التذكير؟ مثلاً: راجع الفصل الثالث"
          value={title}
          maxLength={220}
          onChange={(e) => setTitle(e.target.value)}
          style={{ flex: "2 1 240px" }}
        />
        <input
          className="input"
          data-reminder-due
          type="datetime-local"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          style={{ flex: "1 1 190px" }}
        />
        <input
          className="input"
          data-reminder-note
          placeholder="ملاحظة (اختياري)"
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
          style={{ flex: "2 1 180px" }}
        />
        <button className="btn sm" data-reminder-add disabled={busy} onClick={add}>
          {busy ? "نضيف…" : "أضف التذكير"}
        </button>
      </div>

      <div className="list">
        {rows.map((row) => (
          <div className="list-item" key={row.id} data-reminder-item="1" data-reminder-status={row.status}>
            {editing === row.id ? (
              <div className="stack grow">
                <input
                  className="input"
                  value={editTitle}
                  maxLength={220}
                  onChange={(e) => setEditTitle(e.target.value)}
                  aria-label="عنوان التذكير"
                />
                <input
                  className="input"
                  type="datetime-local"
                  value={editDue}
                  onChange={(e) => setEditDue(e.target.value)}
                  aria-label="وقت التذكير"
                />
                <div className="row wrap">
                  <button className="btn sm" onClick={() => saveEdit(row.id)}>
                    حفظ
                  </button>
                  <button className="btn ghost sm" onClick={() => setEditing(null)}>
                    إلغاء
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="grow">
                  <div className="title">{row.title}</div>
                  <div className="small muted" data-reminder-due-label>
                    {fmtDue(row.due_at)}
                    {row.note ? ` — ${row.note}` : ""}
                  </div>
                </div>
                <span className="tag">{STATUS_LABELS[row.status] || row.status}</span>
                <div className="row wrap">
                  {row.status !== "done" ? (
                    <>
                      <button
                        className="btn ghost sm"
                        data-reminder-snooze
                        onClick={() => snooze(row.id, 60)}
                      >
                        تأجيل ساعة
                      </button>
                      <button className="btn ghost sm" onClick={() => patch(row.id, { done: true })}>
                        أنجزت
                      </button>
                    </>
                  ) : (
                    <button className="btn ghost sm" onClick={() => patch(row.id, { done: false })}>
                      تراجع
                    </button>
                  )}
                  <button className="btn ghost sm" onClick={() => startEdit(row)}>
                    تعديل
                  </button>
                  <button
                    className="btn ghost sm"
                    data-reminder-delete
                    onClick={() => remove(row.id)}
                  >
                    حذف
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
        {!rows.length ? <div className="empty">ما عندك تذكيرات بعد.</div> : null}
      </div>
    </div>
  );
}
