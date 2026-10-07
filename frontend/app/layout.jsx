import "./globals.css";
import Appearance from "@/components/Appearance";
import PwaRegister from "@/components/PwaRegister";

export const metadata = {
  title: "مورس — مدرّسك الشخصي",
  description: "منصة تعليمية ذكية للطالب العراقي: خطة، مراجعة، اختبارات، وشرح.",
  manifest: "/manifest.json",
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/icons/apple-touch-icon.png",
  },
  appleWebApp: {
    capable: true,
    title: "مورس",
    statusBarStyle: "default",
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#2f8ff7",
};

// Pre-paint appearance: theme/accent/scale from the last saved session so the
// first frame is already in the right theme (no light flash before React).
const PREPAINT = `(function(){try{
var a=JSON.parse(localStorage.getItem("mors.appearance")||"null")||{};
var t=a.theme||"light";
if(t==="system"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}
var r=document.documentElement;
r.dataset.theme=t;
r.dataset.contrast=a.high_contrast?"high":"normal";
r.dataset.motion=a.reduce_motion?"reduce":"normal";
if(a.primary_color&&/^#[0-9a-fA-F]{6}$/.test(a.primary_color)){r.style.setProperty("--primary",a.primary_color);}
var s=Number(a.font_scale);if(isFinite(s)){r.style.setProperty("--font-scale",String(Math.min(1.6,Math.max(0.8,s))));}
var ms={small:0.8,normal:1,large:1.2}[a.mors_size]||1;r.style.setProperty("--mors-scale",String(ms));
}catch(e){}})();`;

export default function RootLayout({ children }) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: PREPAINT }} />
      </head>
      <body>
        <Appearance />
        <PwaRegister />
        {children}
      </body>
    </html>
  );
}
