# Mors.ai — نظام تشغيل الطالب العراقي

منصة تعليمية ذكية للطالب العراقي: مكتبة كتب منظّمة بالمنهج، شرح تفاعلي مع
**مورس** (صوت + تعبيرات + استشهاد بالصفحة)، فيديوهات ببوابات فهم، بنك أسئلة
وامتحانات بجاهزية، مرشد يعطي حلولاً عملية، وخطة دراسة يعرف النظام منها ما
يدرسه الطالب **الآن**.

المرجع: المواصفة النهائية (132 قسماً).

## المكوّنات

| المسار | الوصف |
| --- | --- |
| `backend/` | FastAPI + SQLAlchemy (Python 3.11+)، كل منطق المنتج والاختبارات |
| `frontend/` | Next.js (App Router) — واجهة عربية RTL أولاً، mobile-first |
| `tools/` | اختبارات: smoke، e2e، e2e متصفح، UAT قبول §125، فحص مسارات |
| `docs/` | الأرشيف التقني وأدلة التشغيل (انظر أدناه) |

## البدء السريع

```powershell
# 0) البيئة (من جذر المشروع — config.py يقرأ .env من هنا)
copy .env.example .env        # عدّل SECRET_KEY و DATABASE_URL عند النشر

# 1) الخادم
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# 2) الواجهة (نافذة أخرى)
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

الواجهة تتصل بالـ backend عبر rewrite في `frontend/next.config.mjs`
(`API_TARGET` افتراضياً `http://127.0.0.1:8000`).

## الحسابات التجريبية (DEMO_DATA=true)

| الدور | البريد | كلمة المرور |
| --- | --- | --- |
| طالب | `demo@mors.ai` | `DemoPass123!` |
| مدير | `admin@mors.ai` | `DemoPass123!` |

المرحلتان المنشورتان: **الرابع العلمي** (علمي/أدبي) و**الرابع المهني**
(4 أقسام) — بمواد وكتب وأسئلة تجريبية حتى يرفع الإدارة المنهج الرسمي.

## الاختبارات (من جذر المشروع)

```powershell
python -m pytest -q                                   # وحدات backend
python -X utf8 tools/smoke_services.py                # خدمات
python -X utf8 tools/smoke_api.py                     # طبقة HTTP
python -X utf8 tools/e2e.py                           # رحلة كاملة (منافذ 8111/3111)
python -X utf8 tools/uat.py                           # قبول §125 — رحلة الطالب مرتين
python -X utf8 tools/check_frontend_routes.py         # تطابق مسارات الواجهة مع الـ API
python tools/e2e_browser.py                           # متصفح (يتطلب Playwright + إيقاف منفذ 8000)
cd frontend; npm run build                            # بناء الواجهة
```

## التوثيق

| الملف | الموضوع |
| --- | --- |
| `docs/SETUP.md` | دليل التثبيت والإعداد خطوة بخطوة |
| `docs/DATABASE.md` | قاعدة البيانات والترحيل |
| `docs/AI_SETUP.md` | مزوّد الذكاء الاصطناعي والإعدادات |
| `docs/STORAGE.md` | تخزين الملفات والرفع والفهرسة |
| `docs/DEPLOYMENT.md` | دليل النشر للإنتاج |
| `docs/ARCHITECTURE.md` | بنية النظام وأطر العمل |
