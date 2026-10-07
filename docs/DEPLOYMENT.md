# دليل النشر (Deployment Guide)

الإصدار الحالي: **SQLite + uvicorn + Next.js `next start`** على جهاز واحد
(Windows أو Linux). قبل أي خيار أعقد، اقرأ `docs/SETUP.md` وشغّل الاختبارات.

## 1. إعداد الإنتاج

`.env` في جذر المشروع (راجع `.env.example` للتطوير و`prod.env.example` للإنتاج):

```env
APP_ENV=production
DEBUG=false
SECRET_KEY=<توليد قوي — python -c "import secrets; print(secrets.token_urlsafe(48))">
CORS_ORIGINS=https://your-domain.com
DATABASE_URL=sqlite:///D:/mors/data/mors.db        # مسار خارج شجرة الكود
UPLOAD_DIR=D:/mors/uploads                          # قرص دائم
DEMO_DATA=false                                     # الإنتاج لا يزرع شيئاً
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=30
RATE_LIMIT_PER_MINUTE=120
AI_RATE_LIMIT_PER_MINUTE=30
AI_PROVIDER=gemini                                  # أو mock — راجع docs/AI_SETUP.md
GEMINI_API_KEY=<مفتاحك>
```

بوابة إنتاج تُفرض عند الإقلاع (`backend/app/main.py::_enforce_production_policy`):

- **يرفض الإقلاع** مع `SECRET_KEY` افتراضي (`dev-only-change-me` /
  `change-me-before-production` / فارغ) أو مع `RATE_LIMIT_PER_MINUTE=0`
  أو `AI_RATE_LIMIT_PER_MINUTE=0`.
- **يشتغل ويُسجّل تحذيراً** مع `DEMO_DATA=true` أو `DEBUG=true` أو
  `AI_PROVIDER=mock` أو حدّ rate limit أعلى من 300 أو `CORS_ORIGINS=*`.
- `/api/docs` و`/api/openapi.json` يُغلقان تلقائياً عندما
  `APP_ENV=production` بلا `DEBUG=true`، ويظهر ذلك في `GET /health`
  (`docs`, `demo_data`, `debug`).

تأسيس الإدارة على قاعدة خالية (بدون demo seed):

```powershell
python tools/create_admin.py --email admin@your-domain.com --password '<قوي>'
```

> على قاعدة خالية مع `DEMO_DATA=false` لا يوجد منهج تلقائياً — ارفع المنهج
> من `/admin` (مسار النشر §83: `draft → processing → validated → published`).

## 2. بناء الإصدار

الطريقة المدعومة — أمر واحد يتحقق ثم يبني ثم يفحص الحزمة:

```powershell
python tools/build_release.py
```

ثلاث مراحل، والنتيجة واحدة فقط إذا نجحت الثلاث:

1. **التحقق** — `pytest` ← `tools/smoke_api.py` ← `tools/e2e.py` ←
   `tools/uat.py` ← `tools/check_frontend_routes.py` ← `npm run build` ←
   `tools/e2e_browser.py`.
2. **التجميع** — `release/` يحتوي كود backend + `.next` إنتاجي + `.env`
   مولّدة من `prod.env.example` (سرّ عشوائي جديد + مفتاح Gemini إن وُجد)،
   **دون** `mors.db` أو `uploads` أو `node_modules` أو `.env` التطوير.
3. **فحص الحزمة** — يُقلع `release/` فعلياً كعملية إنتاج: `/health`
   يعيد `env=production` و`demo_data=false` و`docs=false`، `/api/docs` → 404،
   لا حساب `demo@mors.ai`، `users=0`، rate limit يُرجع 429، وقيمة
   `SECRET_KEY` التطوير ترفض عند الإقلاع.

`--skip-verify` يتجاوز المرحلة 1 فقط (الحزمة تُفحص دائماً).

بناء الواجهة يدوياً (إن أردت `.next` فقط):

```powershell
cd frontend
npm ci
npm run build          # .next/ إنتاجي
```

`frontend/.env` (اختياري إن تغيّر الهدف):

```env
API_TARGET=http://127.0.0.1:8000     # افتراضي next.config.mjs
```

## 3. التشغيل

### Windows (PowerShell)

```powershell
# backend
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (نافذة أخرى)
cd frontend
npm start                           # next start — بورت 3000
```

### Linux (systemd اقتراح)

```ini
# /etc/systemd/system/mors-backend.service
[Service]
WorkingDirectory=/opt/mors/backend
ExecStart=/opt/mors/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
EnvironmentFile=/opt/mors/.env
Restart=always
User=mors

# /etc/systemd/system/mors-frontend.service
[Service]
WorkingDirectory=/opt/mors/frontend
ExecStart=/usr/bin/npm start
Environment=API_TARGET=http://127.0.0.1:8000
Restart=always
User=mors
```

### ما يفعله الإقلاع تلقائياً

1. `init_db()` — إنشاء الجداول الناقصة + ترحيل الأعمدة الجديدة
   (`docs/DATABASE.md`).
2. `seed_if_empty()` عند `DEMO_DATA=true` فقط.
3. `start_scheduler()` عند `SCHEDULER_ENABLED=true` و`APP_ENV != test`:
   نشر المحتوى المستحق، إغلاق جلسات معلّقة، تنظيف عدّادات الحصة.
   التوقف النظيف في `finally` من lifespan.

## 4. الطبقة الأمامية (Reverse Proxy)

الواجهة تمرّر `/api/*` و`/health` إلى `API_TARGET` — أمام الإنتاج ضع
proxy يُنهي TLS وينقل الحركة:

```nginx
location / { proxy_pass http://127.0.0.1:3000; }          # frontend
location /api/ { proxy_pass http://127.0.0.1:8000/api/; }  # backend مباشرة أسرع
location /health { proxy_pass http://127.0.0.1:8000/health; }
```

مع `CORS_ORIGINS=https://your-domain.com` ليطابق Origin الحقيقي
(الواجهة نفسها same-origin عبر rewrite، لكن الأدوات/الموبايل تحتاجه).

## 5. الأمان قبل الفتح

- [ ] `SECRET_KEY` ليس قيمة تطوير — `dev-only-change-me` /
      `change-me-before-production` أو فارغ **تُرفض عند الإقلاع**
- [ ] `DEBUG=false`
- [ ] `UPLOAD_DIR` خارج الوصول العام وصلاحيات مستخدم الخدمة فقط
- [ ] HTTPS إلزامي ( terminate عند الـ proxy )
- [ ] لا حسابات تجريبية: `DEMO_DATA=false` تعني قاعدة خالية
      (`demo@mors.ai` و`admin@mors.ai` يُزرعان في التطوير فقط)
- [ ] أول حساب أُنشئ بـ`python tools/create_admin.py` بعبارة مرور قوية
      ودُوّن خارج مستودع الكود
- [ ] نسخ احتياطي مجدول لـ`DATABASE_URL` + `UPLOAD_DIR` معاً
- [ ] حدود المعدل مفعّلة (الافتراضيات 120/30 في الدقيقة) — القيمة `0`
      تُرفض عند الإقلاع

## 6. التحقق بعد النشر

```powershell
# الخادم
curl http://127.0.0.1:8000/health
# الواجهة
curl http://127.0.0.1:3000/
# رحلة قبول كاملة على القاعدة الفعلية (من جذر المشروع)
python -X utf8 tools/uat.py
python -X utf8 tools/smoke_api.py
python -m pytest -q
```

باب OpenAPI `/api/docs` يُغلق تلقائياً عندما `APP_ENV=production` بلا
`DEBUG=true` (ينعكس في `GET /health` كحقل `docs`)، فلا يحتاج إخفاءً يدوياً.
إن احتجته للتشخيص مؤقتاً ارفع `DEBUG=true` وأطفئه بعده.

## 7. الترقية

1. نسخ احتياطي (قاعدة + uploads).
2. سحب الكود الجديد.
3. `pip install -r requirements.txt` + `npm ci && npm run build`.
4. إعادة تشغيل الخدمتين — الترحيل الآني يطابق الـ schema بنفس الإقلاع.
5. شغّل `tools/uat.py` و`tools/smoke_api.py` للتأكد.

## 8. التوسع لاحقاً

- **PostgreSQL:** بدّل `DATABASE_URL` وراجع بنود SQLite في
  `db/__init__.py` (أعد بناء `questions` إن لزم) — `docs/DATABASE.md`.
- **خادمان/نصفيان:** `UPLOAD_DIR` يجب أن يصبح مشتركاً (قرص موحّد).
- **عناوين مصادر رسمية:** الرفع من `/admin` + مسار النشر §83 المبني في P6.
