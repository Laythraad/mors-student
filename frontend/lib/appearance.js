const HEX = /^#[0-9a-fA-F]{6}$/;
const MORS_SCALE = { small: 0.8, normal: 1, large: 1.2 };
const CACHE_KEY = "mors.appearance";

function resolveTheme(theme) {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return theme === "dark" ? "dark" : "light";
}

function applyTo(settings) {
  const root = document.documentElement;
  const theme = settings.theme || "light";
  root.dataset.theme = resolveTheme(theme);
  root.dataset.contrast = settings.high_contrast ? "high" : "normal";
  root.dataset.motion = settings.reduce_motion ? "reduce" : "normal";

  if (HEX.test(settings.primary_color || "")) {
    root.style.setProperty("--primary", settings.primary_color);
  } else {
    root.style.removeProperty("--primary");
  }

  const scale = Number(settings.font_scale);
  root.style.setProperty(
    "--font-scale",
    String(Number.isFinite(scale) ? Math.min(1.6, Math.max(0.8, scale)) : 1),
  );
  root.style.setProperty("--mors-scale", String(MORS_SCALE[settings.mors_size] || 1));
}

export function applyAppearance(settings) {
  if (!settings || typeof document === "undefined") return;
  applyTo(settings);
  try {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        theme: settings.theme || "light",
        primary_color: settings.primary_color || "",
        font_scale: settings.font_scale || 1,
        high_contrast: !!settings.high_contrast,
        reduce_motion: !!settings.reduce_motion,
        mors_size: settings.mors_size || "normal",
      }),
    );
  } catch {
    /* private mode — appearance still applies for this session */
  }
}

export function readCachedAppearance() {
  try {
    return JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
  } catch {
    return null;
  }
}
