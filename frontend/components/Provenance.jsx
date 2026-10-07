import { fmtDate } from "@/lib/api";

export const SOURCE_LABELS = {
  official: "مصدر وزاري موثّق",
  ai: "توليد AI",
  external: "مدرس",
  bank: "كتاب",
  manual: "محتوى المنصة",
};

export function sourceLabel(kind) {
  return SOURCE_LABELS[kind] || "محتوى المنصة";
}

export default function Provenance({ provenance, kind, style }) {
  const info = provenance || (kind ? { kind, label: sourceLabel(kind), url: "", checked_at: null } : null);
  if (!info) return null;
  return (
    <div className="small muted" style={style}>
      المصدر:{" "}
      {info.url ? (
        <a href={info.url} target="_blank" rel="noopener noreferrer">
          {info.label} ↗
        </a>
      ) : (
        info.label
      )}
      {info.checked_at ? ` · فُحص ${fmtDate(info.checked_at)}` : ""}
    </div>
  );
}
