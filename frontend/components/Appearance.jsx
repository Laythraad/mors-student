"use client";

import { useEffect } from "react";
import { api, getToken } from "@/lib/api";
import { applyAppearance, readCachedAppearance } from "@/lib/appearance";

export default function Appearance() {
  useEffect(() => {
    const cached = readCachedAppearance();
    if (cached) applyAppearance(cached);

    let latest = cached;
    const onEvent = (event) => {
      latest = event.detail;
      applyAppearance(latest);
    };
    window.addEventListener("mors:appearance", onEvent);

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystem = () => {
      if (latest && latest.theme === "system") applyAppearance(latest);
    };
    media.addEventListener("change", onSystem);

    const fetchSettings = () => {
      if (!getToken()) return Promise.resolve();
      return api("/api/auth/settings")
        .then((data) => {
          if (data?.settings) {
            latest = data.settings;
            applyAppearance(latest);
          }
        })
        .catch(() => {
          /* signed out / offline — the cached/pre-paint appearance stands */
        });
    };
    fetchSettings();
    window.addEventListener("mors:signed-in", fetchSettings);

    return () => {
      window.removeEventListener("mors:appearance", onEvent);
      window.removeEventListener("mors:signed-in", fetchSettings);
      media.removeEventListener("change", onSystem);
    };
  }, []);

  return null;
}
