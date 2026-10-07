"""Browser E2E: boots backend + frontend, drives Chromium through the core flows.

Run with an interpreter that has playwright installed:
    python -m playwright install chromium
    python tools/e2e_browser.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
FE_PORT = int(os.environ.get("FE_PORT", "3112"))
BE_PORT = 8000  # next.config.mjs proxies /api/* to 127.0.0.1:8000 (baked in at build time)
BACKEND_PYTHON = (
    os.environ.get("BACKEND_PYTHON")
    or getattr(sys, "_base_executable", None)
    or sys.executable
)
BASE = f"http://127.0.0.1:{FE_PORT}"
API = f"http://127.0.0.1:{BE_PORT}"

FAILURES: list[str] = []
PASSES = 0
IGNORED_CONSOLE = (
    "favicon",
    "Download the React DevTools",
    "Fast refresh",
    "[DEMO]",
)

# P0 1.2 — engine doubles so the Arabic voice round trip is deterministic:
# one English + one Arabic voice (proving Arabic selection), a spoke() recorder
# (proving Mors' reply is actually spoken), and a recognizer that reports the
# real "permission denied" code (proving STT failures are never swallowed).
VOICE_ROUNDTRIP_JS = """
window.__morsVoices = [
  {name:'Microsoft David Desktop - English (United States)', lang:'en-US', localService:true, default:true, voiceURI:'david'},
  {name:'Microsoft Hoda Desktop - Arabic (Iraq)', lang:'ar-IQ', localService:true, default:false, voiceURI:'hoda'}
];
window.speechSynthesis.getVoices = function () { return window.__morsVoices.slice(); };
Object.defineProperty(window.SpeechSynthesisUtterance.prototype, 'voice', {
  configurable: true,
  get: function () { return this.__morsVoice || null; },
  set: function (v) { this.__morsVoice = v; }
});
window.__spoken = [];
window.speechSynthesis.cancel = function () {};
window.speechSynthesis.speak = function (u) {
  window.__spoken.push({
    text: u.text,
    voice: (u.voice && u.voice.name) || null,
    voiceLang: (u.voice && u.voice.lang) || null
  });
  setTimeout(function () { if (u.onend) u.onend(); }, 5);
};
function FakeRec() {
  this.lang = ''; this.interimResults = false; this.continuous = false;
  this.onresult = null; this.onerror = null; this.onend = null;
}
FakeRec.prototype.start = function () {
  var self = this;
  setTimeout(function () { if (self.onerror) self.onerror({error: 'not-allowed'}); }, 30);
};
FakeRec.prototype.stop = function () {};
window.SpeechRecognition = FakeRec;
window.webkitSpeechRecognition = FakeRec;
"""


def ok(cond: bool, label: str, detail: str = "") -> bool:
    global PASSES
    if cond:
        PASSES += 1
        print(f"[OK ] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label} {detail}")
    return bool(cond)


def wait_http(url: str, timeout: int = 90) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.7)
    return False


def api_json(url: str, payload: dict | None = None, token: str = "", method: str | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method=method or ("POST" if data else "GET"),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def spawn_procs(logdir: Path):
    logdir.mkdir(parents=True, exist_ok=True)
    be = open(logdir / "browser_backend.log", "w", encoding="utf-8")
    fe = open(logdir / "browser_frontend.log", "w", encoding="utf-8")
    env = dict(os.environ)
    env.setdefault("DEMO_DATA", "true")
    env.setdefault("AI_PROVIDER", "mock")
    # a scripted browser session (page loads + polling + AI flows) legitimately
    # exceeds the production allowances; production limits stay in config.
    env.setdefault("RATE_LIMIT_PER_MINUTE", "600")
    env.setdefault("AI_RATE_LIMIT_PER_MINUTE", "180")
    env["PYTHONUTF8"] = "1"
    procs = [
        subprocess.Popen(
            [BACKEND_PYTHON, "-m", "uvicorn", "app.main:app", "--port", str(BE_PORT), "--log-level", "info"],
            cwd=str(BACKEND), env=env, stdout=be, stderr=subprocess.STDOUT),
        subprocess.Popen(
            ["node", str(FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"), "start", "-p", str(FE_PORT)],
            cwd=str(FRONTEND), env=env, stdout=fe, stderr=subprocess.STDOUT),
    ]
    return procs, [be, fe]


def main() -> int:
    from playwright.sync_api import sync_playwright

    procs, logs = spawn_procs(ROOT / "tools" / "logs")
    console_errors: list[str] = []
    try:
        backend_up = wait_http(f"{API}/health")
        ok(backend_up, "backend up")
        if not backend_up:
            try:
                tail = Path(ROOT / "tools" / "logs" / "browser_backend.log").read_text(encoding="utf-8")[-1200:]
            except Exception:
                tail = "(no log)"
            print(tail)
            return 2
        ok(wait_http(f"{BASE}/login"), "frontend up")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(f"pageerror: {err}"))
            page.on("dialog", lambda dialog: dialog.accept())

            # 1. auth gate
            page.goto(BASE + "/", wait_until="networkidle")
            ok(page.url.rstrip("/").endswith("/login"), "root redirects to /login", page.url)

            # 2. login
            inputs = page.locator("input.input")
            inputs.nth(0).fill("demo@mors.ai")
            inputs.nth(1).fill("DemoPass123!")
            page.locator("button.btn.block").click()
            page.wait_for_url(lambda u: "/home" in u or "/onboarding" in u, timeout=20000)
            ok(True, "login redirects into the app", page.url)
            page.wait_for_selector(".topbar h1", timeout=20000)
            token = page.evaluate("() => localStorage.getItem('mors_token') || ''")
            ok(bool(token), "token stored in localStorage")

            # 3. every sidebar destination renders
            for href, label in [("/home", "الرئيسية"), ("/plan", "خطتي"), ("/library", "المكتبة"),
                                ("/notes", "ملاحظاتي"), ("/papers", "أوراق"),
                                ("/chat", "مورس"), ("/progress", "تقدّمي"), ("/videos", "فيديوهات"),
                                ("/inbox", "الإشعارات"), ("/settings", "الإعدادات"),
                                ("/onboarding", "التعارف"), ("/exams", "الامتحانات")]:
                page.goto(BASE + href, wait_until="networkidle")
                try:
                    page.wait_for_selector(".topbar h1", timeout=15000)
                    title = page.locator(".topbar h1").inner_text().strip()
                except Exception:
                    title = ""
                errs = page.locator(".error-box").count()
                ok(bool(title) and errs == 0, f"page {href} renders ({label})", f"title={title!r} errors={errs}")

            # 3b. library -> book reader -> highlight -> ask Mors
            page.goto(BASE + "/library", wait_until="networkidle")
            page.wait_for_selector(".book-card", timeout=20000)
            ok(page.locator(".book-card").count() > 0, "library renders book cards",
               f"count={page.locator('.book-card').count()}")

            # 3b-1. P1 2.1: the shelf itself — labels, unique filters, real search,
            # and an empty state instead of a blank screen
            cards_all = page.locator(".book-card").count()
            first_card = page.locator(".book-card").first.inner_text()
            ok("·" in first_card, "book card is labeled (grade · branch)", first_card.replace("\n", " ")[:90])
            chip_labels = [t.strip() for t in page.locator(".card .chip").all_inner_texts()]
            ok(len(chip_labels) == len(set(chip_labels)), "subject filter chips are unique",
               str(chip_labels))
            ok(len(chip_labels) >= 3, "filter bar lists the shelf's subjects",
               f"n={len(chip_labels)}")
            page.screenshot(path=str(ROOT / "tools" / "logs" / "library_shelf.png"))

            search = page.locator(".card input.input").first
            search.fill("الأحياء")
            page.wait_for_function(
                "(n) => document.querySelectorAll('.book-card').length < n",
                arg=cards_all, timeout=10000,
            )
            narrowed = page.locator(".book-card").count()
            ok(0 < narrowed < cards_all, "typing a subject narrows the shelf",
               f"{cards_all} -> {narrowed}")
            ok("الأحياء" in page.locator(".book-card").first.inner_text(),
               "filtered cards match the query")

            search.fill("zzzz-missing-book")
            page.wait_for_selector(".empty", timeout=10000)
            empty_text = page.locator(".empty").inner_text()
            ok("ما لقينا" in empty_text, "empty search shows a real message, not a blank screen",
               empty_text[:70])
            ok(page.locator(".card .chip").count() == len(chip_labels),
               "the filter bar survives an empty result")
            ok(page.locator(".error-box").count() == 0, "empty search is not an error")
            page.screenshot(path=str(ROOT / "tools" / "logs" / "library_empty.png"))

            search.fill("")
            page.wait_for_function(
                "(n) => document.querySelectorAll('.book-card').length >= n",
                arg=cards_all, timeout=10000,
            )
            chips = page.locator(".card .chip")
            if chips.count() > 1:
                chip_name = chips.nth(1).inner_text().replace("⭐", "").strip()
                chips.nth(1).click()
                page.wait_for_function(
                    """(name) => {
                        const cards = Array.from(document.querySelectorAll('.book-card'));
                        return cards.length > 0 && cards.every(c => c.innerText.includes(name));
                    }""",
                    arg=chip_name, timeout=10000,
                )
                ok(True, "subject chip filters the shelf", chip_name)
                chips.nth(0).click()
                page.wait_for_function(
                    "(n) => document.querySelectorAll('.book-card').length >= n",
                    arg=cards_all, timeout=10000,
                )
            else:
                ok(False, "subject chip filters the shelf", "only the الكل chip was found")

            page.locator(".book-card").first.click()
            page.wait_for_url(lambda u: "/books/" in u, timeout=20000)
            page.wait_for_selector(".reader-heading", timeout=20000)
            heading = page.locator(".reader-heading").inner_text().strip()
            ok(bool(heading), "reader shows a page heading", heading[:70])

            place = page.locator(".reader-place").inner_text().strip()
            page.locator(".reader-nav > button.btn").last.click()
            page.wait_for_function(
                "(prev) => (document.querySelector('.reader-place') || {}).innerText !== prev",
                arg=place, timeout=15000,
            )
            ok(True, "reader advances to the next page", place[:40])

            # scan-only books (no lesson index) are readable but have an empty
            # ToC by design — find a book that actually has lessons for this check
            indexed_id = page.evaluate(
                """async () => {
                  const h = {Authorization: 'Bearer ' + localStorage.getItem('mors_token')};
                  const list = await (await fetch('/api/books', {headers: h})).json();
                  for (const b of (list.books || []).slice(0, 12)) {
                    const d = await (await fetch('/api/books/' + b.id, {headers: h})).json();
                    const book = d.book || d;
                    const lessons = (book.toc || []).reduce(
                      (n, c) => n + (c.units || []).reduce((m, u) => m + (u.lessons || []).length, 0), 0);
                    if (lessons > 0) return b.id;
                  }
                  return null;
                }"""
            )
            ok(bool(indexed_id), "a book with a lesson index exists", str(indexed_id))
            if indexed_id:
                page.goto(BASE + "/books/" + indexed_id, wait_until="networkidle")
                page.wait_for_selector(".reader-heading", timeout=20000)

            page.locator('button[title="جدول المحتويات"]').click()
            page.wait_for_selector(".reader-toc", timeout=8000)
            toc_rows = page.locator(".reader-toc-lesson").count()
            ok(toc_rows > 0, "table of contents lists lessons", f"lessons={toc_rows}")
            if toc_rows:
                page.locator(".reader-toc-lesson").first.click()
                page.wait_for_selector(".reader-toc", state="detached", timeout=8000)

            page.locator('button[title="الوضع الليلي"]').click()
            ok(page.locator(".reader.night").count() == 1, "night mode toggles on")
            page.locator('button[title="الوضع الليلي"]').click()

            bookmark_btn = page.locator('button[title="علامة"]')
            bookmark_btn.wait_for(state="visible", timeout=8000)
            before_bookmark = bookmark_btn.inner_text()
            bookmark_btn.click()
            page.wait_for_function(
                "(prev) => { const b = document.querySelector('button[title=\"علامة\"]');"
                " return !!b && b.innerText !== prev; }",
                arg=before_bookmark,
                timeout=8000,
            )
            ok(True, "bookmark toggles on the page", f"{before_bookmark!r} -> changed")

            selected = page.evaluate(
                """() => {
                    const p = document.querySelector('.reader-p');
                    if (!p) return false;
                    const range = document.createRange();
                    range.selectNodeContents(p);
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    return true;
                }"""
            )
            page.wait_for_selector(".reader-selection", timeout=8000)
            ok(selected, "text selection is captured for Ask Mors")

            page.locator(".reader-selection button", has_text="ظلّل").click()
            page.wait_for_selector("text=حُفظ التظليل", timeout=8000)
            page.wait_for_selector("text=تظليلات الصفحة", timeout=8000)
            ok(True, "highlight saved and listed")

            page.locator(".card", has_text="اسأل مورس").locator("button.chip").first.click()
            page.wait_for_selector(".reader-answer", timeout=45000)
            answer = page.locator(".reader-answer").inner_text().strip()
            ok(len(answer) > 40, "Ask Mors answers inside the book", answer[:70])
            ok(page.locator(".reader-answer .tag").count() > 0, "answer carries a page citation")

            # 4. chat round-trip
            page.goto(BASE + "/chat", wait_until="networkidle")
            page.locator(".chat-input input").fill("من انت؟")
            page.locator(".chat-input button[aria-label='إرسال']").click()
            try:
                page.wait_for_selector(".bubble.mors", timeout=40000)
                reply = page.locator(".bubble.mors").first.inner_text().strip()
            except Exception:
                reply = ""
            ok(bool(reply), "chat reply rendered", reply[:80])

            # 5. lesson page
            subjects = api_json(f"{API}/api/curriculum/subjects", token=token)["subjects"]
            tree = api_json(f"{API}/api/curriculum/subjects/{subjects[0]['id']}/tree", token=token)
            lessons = [l for c in tree["chapters"] for u in c["units"] for l in u["lessons"]]
            lesson_id = lessons[0]["id"]
            page.goto(BASE + f"/lessons/{lesson_id}", wait_until="networkidle")
            try:
                page.wait_for_selector(".card", timeout=15000)
                body = page.locator("main .main, main").first.inner_text()
            except Exception:
                body = ""
            ok(len(body) > 80 and page.locator(".error-box").count() == 0, "lesson page content",
               f"len={len(body)}")

            # 6. quiz flow: answer every question until the report appears
            quiz = api_json(f"{API}/api/quiz/generate",
                            {"lesson_id": lesson_id, "kind": "practice", "count": 4}, token=token)
            page.goto(BASE + f"/quiz/{quiz['id']}", wait_until="networkidle")
            answered = 0
            for _ in range(12):
                if page.locator(".stat").count():
                    break
                try:
                    page.locator(".option").first.click(timeout=5000)
                    answered += 1
                except Exception:
                    break
                page.wait_for_timeout(700)
            ok(page.locator(".stat").count() >= 3, "quiz report rendered", f"answered={answered}")
            stats = page.locator(".stat .label").all_inner_texts()
            ok(any("صحيحة" in s for s in stats), "report shows correct count", str(stats))

            # 6b. exam simulation: readiness → build → timer → answer → analysis
            page.goto(BASE + "/exams", wait_until="networkidle")
            page.wait_for_selector(".tabs", timeout=20000)
            ok(page.locator(".readiness-ring").count() >= 1, "exams page shows the readiness ring")
            ok(page.locator(".error-box").count() == 0, "exams page loads clean")

            page.get_by_role("button", name="امتحان جديد").click()
            page.wait_for_selector("text=محاكاة امتحان جديد", timeout=10000)
            page.get_by_role("button", name="ابدأ المحاكاة").click()
            page.wait_for_url(lambda u: "/exam/" in u, timeout=90000)
            page.wait_for_selector(".exam-grid", timeout=30000)
            ok(page.locator(".exam-nav-btn").count() > 0, "exam navigator lists every question",
               f"cells={page.locator('.exam-nav-btn').count()}")

            timer_text = page.locator(".exam-timer").inner_text().strip()
            ok(":" in timer_text, "server-side timer renders mm:ss", timer_text)
            page.screenshot(path=str(ROOT / "tools" / "logs" / "exam_timer.png"))

            page.locator(".option").first.click()
            page.wait_for_selector("text=تم حفظ إجابتك", timeout=20000)
            main_text = page.locator("main").inner_text()
            ok("ليست الصحيحة" not in main_text and "إجابة صحيحة" not in main_text,
               "exam hides grading until submission")

            page.locator(".card-title button.chip", has_text="للمراجعة").click()
            page.wait_for_selector(".exam-nav-btn.marked", timeout=10000)
            ok(True, "mark-for-review highlights the navigator cell")

            answered_cells = page.locator(".exam-nav-btn.done").count()
            ok(answered_cells >= 1, "navigator marks answered questions", f"done={answered_cells}")

            page.get_by_role("button", name="إنهاء وإرسال الامتحان").click()
            page.wait_for_selector(".stat", timeout=45000)
            ok(page.locator(".stat").count() >= 3, "exam analysis renders the score panel")
            ok(page.locator(".error-box").count() == 0, "exam analysis has no errors")
            analysis_text = page.locator("main").inner_text()
            ok("حسب مستوى الصعوبة" in analysis_text, "analysis breaks results down by difficulty")
            ok("استعدادك" in analysis_text, "analysis carries the readiness verdict")

            # 6c. advisor: problems → solutions → apply an action → bottom nav
            page.goto(BASE + "/advisor", wait_until="networkidle")
            page.wait_for_selector(".tabs", timeout=20000)
            ok(page.locator(".error-box").count() == 0, "advisor page loads clean")
            headline = page.locator(".advisor-headline").inner_text().strip()
            ok(len(headline) > 12, "advisor headline renders", headline[:70])

            page.get_by_role("button", name="ما مشكلتي؟").click()
            page.wait_for_timeout(600)
            problem_count = page.locator(".problem").count()
            if problem_count:
                ok(
                    page.locator(".problem .solution").count() == problem_count,
                    "every problem carries a solution",
                    f"n={problem_count}",
                )
            else:
                ok(True, "no problems reported for this student", "empty is valid")

            page.get_by_role("button", name="خطة الأسبوع").click()
            page.wait_for_selector(".kpis", timeout=10000)
            ok(page.locator(".kpi").count() >= 5, "weekly KPIs render", f"kpis={page.locator('.kpi').count()}")

            page.get_by_role("button", name="شنو لازم أسوي؟").click()
            page.wait_for_selector(".step", timeout=10000)
            step_count = page.locator(".step").count()
            ok(step_count >= 5, "advisor lists concrete steps", f"steps={step_count}")
            session_step = page.locator(".step", has_text="جلسة دراسة").first
            session_step.locator("button", has_text="طبّق").click()
            page.wait_for_selector(".success-box", timeout=25000)
            applied_text = page.locator(".success-box").inner_text()
            ok("حجزنا" in applied_text, "advisor books a study session", applied_text[:80])
            ok(page.locator(".error-box").count() == 0, "no error after applying a step")

            # bottom navigation "المزيد" sheet (§100) — mobile viewport
            mobile_ctx = browser.new_context(viewport={"width": 390, "height": 844})
            mobile = mobile_ctx.new_page()
            mobile.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            mobile.add_init_script(f"localStorage.setItem('mors_token', {json.dumps(token)});")
            mobile.goto(BASE + "/advisor", wait_until="networkidle")
            mobile.wait_for_selector(".bottomnav", timeout=20000)
            more_btn = mobile.locator(".bottomnav button", has_text="المزيد")
            ok(more_btn.count() == 1, "bottom bar keeps a مزيد entry")
            more_btn.click()
            mobile.wait_for_selector(".more-grid", timeout=8000)
            more_links = mobile.locator(".more-grid a").count()
            ok(more_links >= 6, "more sheet lists the rest of the navigation", f"n={more_links}")
            ok(
                mobile.locator(".more-grid a", has_text="مرشدي").count() == 1,
                "more sheet includes مرشدي",
            )
            mobile.locator(".more-grid a", has_text="تقدّمي").first.click()
            mobile.wait_for_url(lambda u: "/progress" in u, timeout=20000)
            ok(True, "more sheet navigates to a page")
            mobile_ctx.close()

            # 6d. videos & courses (P4): list → player → progress → gate → report
            page.goto(BASE + "/videos", wait_until="networkidle")
            page.wait_for_selector(".list-item", timeout=20000)
            ok(page.locator(".error-box").count() == 0, "videos page loads clean")
            video_links = page.locator("a[href^='/videos/']")
            ok(video_links.count() >= 1, "videos list links to players", f"n={video_links.count()}")
            course_links = page.locator("a[href^='/courses/']")
            ok(course_links.count() >= 1, "videos page links to courses", f"n={course_links.count()}")
            course_href = course_links.first.get_attribute("href") if course_links.count() else ""
            video_href = video_links.first.get_attribute("href") if video_links.count() else ""

            if video_href:
                page.goto(BASE + video_href, wait_until="networkidle")
                page.wait_for_selector(".video-frame", timeout=20000)
                ok(page.locator(".error-box").count() == 0, "video player page loads clean")

                # §36: no simulated player may stand in for a real lesson video
                ok(page.locator(".demo-player").count() == 0, "fake demo player is gone")

                # the real proof: the official YouTube embed actually mounts
                try:
                    page.wait_for_selector(
                        ".video-frame iframe[src*='youtube.com/embed/']", timeout=25000
                    )
                    embed_src = page.locator(
                        ".video-frame iframe[src*='youtube.com/embed/']"
                    ).first.get_attribute("src")
                    ok(True, "official YouTube embed renders", embed_src or "")
                    ok("/embed/" in (embed_src or ""), "embed src is a youtube video id", embed_src or "")
                except Exception:
                    ok(False, "official YouTube embed renders",
                       page.locator(".video-frame").inner_html()[:300])
                    embed_src = ""
                shot = ROOT / "tools" / "logs" / "video_player.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot), full_page=False)
                # provenance must name the real channel, not a demo teacher
                main_text = page.locator("main").inner_text()
                ok("المصدر: قناة يوتيوب" in main_text, "real channel provenance shown")

                # §38: watched time — driven here through the same API the
                # player calls, since only a real player owns the transport.
                vid_id = video_href.rstrip("/").rsplit("/", 1)[-1]
                detail = api_json(f"{API}/api/media/videos/{vid_id}", token=token)
                dur = detail.get("duration_seconds") or 720
                api_json(
                    f"{API}/api/media/videos/{vid_id}/progress",
                    {"position": dur, "watched_seconds": dur, "key_idea": "فرق ثابت"},
                    token=token,
                )
                page.reload(wait_until="networkidle")
                try:
                    page.wait_for_selector(
                        ".card .tag:has-text('شاهدته'), .card .tag:has-text('مكتمل')",
                        timeout=25000,
                    )
                    ok(True, "watch state tag renders")
                except Exception:
                    tag_text = page.locator(".card .tag").first.inner_text()
                    ok(False, "watch state tag renders", tag_text)
                page.wait_for_selector("text=قبل ما ننتقل", timeout=15000)
                ok(True, "Mors opens the video quiz gate")
                main_text = page.locator("main").inner_text()
                ok("اختبر فهمي" in main_text, "gate offers the short quiz")

                # §84 report flow → success box
                page.locator(".card button", has_text="بلاغ عن الفيديو").click()
                page.wait_for_selector("select.input", timeout=8000)
                page.locator("button", has_text="أرسل البلاغ").click()
                page.wait_for_selector(".success-box", timeout=15000)
                ok(
                    "وصلنا البلاغ" in page.locator(".success-box").inner_text(),
                    "content report acknowledged",
                )
                ok(page.locator(".error-box").count() == 0, "player flow has no error box")

            # §39 continue watching card after the saved progress
            page.goto(BASE + "/videos", wait_until="networkidle")
            page.wait_for_selector(".continue-card", timeout=20000)
            ok(
                "متابعة المشاهدة" in page.locator(".continue-card").inner_text(),
                "continue watching card renders",
            )

            if course_href:
                page.goto(BASE + course_href, wait_until="networkidle")
                page.wait_for_selector(".video-row", timeout=20000)
                ok(page.locator(".error-box").count() == 0, "course page loads clean")
                modules = page.locator(".module-block").count()
                ok(modules >= 1, "course lists modules", f"n={modules}")
                ok(page.locator(".bar").count() >= 1, "course shows progress bars")
                course_text = page.locator("main").inner_text()
                ok("%" in course_text, "course shows a percentage")

            # 6e. voice input/output controls (§15/§70) on the chat page
            page.goto(BASE + "/chat", wait_until="networkidle")
            page.wait_for_selector(".chat-input", timeout=20000)
            ok(page.locator(".error-box").count() == 0, "chat page loads clean for voice")
            voice_chip = page.locator(".chip", has_text="صوت")
            ok(voice_chip.count() >= 1, "chat exposes the auto-voice toggle", f"n={voice_chip.count()}")
            mic = page.locator(".chat-input .mic")
            if mic.count():
                mic.click()
                page.wait_for_timeout(2500)
                ok(page.locator(".error-box").count() == 0, "voice input start has no error box")
                if page.locator(".chat-input .mic.on").count():
                    # the listening mic pulses (CSS animation) — force the toggle off
                    page.locator(".chat-input .mic.on").click(force=True)
                    page.wait_for_timeout(400)
            else:
                ok(True, "voice input hidden when unsupported", "no SpeechRecognition here")

            # 6f. the Arabic voice round trip itself (P0 1.2): Mors' reply is
            # spoken with an ARABIC voice, and a dead microphone is explained
            # instead of hanging silently. Runs in its own context because it
            # injects engine doubles that must not leak into other checks.
            api_json(
                f"{API}/api/auth/settings",
                {"voice_enabled": True, "tts_voice": "system"},
                token=token,
                method="PATCH",
            )
            vctx = browser.new_context(viewport={"width": 1100, "height": 850})
            vctx.add_init_script(VOICE_ROUNDTRIP_JS)
            vpage = vctx.new_page()
            vpage.on(
                "console",
                lambda m: console_errors.append(m.text) if m.type == "error" else None,
            )
            vpage.on("pageerror", lambda err: console_errors.append(f"pageerror: {err}"))
            vpage.goto(BASE + "/login", wait_until="networkidle")
            vpage.locator("input.input").nth(0).fill("demo@mors.ai")
            vpage.locator("input.input").nth(1).fill("DemoPass123!")
            vpage.locator("button.btn").first.click()
            vpage.wait_for_timeout(2500)
            vpage.goto(BASE + "/chat", wait_until="networkidle")
            vpage.wait_for_selector(".chat-input", timeout=20000)

            vchip = vpage.locator(".chip", has_text="صوت")
            if vchip.count():
                vchip.first.click()
                vpage.wait_for_timeout(500)
            vpage.locator(".chat-input input").fill("اشرحلي المتتالية الحسابية بسطرين")
            vpage.locator('.chat-input button[aria-label="إرسال"]').click()
            try:
                vpage.wait_for_selector(".bubble.mors", timeout=60000)
                ok(True, "voice round trip: Mors replied")
            except Exception:
                ok(False, "voice round trip: Mors replied", vpage.locator(".chat-input").count())
            spoken = []
            for _ in range(50):
                spoken = vpage.evaluate("() => window.__spoken.slice()")
                if spoken:
                    break
                vpage.wait_for_timeout(300)
            ok(len(spoken) >= 1, "voice round trip: reply is spoken", len(spoken))
            if spoken:
                last = spoken[-1]
                ok(
                    str(last.get("voiceLang") or "").lower().startswith("ar"),
                    "voice round trip: an ARABIC voice is used",
                    f"{last.get('voice')} ({last.get('voiceLang')})",
                )
                ok(len(str(last.get("text") or "")) > 10, "voice round trip: it speaks the reply",
                   str(last.get("text"))[:40])

            # STT failure path: permission denied must surface in Arabic
            vchip2 = vpage.locator(".chat-input .mic")
            if vchip2.count():
                vchip2.click()
                try:
                    vpage.wait_for_selector(".notice-box", timeout=15000)
                    notice = vpage.locator(".notice-box").inner_text()
                    ok("المايك مرفوض" in notice, "voice round trip: STT failure explained",
                       notice[:80])
                except Exception:
                    ok(False, "voice round trip: STT failure explained",
                       vpage.locator("main").inner_text()[:200])
                ok(vpage.locator(".error-box").count() == 0,
                   "voice round trip: STT failure is not an error box")
            vpage.screenshot(path=str(ROOT / "tools" / "logs" / "voice_roundtrip.png"))
            vctx.close()

            # 6g. the same two P0 proofs at phone size, with a real phone UA —
            # P0 1.1 and 1.2 are only "done" when they hold on mobile too.
            # The floating Mors widget used to land on the composer and make
            # the send button unclickable on a phone.
            MOBILE_AGENTS = {
                "android": (
                    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
                ),
                "ios": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
                    "Mobile/15E148 Safari/604.1"
                ),
            }
            for platform, agent in MOBILE_AGENTS.items():
                mctx = browser.new_context(
                    viewport={"width": 412 if platform == "android" else 390, "height": 900},
                    device_scale_factor=2,
                    is_mobile=True,
                    has_touch=True,
                    user_agent=agent,
                )
                mctx.add_init_script(VOICE_ROUNDTRIP_JS)
                m = mctx.new_page()
                m.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )
                m.on("pageerror", lambda err: console_errors.append(f"pageerror: {err}"))
                m.goto(f"{BASE}/login", wait_until="networkidle")
                m.locator("input.input").nth(0).fill("demo@mors.ai")
                m.locator("input.input").nth(1).fill("DemoPass123!")
                m.locator("button.btn").first.click()
                m.wait_for_timeout(2500)

                # --- P0 1.1: a real lesson video inside the mobile webview
                if video_href:
                    m.goto(BASE + video_href, wait_until="networkidle")
                    m.wait_for_selector(".video-frame", timeout=25000)
                    ok(m.locator(".demo-player").count() == 0,
                       f"mobile[{platform}] fake demo player is gone")
                    try:
                        m.wait_for_selector(
                            ".video-frame iframe[src*='youtube.com/embed/']", timeout=25000
                        )
                        ok(True, f"mobile[{platform}] official YouTube embed renders")
                    except Exception:
                        ok(False, f"mobile[{platform}] official YouTube embed renders",
                           m.locator(".video-frame").inner_html()[:200])
                    m.screenshot(path=str(ROOT / "tools" / "logs" / f"mobile_video_{platform}.png"))

                # --- P0 1.2: the Arabic voice round trip on a phone
                m.goto(BASE + "/chat", wait_until="networkidle")
                m.wait_for_selector(".chat-input", timeout=20000)
                mchip = m.locator("button.chip", has_text="صوت")
                if mchip.count():
                    mchip.first.click()
                    m.wait_for_timeout(400)
                m.locator(".chat-input input").fill("اشرحلي المتتالية الحسابية بسطرين")
                msend = m.locator('.chat-input button[aria-label="إرسال"]')
                covered = False
                try:
                    msend.click(timeout=6000)
                except Exception:
                    covered = True
                    m.screenshot(
                        path=str(ROOT / "tools" / "logs" / f"mobile_chat_blocked_{platform}.png")
                    )
                    msend.click(force=True)
                ok(not covered,
                   f"mobile[{platform}] composer send button is not covered by the floating Mors",
                   "intercepted" if covered else "clean")
                # the "يفكّر…" spinner shares .bubble.mors — wait for a real reply
                try:
                    m.wait_for_selector(".bubble.mors:not(.muted)", timeout=60000)
                    ok(True, f"mobile[{platform}] Mors replied")
                except Exception:
                    ok(False, f"mobile[{platform}] Mors replied", "no reply within 60s")
                mspoken = []
                for _ in range(60):
                    mspoken = m.evaluate("() => (window.__spoken || []).slice()")
                    if mspoken:
                        break
                    m.wait_for_timeout(500)
                ok(len(mspoken) >= 1, f"mobile[{platform}] reply spoken", f"n={len(mspoken)}")
                if mspoken:
                    ok(str(mspoken[-1].get("voiceLang") or "").lower().startswith("ar"),
                       f"mobile[{platform}] ARABIC voice", str(mspoken[-1].get("voice")))
                ok(m.locator(".error-box").count() == 0,
                   f"mobile[{platform}] no error box in the chat flow")
                m.screenshot(path=str(ROOT / "tools" / "logs" / f"mobile_voice_{platform}.png"))
                mctx.close()

            # 7. settings round-trip
            page.goto(BASE + "/settings", wait_until="networkidle")
            page.wait_for_selector(".topbar h1", timeout=15000)
            ok(page.locator(".error-box").count() == 0, "settings page loads clean")

            # voice section (§70): providers + prefs + test button
            page.wait_for_selector("text=الصوت", timeout=15000)
            ok(page.locator("text=TTS:").count() >= 1, "voice providers shown")
            ok(page.locator("text=التعرّف على الكلام").count() >= 1, "stt pref shown")
            test_btn = page.locator("button", has_text="جرّب صوت مورس")
            ok(test_btn.count() == 1, "voice test button exists", f"n={test_btn.count()}")
            if test_btn.count():
                test_btn.click()
                page.wait_for_selector(".card .success-box", timeout=30000)
                voice_msg = page.locator(".card .success-box").first.inner_text()
                ok(
                    "نطقت" in voice_msg or "ما يدعم" in voice_msg,
                    "voice test answers",
                    voice_msg[:70],
                )
                ok(page.locator(".error-box").count() == 0, "voice test has no error box")

            # 8. plan generation
            page.goto(BASE + "/plan", wait_until="networkidle")
            page.wait_for_selector(".topbar h1", timeout=15000)
            ok(page.locator(".error-box").count() == 0, "plan page loads clean")

            # 9. study session lifecycle: start -> timer UI -> finish -> mors reaction
            api_json(f"{API}/api/study/start",
                     {"title": "جلسة اختبار", "lesson_id": lesson_id, "goal": "مراجعة سريعة"},
                     token=token)
            page.goto(BASE + "/study", wait_until="networkidle")
            page.get_by_role("button", name="أنهي الجلسة").wait_for(timeout=15000)
            ok(True, "study timer UI renders for an active session")
            page.screenshot(path=str(ROOT / "tools" / "logs" / "study_timer.png"))
            page.get_by_role("button", name="أنهي الجلسة").click()
            try:
                page.wait_for_selector("text=أحسنت", timeout=25000)
            except Exception:
                print("[DBG] error-box:", page.locator(".error-box").all_inner_texts())
                print("[DBG] main text:", page.locator("main").inner_text()[:800])
                raise
            ok(page.locator(".stat").count() >= 3, "session finish panel renders")
            ok(page.locator(".error-box").count() == 0, "no error box after finishing a session")

            # 10. admin publishing pipeline + scheduler (P6 / §83 + §126)
            admin_ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            apage = admin_ctx.new_page()
            apage.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            apage.on("pageerror", lambda err: console_errors.append(f"pageerror: {err}"))
            apage.on("dialog", lambda dialog: dialog.accept())
            apage.goto(BASE + "/login", wait_until="networkidle")
            ain = apage.locator("input.input")
            ain.nth(0).fill("admin@mors.ai")
            ain.nth(1).fill("DemoPass123!")
            apage.locator("button.btn.block").click()
            apage.wait_for_url(
                lambda u: "/home" in u or "/onboarding" in u or "/admin" in u, timeout=20000
            )
            ok(True, "admin login", apage.url)

            apage.goto(BASE + "/admin", wait_until="networkidle")
            apage.wait_for_selector(".tabs", timeout=20000)
            ok(apage.locator(".error-box").count() == 0, "admin page loads clean")

            apage.locator(".tabs button", has_text="نشر المحتوى").click()
            apage.wait_for_selector("text=طابور النشر", timeout=15000)
            ok(True, "publish tab renders")

            atoken = apage.evaluate("() => localStorage.getItem('mors_token') || ''")
            asubs = (api_json(f"{API}/api/curriculum/subjects", token=atoken).get("subjects") or [])
            ok(bool(asubs), "admin can list subjects", f"n={len(asubs)}")
            if asubs:
                apage.locator("input.input[placeholder='عنوان المحتوى']").fill(
                    "درس من المتصفح P6"
                )
                apage.locator(".card").first.locator("input[dir='ltr']").first.fill(asubs[0]["id"])
                apage.locator("button.btn", has_text="إنشاء مسودة").click()
                apage.wait_for_selector(".success-box", timeout=15000)
                ok(
                    "أُنشئت المسودة" in apage.locator(".success-box").first.inner_text(),
                    "draft created from the UI",
                )

                row = apage.locator("tbody tr", has_text="درس من المتصفح P6").first
                row.wait_for(timeout=15000)
                row.locator("button", has_text="معالجة").click()
                apage.wait_for_selector(".success-box:has-text('نُفّذت المعالجة')", timeout=30000)
                row = apage.locator("tbody tr", has_text="درس من المتصفح P6").first
                row.locator("button", has_text="نشر الآن").click()
                apage.wait_for_selector(".success-box:has-text('نُشر المحتوى')", timeout=20000)
                row = apage.locator("tbody tr", has_text="درس من المتصفح P6").first
                ok(
                    row.locator(".tag", has_text="منشور").count() == 1,
                    "draft shows published in the queue",
                )
                ok(apage.locator(".error-box").count() == 0, "publish flow has no error box")

            apage.locator(".tabs button", has_text="المجدول").click()
            apage.wait_for_selector("text=المهام الخلفية", timeout=15000)
            job_rows = apage.locator("tbody tr")
            ok(job_rows.count() == 3, "scheduler lists 3 jobs", f"n={job_rows.count()}")
            apage.locator("button", has_text="شغّل الآن").first.click()
            apage.wait_for_selector(".success-box:has-text('نجحت المهمة')", timeout=30000)
            ok(True, "job runs from the UI")
            ok(apage.locator(".error-box").count() == 0, "scheduler flow has no error box")
            # 11. §3 inspiration: the three shipped ideas — a one-question check
            # at the end of a lesson (Abwaab), a daily quick quiz on /home, and
            # a student flag that lands in the admin inbox (مرماز-style).
            # 11a. the quick check: one question, instant feedback, the right option
            page.goto(BASE + f"/lessons/{lesson_id}", wait_until="networkidle")
            try:
                page.wait_for_selector("[data-quick-check='1']", timeout=30000)
                qc = page.locator("[data-quick-check='1']")
                qc.locator(".option").first.wait_for(timeout=20000)
                ok(qc.locator(".option").count() >= 2, "quick check renders one question",
                   f"options={qc.locator('.option').count()}")
                ok("سؤال سريع لفهم" in qc.inner_text() or "سؤال سريع" in qc.inner_text(),
                   "quick check is labelled for the lesson")
                qc.locator(".option").first.click()
                page.wait_for_selector("[data-quick-check='1'] .notice-box", timeout=25000)
                qc_feedback = qc.locator(".notice-box").first.inner_text()
                ok(
                    "الصحيح:" in qc_feedback or "إجابة صحيحة" in qc_feedback,
                    "quick check answers back with the correct option",
                    qc_feedback.replace("\n", " ")[:90],
                )
                ok(qc.locator(".option.correct").count() == 1,
                   "quick check marks the right option")
                ok(page.locator(".error-box").count() == 0,
                   "quick check has no error box")
                page.screenshot(path=str(ROOT / "tools" / "logs" / "quick_check.png"))
            except Exception as exc:
                ok(False, "quick check renders and answers", str(exc)[:160])

            # 11b. the daily quick quiz card on /home
            page.goto(BASE + "/home", wait_until="networkidle")
            try:
                page.wait_for_selector("[data-daily-quiz='1']", timeout=30000)
                daily_card = page.locator("[data-daily-quiz='1']")
                ok("اختبار اليوم" in daily_card.inner_text(), "home shows the daily quiz card")
                start_btn = daily_card.locator("button", has_text="ابدأ اختبار اليوم")
                if start_btn.count():
                    start_btn.first.click()
                    page.wait_for_url(lambda u: "/quiz/" in u, timeout=30000)
                    ok(True, "daily quiz opens from the home card", page.url)
                    page.wait_for_selector(".option", timeout=20000)
                    ok(page.locator(".option").count() >= 2, "daily quiz renders its questions")
                else:
                    ok("أنجزت اختبار اليوم" in daily_card.inner_text(),
                       "daily quiz card reports the finished result",
                       daily_card.inner_text().replace("\n", " ")[:90])
                ok(page.locator(".error-box").count() == 0, "daily quiz flow has no error box")
                page.screenshot(path=str(ROOT / "tools" / "logs" / "daily_quiz.png"))
            except Exception as exc:
                ok(False, "daily quiz card on /home", str(exc)[:160])

            # 11c. a wrong answer in a report can be reported, and the admin sees it
            marker = f"صياغة غامضة {int(time.time())}"
            try:
                flag_quiz = api_json(
                    f"{API}/api/quiz/generate",
                    {"lesson_id": lesson_id, "kind": "practice", "count": 1, "types": ["mcq"]},
                    token=token,
                )
                flag_question = flag_quiz["questions"][0]
                started = api_json(
                    f"{API}/api/quiz/{flag_quiz['id']}/start", token=token, method="POST"
                )
                wrong_option = None
                for option in flag_question["options"]:
                    graded = api_json(
                        f"{API}/api/quiz/attempts/{started['attempt_id']}/answer",
                        {"question_id": flag_question["id"], "answer": option["id"]},
                        token=token,
                        method="POST",
                    )
                    if not graded.get("correct"):
                        wrong_option = option
                        break
                ok(wrong_option is not None, "a wrong option exists to report")

                # the page reuses the in-progress attempt, so it can pick that option
                page.goto(BASE + f"/quiz/{flag_quiz['id']}", wait_until="networkidle")
                page.wait_for_selector(".option", timeout=20000)
                page.locator(".option", has_text=wrong_option["text"]).first.click()
                page.wait_for_selector(".stat", timeout=30000)
                mistakes = page.locator(".list-item", has_text="إجابتك")
                ok(mistakes.count() >= 1, "report lists the mistake")
                shown = mistakes.first.inner_text()
                ok(wrong_option["text"] in shown, "report shows the answer in words",
                   shown.replace("\n", " ")[:90])
                page.locator("button", has_text="إبلاغ عن السؤال").first.click()
                page.wait_for_selector("select[aria-label='سبب البلاغ']", timeout=10000)
                page.locator("textarea[placeholder='شرح مختصر (اختياري)']").fill(marker)
                page.locator("button", has_text="أرسل البلاغ").first.click()
                page.wait_for_selector("text=وصل البلاغ", timeout=15000)
                ok(True, "student flag sent from the report")
                ok(page.locator(".error-box").count() == 0, "flagging has no error box")

                # the same flag in the admin inbox: listed, then closed
                apage.goto(BASE + "/admin", wait_until="networkidle")
                apage.wait_for_selector(".tabs", timeout=20000)
                apage.locator(".tabs button", has_text="بلاغات الأسئلة").click()
                apage.wait_for_selector("table.table tbody tr", timeout=15000)
                flag_row = apage.locator("tbody tr", has_text=marker)
                ok(flag_row.count() >= 1, "flag reaches the admin inbox",
                   f"rows={flag_row.count()}")
                ok(flag_row.first.inner_text().count("الإجابة المعتمَدة غير صحيحة") >= 1,
                   "admin inbox labels the flag kind",
                   flag_row.first.inner_text().replace("\n", " ")[:90])
                apage.screenshot(path=str(ROOT / "tools" / "logs" / "question_flag.png"))
                flag_row.first.locator("button", has_text="إغلاق").click()
                apage.wait_for_selector(".success-box:has-text('أُغلق البلاغ')", timeout=15000)
                gone = False
                for _ in range(20):
                    if apage.locator("tbody tr", has_text=marker).count() == 0:
                        gone = True
                        break
                    apage.wait_for_timeout(400)
                ok(gone, "closed flag leaves the open inbox")
                ok(apage.locator(".error-box").count() == 0, "admin inbox has no error box")
            except Exception as exc:
                ok(False, "question flag -> admin inbox", str(exc)[:200])

            # 12. §2.4 reminders are fully CRUD from the inbox: add, snooze, delete
            try:
                page.goto(BASE + "/inbox", wait_until="networkidle")
                page.wait_for_selector("[data-reminders='1']", timeout=20000)
                ok(True, "inbox shows the reminders card")
                stamp = f"تذكير المتصفح {int(time.time())}"
                page.locator("[data-reminder-title]").fill(stamp)
                page.locator("[data-reminder-note]").fill("من أداة المتصفح")
                page.locator("[data-reminder-add]").click()
                mine = page.locator("[data-reminder-item]", has_text=stamp)
                mine.first.wait_for(timeout=20000)
                ok(mine.count() >= 1, "reminder created from the UI", stamp)
                ok(mine.first.get_attribute("data-reminder-status") in ("pending", "due"),
                   "new reminder starts pending",
                   str(mine.first.get_attribute("data-reminder-status")))
                row_text = mine.first.inner_text()
                ok(any(c.isdigit() for c in row_text),
                   "reminder row shows a readable time",
                   row_text.replace("\n", " ")[:80])

                mine.first.locator("[data-reminder-snooze]").click()
                snoozed = page.locator(
                    "[data-reminder-item][data-reminder-status='snoozed']", has_text=stamp
                )
                snoozed.first.wait_for(timeout=20000)
                ok(True, "reminder snoozes forward from the UI")

                # editing it keeps the same row
                page.locator("[data-reminder-item]", has_text=stamp).first.locator(
                    "button", has_text="تعديل"
                ).click()
                page.locator("[aria-label='عنوان التذكير']").fill(f"{stamp} — عُدّل")
                page.locator("button", has_text="حفظ").first.click()
                edited = page.locator("[data-reminder-item]", has_text=f"{stamp} — عُدّل")
                edited.first.wait_for(timeout=20000)
                ok(True, "reminder edited from the UI")

                edited.first.locator("[data-reminder-delete]").click()
                edited.first.wait_for(state="detached", timeout=20000)
                ok(page.locator("[data-reminder-item]", has_text=stamp).count() == 0,
                   "reminder deleted from the UI")
                ok(page.locator(".error-box").count() == 0, "reminders flow has no error box")
                page.screenshot(path=str(ROOT / "tools" / "logs" / "reminders.png"))
            except Exception as exc:
                ok(False, "reminders CRUD from the inbox", str(exc)[:200])

            admin_ctx.close()

            browser.close()

        real_errors = [e for e in console_errors if not any(g in e for g in IGNORED_CONSOLE)]
        ok(not real_errors, "no console/page errors", "; ".join(real_errors[:4]))

        print()
        print(f"RESULT {PASSES} passed, {len(FAILURES)} failed")
        if FAILURES:
            print("FAILED: " + ", ".join(FAILURES))
        return 1 if FAILURES else 0
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        for handle in logs:
            handle.close()


if __name__ == "__main__":
    sys.exit(main())
