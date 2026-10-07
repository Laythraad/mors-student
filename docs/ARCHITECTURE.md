# Mors.ai — Architecture

> مدرس شخصي ذكي للطالب العراقي — Educational Operating System.

This document is the contract every module in this repository obeys. It is
written before the code, and the code is written against it.

---

## 1. Shape of the system

```
┌──────────────────────────────────────────────────────────────────────┐
│  frontend/   Next.js (App Router) · TypeScript · Arabic-first RTL    │
│  ─────────────────────────────────────────────────────────────────── │
│  Design tokens · Mors character runtime · Speech bubble · Focus mode │
└───────────────┬──────────────────────────────────────────────────────┘
                │  JSON/HTTP  (Bearer JWT)
┌───────────────▼──────────────────────────────────────────────────────┐
│  backend/    FastAPI · SQLAlchemy 2 · SQLite (→ PostgreSQL ready)    │
│                                                                      │
│  api/        thin HTTP layer: auth, students, curriculum, planner,   │
│              sessions, chat, quizzes, papers, notes, search, video,  │
│              teachers, progress, notifications, admin, mors, export  │
│                                                                      │
│  services/   business logic, no HTTP objects                        │
│  mors/       Personality Engine + Event Bus + State machine         │
│  ai/         AI Router → Orchestrator → Agents → Providers          │
│  rag/        PDF → OCR → clean → chunk → embed → index → retrieve   │
│  db/         models · session · seed (DEMO curriculum)              │
│  core/       config · security · errors · rate limit · deps         │
└──────────────────────────────────────────────────────────────────────┘
```

Two rules keep it honest:

* **No HTTP objects below `api/`.** Services take plain arguments and return
  plain data, so every feature is unit-testable without a server.
* **The curriculum never lives in the frontend.** Stage / branch / subject /
  book / chapter / unit / lesson / page / source are rows, not constants.

---

## 2. Database schema (grouped)

| Group | Tables |
|---|---|
| Identity | `users`, `roles`, `user_roles`, `refresh_tokens` |
| Learner | `student_profiles`, `student_subjects`, `study_preferences`, `learning_profiles` |
| Curriculum | `stages`, `branches`, `subjects`, `curriculums`, `books`, `chapters`, `units`, `lessons`, `lesson_pages`, `sources` |
| Planning | `study_plans`, `plan_days`, `tasks`, `exams`, `events` |
| Study | `study_sessions`, `session_notes`, `reviews`, `breaks` |
| Assessment | `quizzes`, `questions`, `options`, `quiz_attempts`, `answers`, `mastery_scores`, `weak_topics` |
| Knowledge | `papers`, `paper_pages`, `paper_blocks`, `paper_sources`, `notes`, `summaries`, `flashcards` |
| Media | `videos`, `video_progress`, `teachers`, `teacher_courses`, `uploads` |
| AI | `ai_conversations`, `ai_messages`, `ai_events`, `ai_usage`, `ai_prompts`, `ai_chunks` |
| Mors | `mors_states`, `mors_events`, `mors_messages` |
| System | `notifications`, `achievements`, `student_achievements`, `search_index`, `settings` |

Every row that carries curriculum content also carries a `source_id` so an
answer can always be traced to *book → chapter → lesson → page*.

`stage_id` / `branch_id` are foreign keys everywhere — nothing is hard-coded
to "الرابع العلمي". The first seed ships that stage only, and is labelled
`DEMO`.

---

## 3. AI architecture

### 3.1 Configuration, never literals

```
AI_PROVIDER        = "gemini" | "mock"
AI_MODEL           primary reasoning model          (Gemini Flash class)
AI_FAST_MODEL      cheap model for short/repetitive calls
AI_REASONING_MODEL strong model for planning / exam building
AI_VISION_MODEL    image understanding
```

No file other than `app/ai/config.py` may mention a model name.

### 3.2 Router → Orchestrator → Agents

```
request ─► AI Router ─► picks (model, agent, budget)
              │
              ▼
         Orchestrator ──► assembles context (profile + curriculum + RAG + history)
              │
              ├── TutorAgent         explanations, Socratic hints
              ├── PlannerAgent       daily plan, recovery plan, exam plan
              ├── QuizAgent          question generation, adaptive grading
              ├── SummarizerAgent    summaries, study sheets, flashcards
              ├── ExamAgent          mock exams, difficulty ladder
              ├── StudyCoachAgent    morning briefing, night review
              ├── PaperAgent         structured paper blocks
              ├── VisionAgent        OCR, handwritten-note understanding
              └── CurriculumAgent    syllabus reasoning, source lookup
              │
              ▼
         Provider (Gemini | Mock) ─► validated structured output
```

Routing table (cost control):

| Task | Agent | Model tier |
|---|---|---|
| greeting / chit-chat | Tutor | fast |
| lesson explanation | Tutor | primary |
| plan / 5-day recovery | Planner + Exam | reasoning |
| quiz item generation | Quiz | primary |
| one-line summary / title | Summarizer | fast |
| image → text | Vision | vision |

### 3.3 Cost controls

response cache keyed by `(model, prompt_hash, context_hash)` · request
de-duplication (in-flight) · conversation summaries instead of full history ·
RAG retrieval instead of whole-book prompting · structured output so a failed
parse never costs a second round trip · per-user daily token budget.

### 3.4 Anti-hallucination

The model receives **retrieved chunks only**, each with a `source_id`. The
response schema requires `citations[]`; the service drops any citation whose
`source_id` is not in the retrieved set. If retrieval returns nothing the
agent is instructed to answer `no_source_found` rather than invent a page.
Low-confidence answers are surfaced as low-confidence — never as fact.

---

## 4. Mors character architecture

### 4.1 Assets

`tools/slice_character_sheet.py` cuts the official sheet into
`frontend/public/mors/<state>.png` (transparent) and writes
`assets/character/sprite_map.json`. The source art is never modified.

### 4.2 State machine

16 system states, each mapped to an official expression:

| State | Sprite | When |
|---|---|---|
| `IDLE` | neutral | no activity |
| `HAPPY` | happy | session started, student returned |
| `EXCITED` | excited | streak, new record |
| `PROUD` | smug | completed something hard |
| `CURIOUS` | wink | asking the student a question |
| `THINKING` | thinking | reasoning / hint generation |
| `CONFUSED` | confused | ambiguous student input |
| `CONCERNED` | sad | missed tasks, falling behind |
| `DISAPPOINTED` | crying | repeated non-commitment (gentle only) |
| `ENCOURAGING` | peaceful | after a mistake |
| `CELEBRATING` | hype | high score, mastery |
| `SURPRISED` | shocked | big improvement |
| `FOCUSED` | cool | "ماذا أدرس الآن" / exam mode |
| `SLEEPY` | tired | late night, break time |
| `STUDYING` | neutral | during an active session |
| `OVERWHELMED` | overwhelmed | too much backlog — triggers recovery |

Forbidden: any state whose message shames, insults or threatens. Enforced by
`mors/messages.py` (tone validator) and a unit test over every template.

### 4.3 Personality Engine

```
StudentEvent + Progress + Context ─► PersonalityEngine ─► {expression, tone, message, animation, priority, ttl}
```

The engine is **contextual, not threshold-based**. `90%` after `30%` →
`CELEBRATING`; `90%` while fundamentals are still broken → `CONCERNED`;
`60%` after `30%` → `PROUD`. Rules read mastery delta, trend, streak and
error pattern — not just the raw score.

### 4.4 Event bus

`EVENT_STUDY_STARTED`, `EVENT_STUDY_COMPLETED`, `EVENT_TASK_MISSED`,
`EVENT_EXAM_PASSED`, `EVENT_EXAM_FAILED`, `EVENT_STREAK_CREATED`,
`EVENT_STREAK_BROKEN`, `EVENT_NEW_RECORD`, `EVENT_RETURNED_AFTER_ABSENCE`,
`EVENT_WEAK_TOPIC_DETECTED`, `EVENT_LESSON_MASTERED`, …

One event fans out to independent handlers: update progress → update mastery
→ schedule review → update streak → change Mors → generate feedback → send
notification. Handlers are registered, never inlined in a route.

### 4.5 Notification discipline

Focus Mode suppresses everything except session start, critical error, session
end and student-initiated messages. Every student can set per-category
frequency; idle chatter is opt-in.

---

## 5. Development phases

| Phase | Scope | Gate |
|---|---|---|
| **P0** | repo skeleton, config, DB models, seed, sprite pipeline | `pytest` green |
| **P1** | auth + onboarding + profile | register→profile E2E |
| **P2** | curriculum, planner, sessions, Mors engine, chat | core loop E2E |
| **P3** | quizzes, adaptive testing, mastery, reviews, progress | quiz → plan feedback |
| **P4** | papers, notes, summaries, flashcards, canvas, upload | paper CRUD + export |
| **P5** | RAG pipeline, videos, teachers, search, coach, notifications | retrieval with citations |
| **P6** | admin CMS, prompt management, roles, security | admin E2E |
| **P7** | frontend all views, RTL, accessibility, responsive | UAT as a real student |

Each phase ends with `pytest` + a manual pass. Nothing is declared done on
"the page renders".

---

## 6. Definition of done

The student can register → choose stage/branch/subjects → set time → receive
a plan → study → talk to Mors → get an explanation → build a summary → build
a paper → watch a lesson → take a quiz → read the analysis; the system knows
their weak topics, schedules review, and Mors changes with their events —
while they can see their progress.
