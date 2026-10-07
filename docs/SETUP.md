# دليل التثبيت والإعداد (Setup Guide)

## المتطلبات

| المكوّن | الإصدار |
| --- | --- |
| Python | 3.11+ (مُختبر على 3.12) |
| Node.js | 18+ (مُختبر على 24 — على Windows استعمل `npm.cmd`) |
| SQLite | يأتي مع Python (لا يحتاج تثبيتاً) |
| Tesseract (اختياري) | لـ OCR الصور — إن غاب تعمل الرفع بدون استخراج نص |
| Playwright (اختياري) | لاختبارات المتصفح `tools/e2e_browser.py` |

## 1. البيئة ثم الخادم (backend)

```powershell
# من جذر المشروع — app/config.py يقرأ .env من جذر المشروع
copy .env.example .env            # Linux/Mac: cp .env.example .env

cd backend
python -m venv .venv
.\.venv\Scripts\activate          # باش: source .venv/bin/activate
pip install -r requirements.txt
```

عدّل `<جذر المشروع>/.env` الأهمية قبل أي شيء آخر:

- `SECRET_KEY` — مفتاح التوقيع (إلزامي في الإنتاج، راجع `docs/DEPLOYMENT.md`)
- `DATABASE_URL` — الافتراضي `mors.db` في جذر المشروع
- `UPLOAD_DIR` — الافتراضي `uploads/` في جذر المشروع
- `AI_PROVIDER` — `mock` (بدون مفتاح) أو `gemini` (راجع `docs/AI_SETUP.md`)

شغّل:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

**التحقق:** افتح `http://127.0.0.1:8000/health` → `{"status":"ok"}`،
وواجهة OpenAPI على `http://127.0.0.1:8000/api/docs`.

عند أول تشغيل مع `DEMO_DATA=true` تُزرع البيانات تلقائياً: المنهج + صفحات
الكتب + الفيديوهات + حسابا `demo@mors.ai` و`admin@mors.ai`. هذا يضبطه
`mors.ai/.env` في التطوير (`DEMO_DATA=true`)، أما افتراضي الكود فأصبح `false`
فلا يُزرع شيء على قاعدة نظيفة — التأسيس حينها عبر `tools/create_admin.py`
(راجع `docs/DEPLOYMENT.md`).
الزرع idempotent — أي إقلاع لاحق لا يكرر شيئاً ولا يمسّ البيانات الموجودة
(مرحلة الرابع المهني تُضاف كذلك بشكل idempotent إذا غابت).

## 2. الواجهة (frontend)

```powershell
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

الاتصال بالـ backend عبر rewrite في `next.config.mjs`:

```text
/api/*  →  ${API_TARGET}/api/*        (الافتراضي http://127.0.0.1:8000)
/health →  ${API_TARGET}/health
```

إن كان الـ backend على منفذ/مضيف آخر:

```powershell
$env:API_TARGET="http://backend-host:8000"; npm run dev
```

## 3. أول دخول

1. سجّل طالباً جديداً (أو استعمل `demo@mors.ai` / `DemoPass123!`).
2. رحلة الإعداد: المرحلة ← الفرع/القسم ← المواد ← جدول المدرسة والنوم ←
   التشخيص ← الخطة الأولى.
3. لوحة الإدارة (`admin@mors.ai` → `/admin`): رفع الكتب، مراجعة المحتوى،
   النشر والجدولة.

## 4. تشغيل الاختبارات

من جذر المشروع:

```powershell
python -m pytest -q
python -X utf8 tools/smoke_services.py
python -X utf8 tools/smoke_api.py
python -X utf8 tools/e2e.py
python -X utf8 tools/uat.py
python -X utf8 tools/check_frontend_routes.py
```

ملاحظات:

- الاختبارات تستخدم قواعد `%TEMP%\mors_*.db` منفصلة — لا تمسّ قاعدة التطوير.
- `tools/e2e_browser.py` يستهلك منفذ 8000 داخلياً: أوقف الخادمين قبله وأعِد
  تشغيلهما بعده.
- على Windows أضف `-X utf8` لأي سكربت يطبع نصاً عربياً.

## 5. مشاكل شائعة

| العرض | الحل |
| --- | --- |
| `ModuleNotFoundError: app` | شغّل سكربتات `tools/` من جذر المشروع، وpytest من `backend/` |
| الواجهة لا تصل للـ backend | تأكد `API_TARGET` وأن المنفذ 8000 يعمل |
| رفع صورة بلا نص | OCR اختياري — ثبّت Tesseract أو اترك الملف يُرفع كما هو (الحالة تظهر للطالب) |
| نص عربي مشوّه في PowerShell | استعمل `python -X utf8` |
| منفذ 8000 مشغول | `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess` |
