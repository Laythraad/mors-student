"use client";

import { api } from "@/lib/api";

export const AUTO_VOICE_KEY = "mors_voice_auto";

// §15/§70 — every STT failure must tell the student what happened instead of
// silently dropping the microphone.
export const STT_ERRORS = {
  "not-allowed":
    "المايك مرفوض — فعّل إذن الميكروفون للموقع من إعدادات المتصفح ثم أعد المحاولة.",
  "service-not-allowed":
    "خدمة التعرّف على الكلام محجوبة هنا — اكتب سؤالك بدلاً من الإدخال الصوتي.",
  "audio-capture":
    "ما لقيت ميكروفون — تأكد أنه متوصّل بالجهاز وموصول للنظام.",
  network:
    "خدمة التعرّف على الكلام تحتاج إنترنت وانقطع الاتصال — جرّب مرة ثانية.",
  "no-speech": "ما سمعت صوت — كلّم الميكروفون من قريب وجرّب مرة ثانية.",
  language_not_supported:
    "المتصفح ما يدعم التعرّف على الكلام بالعربية — اكتب بدلاً من ذلك.",
  aborted: "أوقفت الإدخال الصوتي.",
  "bad-grammar": "تعذّر قراءة النص — أعد المحاولة.",
};

export function sttErrorMessage(code) {
  return STT_ERRORS[code] || "صار خطأ أثناء الإنصات — أعد المحاولة أو اكتب سؤالك.";
}

export function ttsSupported() {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function sttSupported() {
  if (typeof window === "undefined") return false;
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export function autoVoiceEnabled() {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(AUTO_VOICE_KEY) === "1";
}

export function setAutoVoice(on) {
  if (typeof window === "undefined") return;
  if (on) window.localStorage.setItem(AUTO_VOICE_KEY, "1");
  else window.localStorage.removeItem(AUTO_VOICE_KEY);
}

// Chrome loads voices asynchronously: the first getVoices() call returns []
// and only voiceschanged fills them in. Speaking before that means the
// utterance silently falls back to the system default — usually not Arabic.
export function voicesReady(timeout = 3000) {
  if (!ttsSupported()) return Promise.resolve([]);
  const have = window.speechSynthesis.getVoices() || [];
  if (have.length) return Promise.resolve(have);
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve(window.speechSynthesis.getVoices() || []);
    };
    window.speechSynthesis.addEventListener("voiceschanged", finish, { once: true });
    window.setTimeout(finish, timeout);
  });
}

function arabic(voices) {
  return voices.filter((v) => /^ar([-_]|$)/i.test(v.lang || ""));
}

export function arabicVoiceAvailable(voices) {
  const list = voices || (ttsSupported() ? window.speechSynthesis.getVoices() || [] : []);
  return arabic(list).length > 0;
}

// preference: "system" (best effort) | "ar" (Arabic required) | "slow" (calmer pace)
export function pickVoice(preference = "system", voices) {
  if (!ttsSupported()) return null;
  const list = voices || window.speechSynthesis.getVoices() || [];
  if (!list.length) return null;
  const ar = arabic(list);
  const iq = ar.filter((v) => /[-_]IQ/i.test(v.lang || ""));
  if (preference === "ar") return iq[0] || ar[0] || null;
  if (preference === "slow") return iq[0] || ar[0] || list[0] || null;
  return (
    iq[0] ||
    ar[0] ||
    list.find((v) => /arabic|عربي|عربى/i.test(v.name || "")) ||
    list[0] ||
    null
  );
}

export function stopSpeaking() {
  if (ttsSupported()) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* engine already idle */
    }
  }
}

/**
 * Speak `text` with the student's chosen voice preference.
 * Resolves `{ ok: true }` or `{ ok: false, reason }` — never a bare boolean,
 * so callers can say exactly why nothing was heard.
 */
export async function speakText(
  text,
  { rate = 1, pitch = 1, volume = 1, lang = "ar-IQ", voice = "system" } = {},
) {
  if (!ttsSupported()) return { ok: false, reason: "unsupported" };
  if (!text) return { ok: false, reason: "empty" };

  const voices = await voicesReady();
  const preference = voice || "system";
  const chosen = pickVoice(preference, voices);

  if (preference === "ar" && !chosen) {
    // the student explicitly asked for an Arabic voice the system doesn't have
    return { ok: false, reason: "no-arabic-voice" };
  }
  if (!chosen) return { ok: false, reason: "no-voices" };

  const spokenRate = preference === "slow" ? Math.min(rate, 0.85) : rate;

  return new Promise((resolve) => {
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.rate = spokenRate;
      utter.pitch = pitch;
      utter.volume = volume;
      utter.lang = lang;
      if (chosen) utter.voice = chosen;
      let done = false;
      const finish = (ok, reason) => {
        if (!done) {
          done = true;
          resolve(ok ? { ok: true } : { ok: false, reason: reason || "interrupted" });
        }
      };
      utter.onend = () => finish(true);
      utter.onerror = (e) => finish(false, (e && e.error) || "utterance");
      window.speechSynthesis.speak(utter);
      // headless / blocked engines may never fire onend — never hang the UI
      window.setTimeout(() => finish(Boolean(window.speechSynthesis.speaking)), Math.min(12000, 2500 + text.length * 90));
    } catch {
      resolve({ ok: false, reason: "exception" });
    }
  });
}

export async function speakAsMors(text, style = "neutral", voicePref) {
  if (!text) return { ok: false, reason: "empty" };
  try {
    const cfg = await api("/api/voice/speak", {
      method: "POST",
      body: { text: text.slice(0, 800), style, ...(voicePref ? { voice: voicePref } : {}) },
    });
    return await speakText(cfg.text, { ...cfg, voice: voicePref || cfg.voice });
  } catch {
    return await speakText(text, voicePref ? { voice: voicePref } : {});
  }
}

export function createRecognizer({ lang = "ar-IQ", onFinal, onInterim, onEnd, onError } = {}) {
  if (typeof window === "undefined") return null;
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = lang;
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;
  rec.onresult = (event) => {
    let interim = "";
    let final = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const chunk = event.results[i][0].transcript || "";
      if (event.results[i].isFinal) final += chunk;
      else interim += chunk;
    }
    if (interim && onInterim) onInterim(interim);
    if (final && onFinal) onFinal(final.trim());
  };
  rec.onerror = (event) => {
    if (onError) onError(event.error || "error");
  };
  rec.onend = () => {
    if (onEnd) onEnd();
  };
  return rec;
}
