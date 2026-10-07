"use client";

export const TOKEN_KEY = "mors_token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || "تعذّر تنفيذ الطلب.");
    this.status = status;
    this.code = code || "error";
  }
}

async function parse(response) {
  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }
  if (!response.ok) {
    const err = data && data.error ? data.error : {};
    if (response.status === 401 && typeof window !== "undefined") {
      setToken(null);
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    throw new ApiError(response.status, err.code, err.message);
  }
  return data;
}

export async function api(path, options = {}) {
  const { method = "GET", body, headers = {}, query } = options;
  let url = path;
  if (query) {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, value);
    });
    const qs = params.toString();
    if (qs) url += `${url.includes("?") ? "&" : "?"}${qs}`;
  }

  const init = {
    method,
    headers: { ...authHeaders(), ...headers },
    credentials: "include",
  };

  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const response = await fetch(url, init);
  return parse(response);
}

export function errorMessage(error) {
  if (!error) return "خطأ غير متوقع.";
  if (error.code === "failed_fetch") return "تعذّر الاتصال بالخادم — تأكد أن الـ backend شغّال.";
  return error.message || "خطأ غير متوقع.";
}

export function fmtTime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function fmtDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleDateString("ar-IQ", {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
  } catch {
    return String(value);
  }
}

export function fmtShortDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleDateString("ar-IQ", { day: "numeric", month: "short" });
  } catch {
    return String(value);
  }
}
