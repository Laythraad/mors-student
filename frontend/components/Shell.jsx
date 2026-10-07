"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, fmtTime, getToken, setToken } from "@/lib/api";
import Mors from "@/components/Mors";

const NAV = [
  { href: "/home", label: "الرئيسية", ico: "🏠" },
  { href: "/chat", label: "مورس", ico: "💬" },
  { href: "/library", label: "المكتبة", ico: "📚", match: ["/books"] },
  { href: "/plan", label: "خطتي", ico: "🗓️" },
  { href: "/exams", label: "الامتحانات", ico: "🎯", match: ["/exam/"] },
  { href: "/advisor", label: "مرشدي", ico: "🧭", match: ["/advisor/"] },
  { href: "/progress", label: "تقدّمي", ico: "📈" },
  { href: "/notes", label: "ملاحظاتي", ico: "📝" },
  { href: "/papers", label: "أوراق", ico: "🗂️" },
  { href: "/videos", label: "الدروس", ico: "🎬" },
  { href: "/inbox", label: "الإشعارات", ico: "🔔" },
  { href: "/settings", label: "الإعدادات", ico: "⚙️" },
];

// bottom bar (§100): the four daily destinations + "المزيد" for the rest
const BOTTOM_HREFS = ["/home", "/chat", "/plan", "/exams"];

function isActive(item, pathname) {
  if (pathname === item.href || pathname.startsWith(`${item.href}/`)) return true;
  return (item.match || []).some((m) => pathname.startsWith(m));
}

export default function Shell({ children, title }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState(null);
  const [tick, setTick] = useState(0);
  const [moreOpen, setMoreOpen] = useState(false);
  const startedAt = useRef(Date.now());

  const loadSession = useCallback(async () => {
    try {
      const data = await api("/api/study/active");
      const next = data.session || null;
      setSession((prev) => {
        if (next && prev && prev.id === next.id) return prev;
        if (!next && !prev) return prev;
        if (next) startedAt.current = Date.now();
        return next;
      });
    } catch {
      /* keep the last known state — a flaky request must not wipe the strip */
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await api("/api/auth/me");
        if (!cancelled) setUser(data.user);
      } catch (err) {
        // 401 = real logout; anything else (offline, rate limit) must not kick the user out
        if (!cancelled && err && err.status === 401) {
          router.replace("/login");
          return;
        }
      }
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (!ready) return;
    loadSession();
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    const refresh = setInterval(loadSession, 20000);
    return () => {
      clearInterval(timer);
      clearInterval(refresh);
    };
  }, [ready, loadSession]);

  async function endSession() {
    if (!session) return;
    try {
      await api(`/api/study/${session.id}/end`, {
        method: "POST",
        body: { status: "completed", feedback: "medium" },
      });
    } catch {
      /* ignore — the strip will refresh anyway */
    }
    setSession(null);
    router.refresh();
  }

  if (!ready) {
    return (
      <div className="loading-page">
        <div className="spinner" />
        <span>جاري التحميل…</span>
      </div>
    );
  }

  const elapsed = session
    ? (session.elapsed_seconds || 0) + Math.floor((Date.now() - startedAt.current) / 1000)
    : 0;

  const isAdmin = user && (user.role === "admin" || user.role === "content_manager");
  const nav = isAdmin ? [...NAV, { href: "/admin", label: "الإدارة", ico: "🛡️" }] : NAV;
  const bottomItems = nav.filter((item) => BOTTOM_HREFS.includes(item.href));
  const moreItems = nav.filter((item) => !BOTTOM_HREFS.includes(item.href));
  const bottomOn = bottomItems.some((item) => isActive(item, pathname));
  const moreOn = !bottomOn && moreItems.some((item) => isActive(item, pathname));

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span>🎓</span> مورس
        </div>
        {nav.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(item, pathname) ? "active" : ""}
          >
            <span className="ico">{item.ico}</span> {item.label}
          </Link>
        ))}
        <div style={{ marginTop: "auto", padding: "10px", fontSize: 13 }} className="muted">
          {user ? user.full_name : ""}
          <br />
          <button
            className="btn ghost sm"
            style={{ marginTop: 8 }}
            onClick={() => {
              setToken(null);
              router.replace("/login");
            }}
          >
            خروج
          </button>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <h1>{title}</h1>
          <div className="row">
            <Link href="/inbox" className="btn ghost sm">
              🔔
            </Link>
            <Link href="/settings" className="btn soft sm">
              ⚙️
            </Link>
          </div>
        </div>

        {session ? (
          <div className="session-strip">
            <span className="row">
              <strong>{session.title || "جلسة دراسة"}</strong>
              <span className="mono" dir="ltr">
                {fmtTime(elapsed)}
              </span>
            </span>
            <span className="row">
              <button className="btn sm" onClick={() => router.push(`/study?session=${session.id}`)}>
                متابعة
              </button>
              <button className="btn sm" onClick={endSession}>
                إنهاء
              </button>
            </span>
          </div>
        ) : null}

        {children}
      </main>

      <nav className="bottomnav">
        {bottomItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(item, pathname) ? "active" : ""}
          >
            <span className="ico">{item.ico}</span>
            {item.label}
          </Link>
        ))}
        <button
          type="button"
          className={moreOn || moreOpen ? "active" : ""}
          onClick={() => setMoreOpen(true)}
        >
          <span className="ico">⋯</span>
          المزيد
        </button>
      </nav>

      {moreOpen ? (
        <div className="more-backdrop" onClick={() => setMoreOpen(false)}>
          <div className="more-sheet" onClick={(event) => event.stopPropagation()}>
            <div className="more-head">
              <strong>المزيد</strong>
              <button className="btn ghost sm" onClick={() => setMoreOpen(false)}>
                ✕
              </button>
            </div>
            <div className="more-grid">
              {moreItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={isActive(item, pathname) ? "active" : ""}
                  onClick={() => setMoreOpen(false)}
                >
                  <span className="ico">{item.ico}</span>
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {/* On /chat the student is already talking to Mors, and on phones the
          floating widget landed on top of the composer — the send button was
          literally unclickable. Keep it everywhere else. */}
      {pathname === "/chat" ? null : <Mors />}
    </div>
  );
}
