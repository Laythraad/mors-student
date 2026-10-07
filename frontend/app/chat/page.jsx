"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Shell from "@/components/Shell";
import { api, errorMessage } from "@/lib/api";
import {
  autoVoiceEnabled,
  createRecognizer,
  setAutoVoice,
  speakAsMors,
  stopSpeaking,
  sttErrorMessage,
  sttSupported,
  ttsSupported,
} from "@/lib/voice";

const MODES = [
  { key: "tutor", label: "شرح" },
  { key: "socratic", label: "هدّدني بالأسئلة" },
  { key: "hint", label: "تلميح فقط" },
  { key: "quiz", label: "أسئلة" },
  { key: "summarize", label: "لخّص" },
];

const QUICK = [
  "اشرحلي هالدرس بطريقة بسيطة",
  "أعطني مثال محلول",
  "وش الفرق بين المفهومين؟",
  "اختبرني بـ٣ أسئلة",
];

export default function ChatPage() {
  return (
    <Shell title="محادثة مورس">
      <Suspense fallback={null}>
        <ChatBody />
      </Suspense>
    </Shell>
  );
}

function ChatBody() {
  const params = useSearchParams();
  const lessonId = params.get("lesson");
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [text, setText] = useState("");
  const [mode, setMode] = useState("tutor");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [voiceCfg, setVoiceCfg] = useState(null);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [autoVoice, setAutoVoiceState] = useState(false);
  const [notice, setNotice] = useState("");
  const logRef = useRef(null);
  const recRef = useRef(null);
  const watchRef = useRef(null);

  const clearWatchdog = useCallback(() => {
    if (watchRef.current) {
      window.clearTimeout(watchRef.current);
      watchRef.current = null;
    }
  }, []);

  const voiceOn = voiceCfg?.user?.voice_enabled !== false;

  useEffect(() => {
    setAutoVoiceState(autoVoiceEnabled());
    api("/api/voice/config")
      .then(setVoiceCfg)
      .catch(() => setVoiceCfg(null));
  }, []);

  useEffect(
    () => () => {
      stopSpeaking();
      clearWatchdog();
      if (recRef.current) {
        try {
          recRef.current.stop();
        } catch {
          /* recognizer already stopped */
        }
      }
    },
    [clearWatchdog],
  );

  // §70 — voice is always optional; the student's switch is about Mors SPEAKING
  // (TTS), so it must never silence their own microphone (STT).
  const canListen = sttSupported() && voiceCfg?.stt_ready !== false;
  const ttsCapable = ttsSupported() && voiceCfg?.tts_ready !== false;
  const canSpeak = ttsCapable && voiceOn;
  const voicePref = voiceCfg?.user?.tts_voice || "system";

  function toggleAutoVoice() {
    if (!voiceOn) {
      setNotice("صوت مورس موقوف من الإعدادات — شغّله من هناك عشان تسمع الردود.");
      return;
    }
    const next = !autoVoice;
    setAutoVoiceState(next);
    setAutoVoice(next);
    if (!next) stopSpeaking();
  }

  function toggleMic() {
    if (listening) {
      if (recRef.current) {
        try {
          recRef.current.stop();
        } catch {
          /* noop */
        }
      }
      setListening(false);
      setInterim("");
      clearWatchdog();
      return;
    }
    const rec = createRecognizer({
      onFinal: (finalText) => {
        setInterim("");
        clearWatchdog();
        if (finalText) setText((prev) => (prev ? `${prev} ${finalText}` : finalText));
      },
      onInterim: (chunk) => setInterim(chunk),
      onEnd: () => {
        clearWatchdog();
        setListening(false);
        setInterim("");
      },
      onError: (code) => {
        // never swallow it: the student must learn why nothing was heard
        clearWatchdog();
        setListening(false);
        setInterim("");
        setNotice(sttErrorMessage(code));
      },
    });
    if (!rec) {
      setNotice(sttErrorMessage("service-not-allowed"));
      return;
    }
    recRef.current = rec;
    setListening(true);
    setInterim("");
    setNotice("");
    try {
      rec.start();
      // some engines hang forever without firing onerror/onend (seen with
      // blocked or offline recognizers) — surface that instead of stalling
      watchRef.current = window.setTimeout(() => {
        try {
          rec.stop();
        } catch {
          /* already gone */
        }
        setListening(false);
        setInterim("");
        setNotice(
          "ما قدرت ألتقط صوتك — تأكد من إذن الميكروفون والإنترنت، أو اكتب سؤالك.",
        );
      }, 9000);
    } catch {
      setListening(false);
      setNotice(sttErrorMessage("audio-capture"));
    }
  }

  const loadList = useCallback(async () => {
    try {
      const data = await api("/api/chat/conversations");
      setConversations(data.conversations || []);
    } catch {
      /* optional */
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  async function send(body) {
    const content = (body ?? text).trim();
    if (!content || busy) return;
    setBusy(true);
    setError("");
    setText("");
    setMessages((prev) => [...prev, { role: "user", content }]);
    try {
      const data = await api("/api/chat/messages", {
        method: "POST",
        body: {
          message: content,
          conversation_id: conversationId,
          lesson_id: lessonId || null,
          mode,
        },
      });
      setConversationId(data.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply,
          citations: data.citations || [],
          confidence: data.confidence,
          refused: data.refused,
        },
      ]);
      loadList();
      if (autoVoice && canSpeak && data.reply) {
        speakAsMors(data.reply, data.expression || "neutral", voicePref);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function openConversation(id) {
    try {
      const data = await api(`/api/chat/conversations/${id}`);
      setConversationId(id);
      setMessages(data.messages || []);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function newChat() {
    setConversationId(null);
    setMessages([]);
    if (lessonId) {
      try {
        const data = await api("/api/chat/conversations", {
          method: "POST",
          body: { lesson_id: lessonId },
        });
        setConversationId(data.id);
      } catch {
        /* optional */
      }
    }
  }

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? (
        <div className="notice-box" role="status">
          {notice}
        </div>
      ) : null}

      <div className="tabs">
        {MODES.map((m) => (
          <button key={m.key} className={mode === m.key ? "on" : ""} onClick={() => setMode(m.key)}>
            {m.label}
          </button>
        ))}
      </div>

      <div className="row wrap">
        <button className="btn ghost sm" onClick={newChat}>
          محادثة جديدة
        </button>
        {voiceCfg && !voiceOn ? (
          <span className="chip" title="تقدر تعيد تشغيل الصوت من الإعدادات">
            🔇 الصوت موقوف من الإعدادات
          </span>
        ) : null}
        {ttsCapable ? (
          <button
            className={`chip ${autoVoice ? "on" : ""}`}
            onClick={toggleAutoVoice}
            title={
              voiceOn
                ? "تشغيل صوت مورس تلقائياً على كل رد"
                : "الصوت موقوف من الإعدادات — شغّله أول ما تحب تسمع مورس"
            }
          >
            🔊 {autoVoice && voiceOn ? "صوت تلقائي" : "صوت متوقف"}
          </button>
        ) : null}
        {conversations.slice(0, 5).map((c) => (
          <button key={c.id} className="chip" onClick={() => openConversation(c.id)}>
            {c.title || "محادثة"}
          </button>
        ))}
        {lessonId ? (
          <Link className="chip" href={`/lessons/${lessonId}`}>
            الدرس المرتبط 📖
          </Link>
        ) : null}
      </div>

      <div className="card" style={{ minHeight: 260 }}>
        <div className="chat-log" ref={logRef}>
          {!messages.length ? (
            <div className="empty">
              أهلأ! أنا مورس — اسألني عن أي درس. جرّب أحد الأسئلة الجاهزة:
              <div className="row wrap" style={{ justifyContent: "center", marginTop: 10 }}>
                {QUICK.map((q) => (
                  <button key={q} className="chip" onClick={() => send(q)} disabled={busy}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role === "user" ? "user" : "mors"}`}>
              {m.content}
              {m.role === "assistant" && m.citations && m.citations.length ? (
                <div className="small muted" style={{ marginTop: 6 }}>
                  المصدر: {m.citations.map((c) => c.title || c.text || "").filter(Boolean).join(" · ")}
                </div>
              ) : null}
              {m.role === "assistant" && canSpeak ? (
                <div className="row" style={{ marginTop: 6 }}>
                  <button
                    className="btn ghost sm"
                    onClick={() => speakAsMors(m.content, m.expression || "neutral", voicePref)}
                    aria-label="استمع إلى رد مورس"
                  >
                    🔊 استمع
                  </button>
                </div>
              ) : null}
            </div>
          ))}

          {busy ? (
            <div className="bubble mors muted row">
              <div className="spinner" /> يفكّر…
            </div>
          ) : null}
        </div>
      </div>

      <div className="chat-input">
        {canListen ? (
          <button
            type="button"
            className={`mic ${listening ? "on" : ""}`}
            onClick={toggleMic}
            aria-label={listening ? "إيقاف الإدخال الصوتي" : "إدخال صوتي"}
          >
            {listening ? "◼" : "🎤"}
          </button>
        ) : null}
        <input
          value={text}
          placeholder={listening ? interim || "أنصت إليك…" : "اكتب سؤالك…"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
        />
        <button onClick={() => send()} disabled={busy} aria-label="إرسال">
          ➤
        </button>
      </div>
    </div>
  );
}
