# إعداد الذكاء الاصطناعي (AI Setup)

## المزوّدات

| `AI_PROVIDER` | المتطلب | الاستخدام |
| --- | --- | --- |
| `mock` (الافتراضي) | لا شيء | استجابات تحاكي بنية الحقيقة محلياً — تطوير/اختبار بلا إنترنت وبلا مفاتيح |
| `gemini` | `GEMINI_API_KEY` | نموذج حقيقي عبر Google Gemini |

التبديل سطر واحد في `.env` (جذر المشروع) — لا كود يُعدَّل:

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

جميع الاستدعاءات تمرّ عبر `app/ai/orchestrator.py` (`ask(AIRequest(...))`)،
ومزوّد واحد لا يصلح مهمة ← يسقط المشروع إلى مسار آمن محلي (لا تخمين).

## النماذج

```env
AI_MODEL=gemini-flash-latest              # عام
AI_FAST_MODEL=gemini-flash-latest         # ردود سريعة (الدردشة)
AI_REASONING_MODEL=gemini-flash-latest    # تحليل أعمق (المرشد)
AI_VISION_MODEL=gemini-flash-latest       # فهم الصور المرفوعة
```

## الحدود والتكلفة

```env
AI_DAILY_TOKEN_BUDGET=400000      # سقف يومي للاستهلاك
AI_CACHE_TTL_SECONDS=600          # كاش ردود الأسئلة المكررة
AI_TIMEOUT_SECONDS=45             # مهلة استدعاء واحد
AI_MAX_HISTORY_MESSAGES=12        # أقصى رسالة تُرسل كسجل حوار
AI_RATE_LIMIT_PER_MINUTE=30       # طلبات ذكاء/دقيقة لكل مستخدم (العام RATE_LIMIT_PER_MINUTE للأطراف)
```

الاستهلاك والفهارس تُعرض للإدارة على `/admin` (`/api/admin/usage`).

## التعليمة (Prompts)

- القوالب الافتراضية في `app/ai/prompts.py` وتُزرع في جدول `ai_prompts`.
- الإدارة تعدّلها من `/admin` → `GET/PUT /api/admin/prompts/{key}`
  (القالب المعدَّل في القاعدة يفوز على الافتراضي ثم يُستعاد بـ reset).

## الصوت (§15/§70/§71)

```env
AI_TTS_PROVIDER=browser     # Web Speech API داخل متصفح الطالب — بلا مفتاح
AI_STT_PROVIDER=browser
AI_TTS_VOICE=system
AI_VOICE_MAX_CHARS=800
```

- `browser` يعمل دون أي خدمة خارجية؛ النبرة/السرعة تُضبط على الخادم
  (`POST /api/voice/speak` يعيد `provider/rate/pitch/style`).
- المزوّدان يُستبدلان لاحقاً بالضبط (`openai | elevenlabs`) دون تغيير كود
  الواجهة.

## OCR والصور المرفوعة

- استخراج نص الصور في `app/rag/ocr.py` يتطلب **Tesseract** محلياً **أو**
  `GEMINI_API_KEY` (نموذج الرؤية). إن غاب الاثنان يُرفع الملف وتظهر حالته
  للطالب بصدق ولا يفشل الرفع.

## RAG (استدعاء الكتاب في الإجابات)

```env
RAG_CHUNK_SIZE=900
RAG_CHUNK_OVERLAP=150
RAG_TOP_K=6
RAG_MIN_SCORE=0.12
```

قواعد الحماية في الكود لا في التعليمة: سؤال منهج بلا مصدر موثوق ← رد صريح
«ما لقيت مصدراً» بدل التخمين (يظهر بوضوح في `tools/uat.py` — فحص
`mors_chat_page_citation` و`mors_refuses_off_topic`).

## قواعد ذهبية للاختبار

- الاختبارات و`tools/uat.py` تجبر `AI_PROVIDER=mock` و`RATE_LIMIT` عالياً —
  لا تعتمد على مفتاح حقيقي في CI.
- أبداً لا تضع `GEMINI_API_KEY` داخل `frontend/` أو المستودع: مكانه
  `.env` في جذر المشروع فقط (ملف `.gitignore` يغطّيه).
