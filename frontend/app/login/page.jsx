"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({
    identifier: "",
    email: "",
    password: "",
    full_name: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const field = (key) => ({
    value: form[key],
    onChange: (e) => setForm({ ...form, [key]: e.target.value }),
  });

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const payload =
        mode === "login"
          ? { identifier: form.identifier, password: form.password }
          : {
              full_name: form.full_name,
              email: form.email,
              password: form.password,
            };
      const data = await api(`/api/auth/${mode === "login" ? "login" : "register"}`, {
        method: "POST",
        body: payload,
      });
      setToken(data.tokens.access_token);
      window.dispatchEvent(new Event("mors:signed-in"));
      const step = data.welcome ? data.welcome.onboarding_step : 0;
      const hasStage = data.welcome ? data.welcome.has_stage : false;
      router.replace(!hasStage && step < 99 ? "/onboarding" : "/home");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="logo">
          <img src="/mors/neutral.png" alt="مورس" />
        </div>
        <h1 style={{ textAlign: "center" }}>مورس</h1>
        <p className="muted" style={{ textAlign: "center" }}>
          مدرّسك الشخصي — خطة، شرح، مراجعة، واختبارات.
        </p>

        <div className="tabs">
          <button className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>
            دخول
          </button>
          <button className={mode === "register" ? "on" : ""} onClick={() => setMode("register")}>
            حساب جديد
          </button>
        </div>

        {error ? <div className="error-box">{error}</div> : null}

        <form onSubmit={submit}>
          {mode === "register" ? (
            <div className="field">
              <label>الاسم الكامل</label>
              <input className="input" required minLength={2} {...field("full_name")} />
            </div>
          ) : (
            <div className="field">
              <label>البريد الإلكتروني</label>
              <input
                className="input"
                required
                dir="ltr"
                placeholder="name@example.com"
                {...field("identifier")}
              />
            </div>
          )}

          {mode === "register" ? (
            <div className="field">
              <label>البريد الإلكتروني</label>
              <input
                className="input"
                type="email"
                required
                dir="ltr"
                {...field("email")}
              />
            </div>
          ) : null}

          <div className="field">
            <label>كلمة المرور</label>
            <input
              className="input"
              type="password"
              required
              minLength={8}
              dir="ltr"
              placeholder="••••••••"
              {...field("password")}
            />
          </div>

          <button className="btn block" disabled={busy}>
            {busy ? "لحظة…" : mode === "login" ? "دخول" : "إنشاء الحساب"}
          </button>
        </form>

        <div className="divider" />
        <p className="small muted" style={{ textAlign: "center", margin: 0 }}>
          <Link href="/home">دخول كضيف</Link>
        </p>
      </div>
    </div>
  );
}
