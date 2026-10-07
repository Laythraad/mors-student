"""Development / demo seed data.

Everything created here carries `is_demo = True` so the UI can label it
honestly. The seed is idempotent: it only runs when the tables are empty.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .db import (
    Achievement,
    Branch,
    Book,
    BookPage,
    Chapter,
    Course,
    Curriculum,
    Lesson,
    SessionLocal,
    Source,
    Stage,
    Subject,
    Teacher,
    Unit,
    User,
    Video,
    init_db,
)

DEMO_PAGE_NOTICE = (
    "صفحة تجريبية أنشأها النظام من ملخص الدرس وأهدافه لعرض تجربة القارئ. "
    "النص الرسمي للكتاب يُرفع من لوحة الإدارة ثم يُستخرج تلقائياً."
)

# §36 — real, publicly-licensed lesson videos found via YouTube search and
# confirmed with the oEmbed API (title + author) before being stored here.
# A lesson with no verified video gets NO video row, rather than a link that
# cannot play. Never invent a video id: add to this map only after verifying.
# `channel` is the real uploader — it is stored as provenance so the video is
# never presented as if the fictional demo teacher had recorded it.
VERIFIED_VIDEOS: dict[str, dict[str, str]] = {
    "المتتاليات الحسابية": {
        "url": "https://www.youtube.com/watch?v=cQ835dUifbM",
        "channel": "MK Academy",
        "video_title": "أ. قصي البابا - المتتاليات - المتتالية الحسابية",
    },
    "المتتاليات الهندسية": {
        "url": "https://www.youtube.com/watch?v=lXeKCNsmuNA",
        "channel": "Moosa TV",
        "video_title": "مفهوم المتتاليات الهندسية",
    },
    "الدوال الأسية": {
        "url": "https://www.youtube.com/watch?v=hPTBcInewVw",
        "channel": "حيدر عبدالائمة",
        "video_title": "رياضيات السادس العلمي — شرح الدالة الأسية",
    },
    "الحركة بعجلة منتظمة": {
        "url": "https://www.youtube.com/watch?v=9vxKIQxR0Xk",
        "channel": "فيزياء كليب — عبد الرحمن شريف",
        "video_title": "معادلات الحركة بعجلة منتظمة",
    },
    "الشغل والقدرة": {
        "url": "https://www.youtube.com/watch?v=0vaK_2Q-VKs",
        "channel": "أكاديمية التحرير",
        "video_title": "مفهوم الشغل والقدرة | الشغل والقدرة والطاقة",
    },
    "الطاقة والحفظ": {
        "url": "https://www.youtube.com/watch?v=atEQ443z7SQ",
        "channel": "استاذ حسين محمد",
        "video_title": "فيزياء السادس علمي — مبدأ حفظ الطاقة",
    },
    "الجدول الدوري": {
        "url": "https://www.youtube.com/watch?v=hNO4gQ25SC0",
        "channel": "قناة الاستاذ حسين العراقي 2",
        "video_title": "جدول العناصر الكيميائية وروموزها وشحنتها — كيمياء السادس العلمي",
    },
    "الروابط الكيميائية": {
        "url": "https://www.youtube.com/watch?v=c9_Rkidi14g",
        "channel": "إلكترون Electron",
        "video_title": "الروابط الكيميائية",
    },
    "الخلية": {
        "url": "https://www.youtube.com/watch?v=KBe_S0Sxdy4",
        "channel": "الاستاذ ماهر نايف",
        "video_title": "المحاضرة الأولى — الفصل الأول: الخلية — السادس العلمي",
    },
    "التغذية والهضم": {
        "url": "https://www.youtube.com/watch?v=6tOVUIrN4a4",
        "channel": "الاستاذ الدكتور سجاد حمزة",
        "video_title": "التغذية والهضم — الفصل الأول",
    },
}

logger = logging.getLogger(__name__)

DEMO_PASSWORD = "DemoPass123!"
DEMO_STUDENT_EMAIL = "demo@mors.ai"
DEMO_ADMIN_EMAIL = "admin@mors.ai"

ACHIEVEMENTS: list[dict[str, Any]] = [
    {"code": "first_session", "name": "الخطوة الأولى", "description": "أنهيت أول جلسة دراسة.", "icon": "🌱", "metric": "sessions", "threshold": 1},
    {"code": "session_10", "name": "عشر جلسات", "description": "أكملت عشر جلسات دراسة.", "icon": "📚", "metric": "sessions", "threshold": 10},
    {"code": "session_50", "name": "خمسون جلسة", "description": "أكملت خمسين جلسة دراسة.", "icon": "🏅", "metric": "sessions", "threshold": 50},
    {"code": "minutes_600", "name": "عشر ساعات", "description": "درست 600 دقيقة إجمالاً.", "icon": "⏳", "metric": "study_minutes", "threshold": 600},
    {"code": "minutes_3000", "name": "خمسون ساعة", "description": "درست 3000 دقيقة إجمالاً.", "icon": "🌟", "metric": "study_minutes", "threshold": 3000},
    {"code": "quiz_first", "name": "أول اختبار", "description": "أنهيت أول اختبار.", "icon": "✍️", "metric": "quizzes", "threshold": 1},
    {"code": "quiz_25", "name": "خمسة وعشرون اختباراً", "description": "أنهيت 25 اختباراً.", "icon": "🎯", "metric": "quizzes", "threshold": 25},
    {"code": "task_20", "name": "عشرون مهمة", "description": "أنجزت 20 مهمة من خطتك.", "icon": "✅", "metric": "tasks", "threshold": 20},
    {"code": "task_100", "name": "مئة مهمة", "description": "أنجزت 100 مهمة من خطتك.", "icon": "🏆", "metric": "tasks", "threshold": 100},
    {"code": "streak_3", "name": "ثلاثة أيام متتالية", "description": "درست ثلاثة أيام متتالية.", "icon": "🔥", "metric": "streak", "threshold": 3},
    {"code": "streak_7", "name": "أسبوع كامل", "description": "درست سبعة أيام متتالية.", "icon": "⚡", "metric": "streak", "threshold": 7},
    {"code": "streak_30", "name": "شهر من الالتزام", "description": "درست 30 يوماً متتالياً.", "icon": "👑", "metric": "streak", "threshold": 30},
    {"code": "paper_first", "name": "أول ورقة عمل", "description": "أنشأت أول ورقة عمل.", "icon": "🗂️", "metric": "papers", "threshold": 1},
]

# code, name_ar, name_en, color, icon
SUBJECTS: list[tuple[str, str, str, str, str]] = [
    ("MATH", "الرياضيات", "Mathematics", "#2f8ff7", "📐"),
    ("PHY", "الفيزياء", "Physics", "#7c5cff", "⚛️"),
    ("CHEM", "الكيمياء", "Chemistry", "#16b981", "🧪"),
    ("BIO", "الأحياء", "Biology", "#f59e0b", "🧬"),
    ("ARB", "اللغة العربية", "Arabic", "#ef4444", "📖"),
    ("ENG", "اللغة الإنجليزية", "English", "#ec4899", "🔤"),
    ("ISL", "التربية الإسلامية", "Islamic Education", "#0ea5e9", "🕌"),
]

LESSONS: dict[str, list[tuple[str, str, list[str], list[str]]]] = {
    "MATH": [
        ("المتتاليات الحسابية", "تعريف المتتالية الحسابية وخصائصها وقانون الحد العام.", ["يحدد الحد الأول", "يحسب الفرق المشترك", "يكتب قانون الحد العام"], ["متتالية", "فرق مشترك", "الحد العام"]),
        ("المتتاليات الهندسية", "المتتالية الهندسية والنسبة العامة وقانون الحد العام.", ["يحدد النسبة العامة", "يحسب الحد العاشر", "يميّز بين الحسابي والهندسي"], ["متتالية هندسية", "نسبة مشتركة"]),
        ("الدوال الأسية", "دالة الأس وخصائصها ومشتقتها.", ["يعرّف الدالة الأسية", "يحسب مشتقة الدالة", "يحل معادلات أسية"], ["أسية", "لوغاريتم", "مشتقة"]),
        ("الاحتمالات", "مبادئ العد والتوزيع الاحتمالي البسيط.", ["يعدّ الحالات الممكنة", "يحسب احتمال حدث", "يميّز بين المجرّدة والمركّبة"], ["احتمال", "عدّ", "توزيع"]),
    ],
    "PHY": [
        ("الحركة بعجلة منتظمة", "العلاقة بين الإزاحة والزمن والسرعة الابتدائية.", ["يكتب معادلات الحركة", "يحسب الزمن والسرعة", "يرسم الرسوم البيانية"], ["حركة", "عجلة", "سرعة"]),
        ("الشغل والقدرة", "تعريف الشغل والقدرة وتحويل الوحدات.", ["يحسب الشغل", "يحسب القدرة", "يوحد الوحدات"], ["شغل", "قدرة", "جول"]),
        ("الطاقة والحفظ", "تحوّل الطاقة الكامنة والحركة وقانون حفظ الطاقة.", ["يعدّ مصادر الطاقة", "يطبّق حفظ الطاقة", "يحسب طاقة الوضع"], ["طاقة", "حفظ", "احتكاك"]),
    ],
    "CHEM": [
        ("الجدول الدوري", "تصنيف العناصر وخصائص الدورات.", ["يحدد الموقع في الجدول", "يقارن نشأة الفلزات", "يتنبأ بخصائص العنصر"], ["جدول دوري", "فلز", "لافلز"]),
        ("الروابط الكيميائية", "الأيونية والتساهمية وخصائص كل منها.", ["يميّز أنواع الروابط", "يكتب الصيغة", "يشرح درجة الانصهار"], ["رابطة", "تساهمي", "أيوني"]),
    ],
    "BIO": [
        ("الخلية", "تركيب الخلية ووظائف عضياتها.", ["يميّز الخلية النباتية عن الحيوانية", "يحدد وظيفة العضية", "يشرح نقل المواد"], ["خلية", "عضية", "غشاء"]),
        ("التغذية والهضم", "مراحل الهضم وامتصاص الغذاء.", ["يتتبّع مسار الغذاء", "يشرح الإنزيمات", "يحسب الطاقة"], ["تغذية", "هضم", "إنزيم"]),
    ],
    "ARB": [
        ("الأساليب النحوية", "التمييز بين الأساليب البلاغية والنحوية.", ["يميّز أسلوب النفي", "يعرّف أسلوب التفاؤل", "يستخرج الجملة"], ["نحو", "أسلوب", "بلاغة"]),
        ("الأدب العصر النهضة", "خصائص شعر النهضة وأعلامه.", ["يحدد خصائص العصر", "يعرّف أبرز الأعلام", "يقارن الاتجاهات"], ["نهضة", "شعر", "أدب"]),
    ],
    "ENG": [
        ("Tenses", "Past, present and future forms.", ["identifies tense", "forms the verb", "writes sentences"], ["tense", "verb", "grammar"]),
        ("Vocabulary building", "Word families and context clues.", ["uses context clues", "builds word families", "spells correctly"], ["vocabulary", "spelling"]),
    ],
    "ISL": [
        ("علوم القرآن", "أسباب النزول وخصائص القرآن.", ["يعدّ سور القرآن", "يشرح أسباب النزول", "يعرّف المكية والمدنية"], ["قرآن", "نزول", "سورة"]),
        ("فقه العبادات", "أحكام الطهارة والصلاة.", ["يعدد أركان الصلاة", "يشرح أسباب الطهارة", "يفرّق بين الفرض والسنة"], ["عبادة", "طهارة", "صلاة"]),
    ],
}

# code -> (chapter_title, [(unit_title, [lesson titles...])])
STRUCTURE: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {
    "MATH": ("الرياضيات للصف الرابع العلمي", [("الوحدة الأولى: المتتاليات", ["المتتاليات الحسابية", "المتتاليات الهندسية"]), ("الوحدة الثانية: التفاضل", ["الدوال الأسية"]), ("الوحدة الثالثة: الاحتمالات", ["الاحتمالات"])]),
    "PHY": ("الفيزياء للصف الرابع العلمي", [("الوحدة الأولى: الميكانيك", ["الحركة بعجلة منتظمة"]), ("الوحدة الثانية: الطاقة", ["الشغل والقدرة", "الطاقة والحفظ"])]),
    "CHEM": ("الكيمياء للصف الرابع العلمي", [("الوحدة الأولى: البنية الذرية", ["الجدول الدوري", "الروابط الكيميائية"])]),
    "BIO": ("الأحياء للصف الرابع العلمي", [("الوحدة الأولى: الخلية", ["الخلية"]), ("الوحدة الثانية: التغذية", ["التغذية والهضم"])]),
    "ARB": ("اللغة العربية للصف الرابع العلمي", [("الوحدة الأولى: النحو", ["الأساليب النحوية"]), ("الوحدة الثانية: الأدب", ["الأدب العصر النهضة"])]),
    "ENG": ("English Grade 12 Science", [("Unit 1: Grammar", ["Tenses"]), ("Unit 2: Skills", ["Vocabulary building"])]),
    "ISL": ("التربية الإسلامية للصف الرابع العلمي", [("الوحدة الأولى: القرآن", ["علوم القرآن"]), ("الوحدة الثانية: الفقه", ["فقه العبادات"])]),
}

STAGES: list[dict[str, Any]] = [
    {"code": "grade6", "name_ar": "السادس الابتدائي", "name_en": "Grade 6 Primary", "sort_order": 1, "branches": []},
    {"code": "grade9", "name_ar": "الثالث المتوسط", "name_en": "Grade 9 Preparatory", "sort_order": 2, "branches": []},
    {
        "code": "grade12",
        "name_ar": "الرابع العلمي",
        "name_en": "Grade 12 Science",
        "sort_order": 3,
        "branches": [
            {"code": "science", "name_ar": "علمي", "name_en": "Science", "track": "science"},
            {"code": "literary", "name_ar": "أدبي", "name_en": "Literary", "track": "literary"},
        ],
    },
]

TEACHERS: list[dict[str, Any]] = [
    {"name": "أ. سارة الحسيني", "slug": "sara", "headline": "معلمة رياضيات — خبرة 12 سنة", "bio": "شرح مبسّط مع أمثلة محلولة لكل درس.", "style": "step-by-step", "subjects": ["MATH"], "rating": 4.8, "rating_count": 412},
    {"name": "أ. علي الجبوري", "slug": "ali", "headline": "معلم فيزياء ورياضيات", "bio": "يركّز على الفهم قبل الحفظ.", "style": "conceptual", "subjects": ["PHY", "MATH"], "rating": 4.7, "rating_count": 268},
    {"name": "أ. نور الهدى", "slug": "noor", "headline": "معلمة كيمياء وأحياء", "bio": "تجارب ورؤوس ألسنة تثبّت المعلومة.", "style": "visual", "subjects": ["CHEM", "BIO"], "rating": 4.9, "rating_count": 190},
]


def seed_achievements(db: Session) -> int:
    if db.query(Achievement).count():
        return 0
    for item in ACHIEVEMENTS:
        db.add(Achievement(**item))
    db.flush()
    return len(ACHIEVEMENTS)


def seed_curriculum(db: Session) -> dict[str, int]:
    if db.query(Stage).count():
        return {"skipped": 1}
    counts = {"stages": 0, "subjects": 0, "lessons": 0}

    source = Source(kind="book", title="المنهاج الرسمي — بيانات تجريبية", verified=True, is_demo=True)
    db.add(source)
    db.flush()

    science_stage = None
    for stage_spec in STAGES:
        stage = Stage(
            code=stage_spec["code"],
            name_ar=stage_spec["name_ar"],
            name_en=stage_spec["name_en"],
            sort_order=stage_spec["sort_order"],
            is_demo=True,
        )
        db.add(stage)
        db.flush()
        counts["stages"] += 1

        branches = stage_spec["branches"] or [
            {"code": "general", "name_ar": "عام", "name_en": "General", "track": "general"}
        ]
        for index, branch_spec in enumerate(branches):
            branch = Branch(
                stage_id=stage.id,
                code=branch_spec["code"],
                name_ar=branch_spec["name_ar"],
                name_en=branch_spec.get("name_en", ""),
                track=branch_spec.get("track", "general"),
                sort_order=index,
                is_demo=True,
            )
            db.add(branch)
            db.flush()
            if stage_spec["code"] == "grade12" and branch_spec["code"] == "science":
                science_stage = (stage, branch)
            elif stage_spec["code"] == "grade12":
                science_stage = science_stage or (stage, branch)

            if stage_spec["code"] != "grade12":
                continue

            curriculum = Curriculum(stage_id=stage.id, branch_id=branch.id, title=f'{stage.name_ar} — {branch.name_ar}', academic_year="2025-2026", is_demo=True)
            db.add(curriculum)

            for order, (code, name_ar, name_en, color, icon) in enumerate(SUBJECTS):
                subject = Subject(
                    branch_id=branch.id,
                    code=code,
                    name_ar=name_ar,
                    name_en=name_en,
                    color=color,
                    icon=icon,
                    sort_order=order,
                    is_demo=True,
                )
                db.add(subject)
                db.flush()
                counts["subjects"] += 1

                chapter_spec, units_spec = STRUCTURE[code]
                book = Book(subject_id=subject.id, title=chapter_spec, edition="2025", is_demo=True)
                db.add(book)
                db.flush()
                chapter = Chapter(book_id=book.id, index=1, title=chapter_spec, page_start=1, page_end=120)
                db.add(chapter)
                db.flush()

                lesson_index = 0
                for unit_index, (unit_title, lesson_titles) in enumerate(units_spec, start=1):
                    unit = Unit(chapter_id=chapter.id, index=unit_index, title=unit_title)
                    db.add(unit)
                    db.flush()
                    for title in lesson_titles:
                        meta = next((l for l in LESSONS.get(code, []) if l[0] == title), None)
                        if meta is None:
                            continue
                        lesson_index += 1
                        lesson = Lesson(
                            unit_id=unit.id,
                            chapter_id=chapter.id,
                            subject_id=subject.id,
                            index=lesson_index,
                            title=meta[0],
                            summary=meta[1],
                            objectives=meta[2],
                            keywords=meta[3],
                            difficulty=min(5, 2 + (lesson_index % 3)),
                            estimated_minutes=35 + 10 * (lesson_index % 3),
                            page_start=1 + lesson_index * 8,
                            page_end=8 + lesson_index * 8,
                            source_id=source.id,
                            prerequisites=[],
                            is_demo=True,
                        )
                        db.add(lesson)
                        lesson_index += 0
                    db.flush()
                counts["lessons"] += lesson_index

    db.flush()
    return counts


def seed_media(db: Session) -> int:
    if db.query(Teacher).count():
        return 0
    made = 0
    stage = db.query(Stage).filter(Stage.code == "grade12").first()
    branch = db.query(Branch).filter(Branch.code == "science").first()
    subject_by_code = {s.code: s for s in db.query(Subject).all()}

    for teacher_spec in TEACHERS:
        teacher = Teacher(
            name=teacher_spec["name"],
            slug=teacher_spec["slug"],
            headline=teacher_spec["headline"],
            bio=teacher_spec["bio"],
            style=teacher_spec["style"],
            subjects=teacher_spec["subjects"],
            stages=["grade12"],
            lessons_count=48,
            duration_minutes=3200,
            has_summaries=True,
            has_tests=True,
            level="متوسط",
            rating=teacher_spec["rating"],
            rating_count=teacher_spec["rating_count"],
            verified=True,
            is_demo=True,
        )
        db.add(teacher)
        db.flush()
        made += 1

        for code in teacher_spec["subjects"]:
            subject = subject_by_code.get(code)
            if subject is None:
                continue
            course = Course(
                teacher_id=teacher.id,
                subject_id=subject.id,
                stage_id=stage.id if stage else None,
                branch_id=branch.id if branch else None,
                title=f'{subject.name_ar} — شرح كامل ({teacher.name})',
                description="شرح المنهج كاملاً مع ملخصات واختبارات.",
                level="متوسط",
                is_demo=True,
            )
            db.add(course)
            db.flush()

            lessons = (
                db.query(Lesson)
                .filter(Lesson.subject_id == subject.id)
                .order_by(Lesson.index)
                .limit(3)
                .all()
            )
            for position, lesson in enumerate(lessons, start=1):
                verified = VERIFIED_VIDEOS.get(lesson.title)
                if not verified:
                    # no verified lesson video yet — do not ship a dead link
                    continue
                db.add(
                    Video(
                        course_id=course.id,
                        teacher_id=teacher.id,
                        subject_id=subject.id,
                        lesson_id=lesson.id,
                        title=f'{lesson.title} — شرح مكثف',
                        url=verified["url"],
                        description=(
                            f'{verified["video_title"]}\n'
                            f'المصدر: قناة يوتيوب «{verified["channel"]}» '
                            f'— رابط مُتحقَّق منه رسمياً، لا استضافة ولا تنزيل.'
                        ),
                        duration_seconds=720 + 180 * position,
                        position=position,
                        transcript=(
                            f"{lesson.title}. {lesson.summary} "
                            f"المفاهيم الأساسية: {', '.join(lesson.keywords)}. "
                            f"يتضمّن الفيديو مثالاً محلولاً وملخصاً في النهاية."
                        ),
                        is_demo=True,
                    )
                )
                made += 1
    db.flush()
    return made


def seed_demo_students(db: Session) -> dict[str, str]:
    from .services import auth

    if db.query(User).filter(User.email == DEMO_ADMIN_EMAIL).one_or_none() is None:
        auth.register(db, full_name="مدير المنصة", email=DEMO_ADMIN_EMAIL, password=DEMO_PASSWORD, role="admin")

    existing = db.query(User).filter(User.email == DEMO_STUDENT_EMAIL).one_or_none()
    if existing is not None:
        return {"student": existing.id}

    user = auth.register(db, full_name="طالب تجريبي", email=DEMO_STUDENT_EMAIL, password=DEMO_PASSWORD, role="student")
    db.flush()

    stage = db.query(Stage).filter(Stage.code == "grade12").first()
    branch = db.query(Branch).filter(Branch.code == "science").first()
    subjects = db.query(Subject).filter(Subject.is_demo.is_(True)).all()
    codes = {code for code, *_ in SUBJECTS}
    # enrol in the student's OWN branch: matching by code alone also pulled the
    # literary copies, so the demo student sat in 14 subjects across two shelves
    subject_ids = [
        s.id
        for s in subjects
        if s.code in codes and (branch is None or s.branch_id == branch.id)
    ]

    profile = db.query(auth.StudentProfile).filter(auth.StudentProfile.user_id == user.id).one()
    auth.update_profile(
        db,
        profile,
        {
            "stage_id": stage.id if stage else None,
            "branch_id": branch.id if branch else None,
            "school_name": "مدرسة التجربة",
            "school_start": "08:00",
            "school_end": "14:00",
            "sleep_start": "23:00",
            "sleep_end": "07:00",
            "daily_study_minutes": 90,
            "study_days": [0, 1, 2, 3, 4],
            "free_windows": [{"start": "16:00", "end": "19:00"}],
            "goals": "التحصيل في الرياضيات والفيزياء — هدف تجريبي.",
            "current_level": "medium",
            "onboarding_step": 6,
            "diagnostic_done": True,
        },
    )
    if subject_ids:
        auth.set_subjects(db, profile, subject_ids)
    auth.ensure_learning_profile(db, profile.id)
    auth.ensure_streak(db, profile.id)
    db.flush()

    try:
        from .services import planner

        planner.generate_plan(db, profile.id, days=7, kind="regular", title="الخطة التجريبية", rationale="خطة أولية للتجربة.")
    except Exception:  # noqa: BLE001 - a plan is nice-to-have, never fatal
        logger.exception("demo plan generation failed")

    db.flush()
    return {"student": user.id, "profile": profile.id}


def _lesson_pages(book: Book, chapter: Chapter, unit: Unit, lesson: Lesson) -> list[tuple[str, str]]:
    """Honest demo pages: every line comes from real lesson fields."""
    summary = (lesson.summary or "").strip() or f"درس {lesson.title} ضمن وحدة {unit.title}."
    objectives = [str(o) for o in (lesson.objectives or []) if str(o).strip()]
    keywords = [str(k) for k in (lesson.keywords or []) if str(k).strip()]
    context = f"{book.title} — الفصل: {chapter.title} — الوحدة: {unit.title}"

    cover: list[str] = [summary]
    if objectives:
        cover.append("أهداف الدرس:\n" + "\n".join(f"• {o}" for o in objectives[:5]))
    if keywords:
        cover.append("المصطلحات الأساسية: " + "، ".join(keywords[:8]))
    cover.extend([context, DEMO_PAGE_NOTICE])
    pages: list[tuple[str, str]] = [(lesson.title, "\n\n".join(cover))]

    for index in range(max(1, min(3, len(objectives)))):
        block = objectives[index * 2 : index * 2 + 2] or objectives
        parts = ["نقاط هذه الصفحة:\n" + "\n".join(f"• {o}" for o in block)]
        if keywords:
            slice_ = keywords[index * 3 : index * 3 + 3] or keywords
            parts.append("راجع المصطلحات: " + "، ".join(slice_))
        parts.append(f"بعد القراءة: اشرح {lesson.title} بكلماتك، ثم سجّل ملاحظتك هنا.")
        parts.append(DEMO_PAGE_NOTICE)
        pages.append((f"{unit.title} — {index + 2}", "\n\n".join(parts)))

    return pages


def seed_book_pages(db: Session) -> int:
    """Give every demo book real page rows so the reader and citations work."""
    books = db.query(Book).all()
    made = 0
    for book in books:
        if db.query(BookPage).filter(BookPage.book_id == book.id).count():
            continue
        chapters = db.query(Chapter).filter(Chapter.book_id == book.id).order_by(Chapter.index).all()
        if not chapters:
            continue
        page_number = 0
        for chapter in chapters:
            units = db.query(Unit).filter(Unit.chapter_id == chapter.id).order_by(Unit.index).all()
            for unit in units:
                lessons = (
                    db.query(Lesson).filter(Lesson.unit_id == unit.id).order_by(Lesson.index).all()
                )
                for lesson in lessons:
                    for heading, text in _lesson_pages(book, chapter, unit, lesson):
                        page_number += 1
                        db.add(
                            BookPage(
                                book_id=book.id,
                                chapter_id=chapter.id,
                                unit_id=unit.id,
                                lesson_id=lesson.id,
                                page_number=page_number,
                                heading=heading,
                                text=text,
                                is_demo=True,
                            )
                        )
                        made += 1
        book.page_count = page_number
        db.flush()
    return made


# Fourth vocational (spec §1 / §125): sections, core subjects and one applied
# subject per section. Everything is demo data (is_demo) until the real Iraqi
# vocational curriculum is uploaded from admin.
VOCATIONAL_SECTIONS: list[dict[str, str]] = [
    {"code": "technical", "name_ar": "قسم تقني", "applied_code": "TECH", "applied": "المهارات التقنية"},
    {"code": "health", "name_ar": "قسم صحي", "applied_code": "HLTH", "applied": "المهارات الصحية"},
    {"code": "agri", "name_ar": "قسم زراعي", "applied_code": "AGRI", "applied": "المهارات الزراعية"},
    {"code": "business", "name_ar": "قسم تجاري", "applied_code": "BUSN", "applied": "المهارات التجارية"},
]

VOCATIONAL_CORE: list[tuple[str, str]] = [
    ("VARB", "اللغة العربية"),
    ("VENG", "اللغة الإنجليزية"),
    ("VREL", "التربية الإسلامية"),
]

VOCATIONAL_QUESTIONS: list[tuple[str, list[str], int, str]] = [
    (
        "ما أفضل تجهيز للاختبار القادم؟",
        ["المراجعة المتباعدة على أيام", "الحفظ في الليلة الأخيرة", "عدم المراجعة", "الاعتماد على الحظ"],
        0,
        "المراجعة المتباعدة تثبّت المعلومة أفضل من الحفظ المركّز.",
    ),
    (
        "ماذا تفعل إذا لم تفهم جزءاً في الدرس؟",
        ["أعيد قراءة الشرح وأسأل عند اللزوم", "أتجاوز الموضوع كلياً", "أنتظر الامتحان", "أطلب الإجابة جاهزة"],
        0,
        "السؤال وقتها أفضل من تجاهل الفجوة.",
    ),
    (
        "كيف توزّع جلسات المراجعة؟",
        ["جلسات قصيرة متكررة مع راحة", "جلسة واحدة طويلة", "الدراسة بدون راحة", "أجّل إلى الغد"],
        0,
        "التوزيع يرفع التركيز ويقلل الإرهاق.",
    ),
    (
        "أي عادة تقيس فهمك فعلاً؟",
        ["حل تدريبات وشرح الدرس بكلماتي", "قراءة فقط", "نسخ الملاحظات", "عدم الممارسة"],
        0,
        "التدريب والشرح هما دليل الفهم الحقيقي.",
    ),
]


def seed_vocational(db: Session) -> dict[str, int]:
    """Add the fourth-vocational stage when missing (idempotent add-on)."""
    if db.query(Stage).filter(Stage.code == "grade12voc").count():
        return {"skipped": 1}

    from .services import bank as bank_service

    counts = {"stages": 1, "sections": 0, "subjects": 0, "lessons": 0, "questions": 0}
    stage = Stage(
        code="grade12voc",
        name_ar="الرابع المهني",
        name_en="Fourth Vocational",
        sort_order=4,
        is_demo=True,
    )
    db.add(stage)
    db.flush()

    for order, section in enumerate(VOCATIONAL_SECTIONS):
        branch = Branch(
            stage_id=stage.id,
            code=section["code"],
            name_ar=section["name_ar"],
            name_en="",
            track="vocational",
            sort_order=order,
            is_demo=True,
        )
        db.add(branch)
        db.flush()
        counts["sections"] += 1
        db.add(
            Curriculum(
                stage_id=stage.id,
                branch_id=branch.id,
                title=f'{stage.name_ar} — {branch.name_ar}',
                academic_year="2025-2026",
                is_demo=True,
            )
        )

        subjects_spec = VOCATIONAL_CORE + [(section["applied_code"], section["applied"])]
        for index, (code, name_ar) in enumerate(subjects_spec):
            subject = Subject(
                branch_id=branch.id,
                code=f'{section["code"]}-{code}',
                name_ar=name_ar,
                name_en="",
                color="#2f8ff7",
                icon="📖",
                sort_order=index,
                is_demo=True,
            )
            db.add(subject)
            db.flush()
            counts["subjects"] += 1

            book = Book(
                subject_id=subject.id,
                title=f"كتاب {name_ar} — الرابع المهني (تجريبي)",
                edition="2025",
                is_demo=True,
            )
            db.add(book)
            db.flush()
            chapter = Chapter(
                book_id=book.id,
                index=1,
                title=f"{name_ar} — وحدة تجريبية",
                page_start=1,
                page_end=40,
            )
            db.add(chapter)
            db.flush()
            unit = Unit(chapter_id=chapter.id, index=1, title=f"مقدمة {name_ar}")
            db.add(unit)
            db.flush()

            lesson_rows = [
                (
                    f"مقدمة في {name_ar}",
                    f"مقدمة تجريبية لمادة {name_ar} للرابع المهني؛ يُرفع النص الرسمي من لوحة الإدارة.",
                    ["تعرّف أهداف المادة", "يستعد لبدء التعلم"],
                ),
                (
                    f"تدريبات تطبيقية في {name_ar}",
                    "تدريبات تطبيقية على مهارات المقدمة السابقة.",
                    ["يطبق ما تعلّم", "يقيس فهمه بنفسه"],
                ),
            ]
            for lesson_index, (title, summary, objectives) in enumerate(lesson_rows, start=1):
                db.add(
                    Lesson(
                        unit_id=unit.id,
                        chapter_id=chapter.id,
                        subject_id=subject.id,
                        index=lesson_index,
                        title=title,
                        summary=summary,
                        objectives=objectives,
                        keywords=["تدريب", "مهارات"],
                        difficulty=2,
                        estimated_minutes=40,
                        is_demo=True,
                    )
                )
                db.flush()
                counts["lessons"] += 1

            for prompt, options, answer_index, explanation in VOCATIONAL_QUESTIONS:
                made = bank_service.register_generated(
                    db,
                    {
                        "type": "mcq",
                        "prompt": f"مادة {name_ar} ({branch.name_ar}): {prompt}",
                        "options": options,
                        "answer_index": answer_index,
                        "explanation": explanation,
                        "difficulty": 2,
                        "topic": "مهارات الدراسة",
                        "subject_id": subject.id,
                        "source_kind": "manual",
                    },
                    status="published",
                )
                if made is not None:
                    counts["questions"] += 1
    db.flush()
    return counts


def seed_if_empty() -> dict[str, Any]:
    """Create tables + demo data when the database is still empty."""
    init_db()
    db = SessionLocal()
    try:
        result: dict[str, Any] = {}
        if db.query(User).count() == 0:
            result["curriculum"] = seed_curriculum(db)
            result["achievements"] = seed_achievements(db)
            result["media"] = seed_media(db)
            result["accounts"] = seed_demo_students(db)
            db.commit()
            logger.info("seeded demo data: %s", result)
        elif db.query(Stage).count() == 0:
            result["curriculum"] = seed_curriculum(db)
            result["achievements"] = seed_achievements(db)
            db.commit()
        else:
            result["skipped"] = True

        # the fourth-vocational stage is an idempotent add-on (spec §1/§125)
        vocational = seed_vocational(db)
        if not vocational.get("skipped"):
            result["vocational"] = vocational
            db.commit()
            logger.info("seeded vocational stage: %s", vocational)

        # books may exist while their pages do not (databases created before
        # the reader) — this runs on every boot but is a no-op once populated.
        pages = seed_book_pages(db)
        if pages:
            result["book_pages"] = pages
            db.commit()
            logger.info("seeded %s book pages", pages)
        return result
    finally:
        db.close()


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(seed_if_empty())


if __name__ == "__main__":
    main()
