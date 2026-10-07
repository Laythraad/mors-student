"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/**
 * Floating Mors: shows the current personality state (sprite + face) and the
 * latest queued line. Clicking the bubble delivers it; clicking the sprite
 * cycles to the next pending message.
 */
export default function Mors() {
  const [state, setState] = useState(null);
  const [line, setLine] = useState(null);
  const queue = useRef([]);
  const [open, setOpen] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [stateData, messages] = await Promise.all([
        api("/api/inbox/mors/state"),
        api("/api/inbox/mors/messages", { query: { limit: 5 } }),
      ]);
      setState(stateData);
      const pending = (messages.messages || []).filter((m) => !m.dismissed);
      if (pending.length) {
        queue.current = pending;
        setLine((current) => current || pending[0]);
        try {
          await api("/api/inbox/mors/delivered", {
            method: "POST",
            body: { ids: pending.map((m) => m.id) },
          });
        } catch {
          /* delivery tracking is best-effort */
        }
      }
    } catch {
      /* offline — keep the last known state */
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function dismiss() {
    const current = line;
    setLine(null);
    if (current) {
      try {
        await api(`/api/inbox/mors/messages/${current.id}/dismiss`, { method: "POST" });
      } catch {
        /* already gone */
      }
    }
    const rest = queue.current.filter((m) => m.id !== (current && current.id));
    queue.current = rest;
    if (rest.length) setLine(rest[0]);
  }

  const sprite = (line && line.sprite) || (state && state.sprite) || "/mors/neutral.png";
  const expression = (line && line.expression) || (state && state.expression) || "neutral";
  const text = line ? line.text : state ? state.message : "";

  if (!state && !line) return null;

  return (
    <div className="mors-float">
      {open && text ? (
        <div className="mors-bubble" role="status" aria-live="polite">
          <div className="row between" style={{ gap: 8 }}>
            <strong className="small">{expression}</strong>
            <button
              className="btn ghost sm"
              style={{ padding: "2px 8px", minHeight: 26 }}
              onClick={() => setOpen(false)}
              aria-label="إخفاء"
            >
              ✕
            </button>
          </div>
          <div onClick={dismiss} style={{ cursor: "pointer" }}>
            {text}
          </div>
        </div>
      ) : null}

      <button
        className="mors-sprite"
        onClick={() => {
          if (line) dismiss();
          else setOpen((v) => !v);
        }}
        title="مورس"
        aria-label="مورس"
      >
        <img src={sprite} alt={`مورس — ${expression}`} />
      </button>
    </div>
  );
}
