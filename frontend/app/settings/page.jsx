"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { applyAppearance } from "@/lib/appearance";
import { api, errorMessage, setToken } from "@/lib/api";
import { arabicVoiceAvailable, speakAsMors, sttSupported, ttsSupported, voicesReady } from "@/lib/voice";

export default function SettingsPage() {
  return (
    <Shell title="الإعدادات">
      <SettingsBody />
    </Shell>
  );
}

function SettingsBody() {
  const router = useRouter();
  const [me, setMe] = useState(null);
  const [settings, setSettings] = useState(null);
  const [subjects, setSubjects] = useState([]);
  const [picked, setPicked] = useState([]);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [voiceCfg, setVoiceCfg] = useState(null);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState("");
  const [arVoiceReady, setArVoiceReady] = useState(null);
  const [deletePw, setDeletePw] = useState("");

  const load = useCallback(async () => {
    try {
      const [userData, settingsData, mineData, allSubjects, voiceData] = await Promise.all([
        api("/api/auth/me"),
        api("/api/auth/settings"),
        api("/api/curriculum/mine"),
        api("/api/curriculum/subjects"),
        api("/api/voice/config").catch(() => null),
      ]);
      setMe(userData);
      setSettings(settingsData.settings);
      setPicked((mineData.subjects || []).map((s) => s.id || s.subject_id).filter(Boolean));
      setSubjects(allSubjects.subjects || []);
      setVoiceCfg(voiceData);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // voices arrive asynchronously; report honestly whether Arabic output exists
  useEffect(() => {
    let alive = true;
    voicesReady().then((list) => {
      if (alive) setArVoiceReady(arabicVoiceAvailable(list));
    });
    return () => {
      alive = false;
    };
  }, []);

  async function patchProfile(data) {
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/profile", { method: "PATCH", body: data });
      setNotice("حُفظت بياناتك.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function patchSettings(data) {
    try {
      const result = await api("/api/auth/settings", { method: "PATCH", body: data });
      setSettings(result.settings);
      applyAppearance(result.settings);
      window.dispatchEvent(new CustomEvent("mors:appearance", { detail: result.settings }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveSubjects() {
    setBusy(true);
    try {
      await api("/api/auth/subjects", { method: "PUT", body: { subject_ids: picked } });
      setNotice("حُدّثت موادك.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function changePassword() {
    setBusy(true);
    try {
      await api("/api/auth/password", { method: "POST", body: { password } });
      setPassword("");
      setNotice("تم تغيير كلمة المرور.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount() {
    if (!window.confirm("سيُحذف حسابك وبياناتك نهائياً ولا يمكن التراجع. أنت متأكد؟")) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/account", { method: "DELETE", body: { password: deletePw } });
      setToken(null);
      router.replace("/login");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function testVoice() {
    setVoiceBusy(true);
    setVoiceNotice("");
    setError("");
    try {
      const result = await speakAsMors(
        "أهلأ، أنا مورس — هذا صوتي على المنصة.",
        "welcoming",
        settings.tts_voice || "system",
      );
      if (result?.ok) {
        setVoiceNotice("نطقت الجملة بنجاح ✅");
      } else if (result?.reason === "no-arabic-voice") {
        setVoiceNotice(
          "ما لقيت صوت عربي مثبّت على جهازك — المنصة تشتغل نصّياً بالكامل، "
          + "وراح ينطبق الصوت العربي تلقائياً أول ما تثبّته في نظامك.",
        );
      } else if (result?.reason === "unsupported" || result?.reason === "no-voices") {
        setVoiceNotice("المتصفح ما يدعم النطق — المنصة تشتغل نصّياً بالكامل.");
      } else {
        setVoiceNotice("ما قدرت أنطق الآن — جرّب مرة ثانية.");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setVoiceBusy(false);
    }
  }

  if (!me || !settings)
    return (
      <div className="loading-page">
        <div className="spinner" />
      </div>
    );

  const profile = me.profile || {};

  return (
    <div className="stack">
      {error ? <div className="error-box">{error}</div> : null}
      {notice ? <div className="success-box">{notice}</div> : null}

      <div className="card">
        <div className="card-title">
          <h3>حسابي</h3>
        </div>
        <div className="field">
          <label>الاسم</label>
          <input
            className="input"
            defaultValue={me.user.full_name}
            onBlur={(e) => patchProfile({ full_name: e.target.value })}
          />
        </div>
        <div className="field">
          <label>البريد</label>
          <input className="input" dir="ltr" defaultValue={me.user.email || ""} disabled />
        </div>
        <div className="field">
          <label>اسم المدرسة</label>
          <input
            className="input"
            defaultValue={profile.school_name || ""}
            onBlur={(e) => patchProfile({ school_name: e.target.value })}
          />
        </div>
        <div className="field">
          <label>دقائق الدراسة اليومية</label>
          <input
            type="range"
            min={20}
            max={300}
            step={10}
            defaultValue={profile.daily_study_minutes || 90}
            onBlur={(e) => patchProfile({ daily_study_minutes: Number(e.target.value) })}
          />
        </div>
        <div className="row wrap">
          <Link className="btn ghost sm" href="/onboarding">
            إعادة الإعداد الأول
          </Link>
          <button
            className="btn danger sm"
            onClick={() => {
              setToken(null);
              router.replace("/login");
            }}
          >
            تسجيل الخروج
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>موادي الدراسية</h3>
          <button className="btn sm" disabled={busy} onClick={saveSubjects}>
            حفظ
          </button>
        </div>
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
      </div>

      <div className="card">
        <div className="card-title">
          <h3>تفضيلات مورس والواجهة</h3>
        </div>

        <div className="row between" style={{ marginBottom: 10 }}>
          <span>وضع التركيز (كتم الإشعارات)</span>
          <button
            className={`chip ${settings.focus_mode ? "on" : ""}`}
            onClick={() => patchSettings({ focus_mode: !settings.focus_mode })}
          >
            {settings.focus_mode ? "تشغيل" : "إيقاف"}
          </button>
        </div>

        <div className="row between" style={{ marginBottom: 10 }}>
          <span>رسائل مورس عند الخمول</span>
          <button
            className={`chip ${settings.mors_idle_enabled ? "on" : ""}`}
            onClick={() => patchSettings({ mors_idle_enabled: !settings.mors_idle_enabled })}
          >
            {settings.mors_idle_enabled ? "تشغيل" : "إيقاف"}
          </button>
        </div>

        <div className="row between" style={{ marginBottom: 10 }}>
          <span>الاحتفال بالإنجازات</span>
          <button
            className={`chip ${settings.celebrate_enabled ? "on" : ""}`}
            onClick={() => patchSettings({ celebrate_enabled: !settings.celebrate_enabled })}
          >
            {settings.celebrate_enabled ? "تشغيل" : "إيقاف"}
          </button>
        </div>

        <div className="field">
          <label>وتيرة الإشعارات</label>
          <select
            className="select"
            value={settings.notification_freq}
            onChange={(e) => patchSettings({ notification_freq: e.target.value })}
          >
            <option value="off">إيقاف</option>
            <option value="quiet">قليل</option>
            <option value="normal">عادي</option>
            <option value="all">كثير</option>
          </select>
        </div>

        <div className="field">
          <label>المظهر</label>
          <select
            className="select"
            value={settings.theme}
            onChange={(e) => patchSettings({ theme: e.target.value })}
          >
            <option value="light">فاتح</option>
            <option value="dark">داكن</option>
            <option value="system">حسب النظام</option>
          </select>
        </div>

        <div className="field">
          <label>حجم الخط</label>
          <div className="row wrap">
            {[
              [0.9, "صغير"],
              [1, "متوسط"],
              [1.25, "كبير"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={`chip ${Math.abs((settings.font_scale || 1) - value) < 0.01 ? "on" : ""}`}
                onClick={() => patchSettings({ font_scale: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>اللون الأساسي</label>
          <div className="row wrap">
            {["#2f8ff7", "#7c5cff", "#16b981", "#f59e0b", "#ef4444", "#ec4899"].map((color) => (
              <button
                key={color}
                aria-label={`اللون ${color}`}
                onClick={() => patchSettings({ primary_color: color })}
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: "50%",
                  background: color,
                  cursor: "pointer",
                  border:
                    settings.primary_color === color
                      ? "3px solid var(--text)"
                      : "2px solid var(--border)",
                }}
              />
            ))}
          </div>
        </div>

        <div className="field">
          <label>حجم مورس</label>
          <div className="row wrap">
            {[
              ["small", "صغير"],
              ["normal", "عادي"],
              ["large", "كبير"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={`chip ${settings.mors_size === value ? "on" : ""}`}
                onClick={() => patchSettings({ mors_size: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="row between" style={{ marginBottom: 10 }}>
          <span>تباين عالٍ</span>
          <button
            className={`chip ${settings.high_contrast ? "on" : ""}`}
            onClick={() => patchSettings({ high_contrast: !settings.high_contrast })}
          >
            {settings.high_contrast ? "تشغيل" : "إيقاف"}
          </button>
        </div>

        <div className="row between">
          <span>تقليل الحركة</span>
          <button
            className={`chip ${settings.reduce_motion ? "on" : ""}`}
            onClick={() => patchSettings({ reduce_motion: !settings.reduce_motion })}
          >
            {settings.reduce_motion ? "تشغيل" : "إيقاف"}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>الصوت (Voice Input / Output)</h3>
        </div>
        <div className="row wrap small muted" style={{ marginBottom: 10 }}>
          <span className="chip">
            TTS: {voiceCfg?.tts_provider || "…"}
            {voiceCfg?.tts_ready ? " ✓" : ""}
          </span>
          <span className="chip">
            STT: {voiceCfg?.stt_provider || "…"}
            {voiceCfg?.stt_ready ? " ✓" : ""}
          </span>
          {!ttsSupported() ? <span className="tag warn">المتصفح لا يدعم النطق</span> : null}
          {!sttSupported() ? <span className="tag warn">المتصفح لا يدعم التعرّف</span> : null}
          {ttsSupported() && arVoiceReady === true ? (
            <span className="tag ok">صوت عربي جاهز</span>
          ) : null}
          {ttsSupported() && arVoiceReady === false ? (
            <span className="tag warn">ما مثبّت صوت عربي على الجهاز</span>
          ) : null}
        </div>

        <div className="row between" style={{ marginBottom: 10 }}>
          <span>صوت مورس (TTS)</span>
          <button
            className={`chip ${settings.voice_enabled ? "on" : ""}`}
            onClick={() => patchSettings({ voice_enabled: !settings.voice_enabled })}
          >
            {settings.voice_enabled ? "تشغيل" : "إيقاف"}
          </button>
        </div>

        <div className="field">
          <label>الصوت المفضل</label>
          <select
            className="select"
            value={settings.tts_voice || "system"}
            onChange={(e) => patchSettings({ tts_voice: e.target.value })}
          >
            <option value="system">صوت النظام (تلقائي)</option>
            <option value="ar">صوت عربي</option>
            <option value="slow">صوت هادئ</option>
          </select>
        </div>

        <div className="field">
          <label>التعرّف على الكلام (STT)</label>
          <select
            className="select"
            value={settings.stt_provider || "browser"}
            onChange={(e) => patchSettings({ stt_provider: e.target.value })}
          >
            <option value="browser">المتصفح (بدون رفع صوت)</option>
            <option value="mock">تجريبي (تطوير)</option>
          </select>
        </div>

        <div className="row wrap">
          <button className="btn sm" disabled={voiceBusy} onClick={testVoice}>
            {voiceBusy ? "جاري النطق…" : "🔊 جرّب صوت مورس"}
          </button>
          <span className="small muted">الصوت اختياري — المنصة تعمل نصّياً بالكامل (§70).</span>
        </div>
        {voiceNotice ? <div className="success-box">{voiceNotice}</div> : null}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>كلمة المرور</h3>
        </div>
        <div className="field">
          <input
            className="input"
            type="password"
            dir="ltr"
            placeholder="كلمة مرور جديدة (8+ أحرف مع رقم)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button className="btn" disabled={password.length < 8 || busy} onClick={changePassword}>
          تغيير كلمة المرور
        </button>
      </div>

      <div
        className="card"
        style={{ border: "1px solid color-mix(in srgb, var(--danger) 45%, var(--surface))" }}
      >
        <div className="card-title">
          <h3>حذف الحساب</h3>
          <span className="tag bad">نهائي</span>
        </div>
        <p className="small muted">
          سيُحذف حسابك وكل بياناتك الشخصية (الخطة، الجلسات، الأوراق، الملاحظات، الرفعات، سجل مورس)
          نهائياً ولا يمكن التراجع عن ذلك (§128).
        </p>
        <div className="field">
          <input
            className="input"
            type="password"
            dir="ltr"
            placeholder="أدخل كلمة المرور للتأكيد"
            value={deletePw}
            onChange={(e) => setDeletePw(e.target.value)}
          />
        </div>
        <button
          className="btn ghost"
          style={{ color: "var(--danger)" }}
          disabled={!deletePw || busy}
          onClick={deleteAccount}
        >
          حذف حسابي نهائياً
        </button>
      </div>
    </div>
  );
}
