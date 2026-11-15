"""Live end-to-end demo of the interview engine against a running server.

Usage (server already running):
    python scripts/demo_interview.py [--base http://localhost:8000] [--cv path/to/cv.pdf] [--voice]

--voice answers Q1 by speaking: the answer is turned into a WAV with Windows' built-in text-to-speech
(or tests/fixtures/sample.wav if that is unavailable), transcribed by the server, then evaluated.

Never prints the JWT. Exits 1 if any check fails.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

EMAIL, PASSWORD = "ayesha@intervo.demo", "Demo@1234"
DEFAULT_CV = r"C:\Users\UsEr\Downloads\intervo-cv-update\sample-cvs\Ali_Raza_CV.pdf"
WEAK_ANSWER = "I don't know much about this."

# Detailed answers keyed by skill; the fallbacks cover anything else the planner picks.
GOOD_BY_SKILL = {
    "react": (
        "In my last project, a student marketplace dashboard, I used React with function components and hooks. "
        "I kept shared state in a context plus useReducer, memoised the expensive product list with useMemo and "
        "React.memo, and split routes with React.lazy and Suspense. I fixed unnecessary re-renders by profiling "
        "with the React DevTools Profiler and moving state closer to where it was used. As a result the main page "
        "render time dropped from about 900ms to 300ms and the Lighthouse performance score went from 62 to 91."
    ),
    "javascript": (
        "On a recent project I built a search page in JavaScript where closures and async/await were central. "
        "I debounced the input with a closure holding the timer, fetched results with fetch and async/await using "
        "try/catch, and cancelled stale requests with AbortController so older responses could not overwrite newer "
        "ones. I also used Promise.all to load filters and results in parallel. The result was a 40% drop in API "
        "calls and no more flickering results, which our testers confirmed."
    ),
    "css": (
        "In my portfolio and a client landing page I used CSS Grid for the page layout and Flexbox for components, "
        "with mobile-first media queries and CSS variables for theming. I debugged a layout overflow by inspecting "
        "the box model and replacing fixed widths with minmax and clamp. The result was a fully responsive layout "
        "from 320px to 1440px with no horizontal scroll, and the design review passed on the first round."
    ),
    "html": (
        "In a university project I built the whole front end with semantic HTML: header, nav, main, section and "
        "article elements, proper label and for attributes on forms, and alt text on images. I validated with the "
        "W3C validator and tested with a screen reader. As a result accessibility score in Lighthouse went from 71 "
        "to 98 and the form completion rate in our small user test improved noticeably."
    ),
    "typescript": (
        "In my last project I migrated a JavaScript React app to TypeScript. I defined interfaces for API "
        "responses, used generics for a reusable fetch hook, and union types for component variants. The compiler "
        "caught around 15 latent bugs during migration, such as undefined props, and afterwards runtime type "
        "errors in production dropped to almost zero."
    ),
    "testing": (
        "I decide what to test by risk and user impact. In my last project, a React student marketplace, I wrote "
        "unit tests with Jest for pure logic like price and discount calculation, integration tests with React "
        "Testing Library for the checkout form, and one end-to-end Cypress test for the critical path: login, add "
        "to cart, pay. I also test edge cases such as empty carts, invalid input and failed API calls, and I add a "
        "regression test for every bug I fix. As a result we caught a coupon bug before release, coverage on "
        "business logic reached 85%, and production bugs dropped to almost none."
    ),
    "git": (
        "On my team project we used feature branches with pull requests and short-lived branches off main. I wrote "
        "small commits with clear messages, rebased before merging, and resolved merge conflicts locally with "
        "git mergetool. Once I used git bisect to find the commit that broke the build and git revert to undo it "
        "safely. The result was a clean history, no lost work, and release day merges that took minutes."
    ),
}
# Follow-up answers keyed by skill, so the follow-up stays on the topic of the weak question.
FOLLOW_UP_BY_SKILL = {
    "html": (
        "Let me answer properly. Semantic HTML gives meaning to the page: header, nav, main, section, article and "
        "footer instead of generic divs. It helps screen-reader users because landmarks let them jump between "
        "regions, and headings give them an outline of the page. It also improves SEO because crawlers understand "
        "the structure, and keeps code easier to maintain. In my portfolio project I replaced a div-only layout "
        "with semantic tags, labels and alt text, and my Lighthouse accessibility score went from 71 to 98."
    ),
    "testing": (
        "Let me answer properly. I prioritise by risk: business logic and the critical user path first. In a "
        "project I tested a checkout form with Jest and React Testing Library, covering valid input, empty fields, "
        "an expired coupon and a failed payment API call, which are the edge cases that break in production. "
        "That found a real bug before release and raised logic coverage to 85%."
    ),
}
FOLLOW_UP_GENERIC = (
    "Let me answer properly. In a project I built, a student marketplace front end, I handled this by reading "
    "the requirements, implementing it step by step, and testing it. For example, I fixed a slow product list by "
    "memoising it and lazy loading, which cut load time from 900ms to 300ms. The result was a stable release "
    "that my team and supervisor were happy with."
)
GOOD_TECHNICAL = (
    "In a project I worked on, a small e-commerce front end, I applied this directly. I first broke the problem "
    "into components, chose the simplest approach that met the requirement, and measured before optimising. "
    "For example I profiled the page with Chrome DevTools, found a slow list render, and fixed it with "
    "memoisation and lazy loading. The result was a roughly 50% faster load time, and I wrote tests to make "
    "sure the behaviour stayed correct."
)
GOOD_BEHAVIORAL = (
    "Situation: in my final-year project our team of four was two weeks from the deadline and the login module "
    "was failing. Task: as the front-end lead I was responsible for fixing it without delaying the demo. "
    "Action: I organised a quick meeting, split the bug into small tasks, paired with a teammate on the token "
    "handling, and wrote a checklist for testing. Result: we fixed it in three days, delivered on time, and "
    "received the top grade; I learned to communicate early and break work down."
)
FIXTURE_WAV = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample.wav"
results: list[tuple[str, bool, str]] = []


def speak_to_wav(text: str, out: Path) -> bool:
    """Spoken WAV from Windows' System.Speech. False if no text-to-speech tool is available."""
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$s.SetOutputToWaveFile($env:DEMO_WAV); $s.Speak($env:DEMO_TEXT); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=120, capture_output=True,
                       env={**__import__("os").environ, "DEMO_WAV": str(out), "DEMO_TEXT": text})
        return out.exists() and out.stat().st_size > 1000
    except (OSError, subprocess.SubprocessError):
        return False


def hr(title: str) -> None:
    print(f"\n=== {title} ===")


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def call(client: httpx.Client, method: str, path: str, **kw) -> dict | list:
    r = client.request(method, path, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def good_answer(q: dict) -> str:
    if q["type"] == "behavioral":
        return GOOD_BEHAVIORAL
    return GOOD_BY_SKILL.get(q["skill"].lower(), GOOD_TECHNICAL)


def show_eval(res: dict) -> None:
    print(f"  overall score : {res['score']}")
    for k, v in res["criteria"].items():
        print(f"    - {k:<14}{v}")
    for t in res["tips"]:
        print(f"  tip           : {t}")
    print(f"  provider      : {res['provider']}")
    print(f"  follow-up     : {'YES - ' + res['followUp']['question'] if res['needsFollowUp'] else 'no'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--cv", default=DEFAULT_CV)
    ap.add_argument("--voice", action="store_true", help="answer Q1 by voice (speech-to-text)")
    args = ap.parse_args()

    with httpx.Client(base_url=args.base + "/api", timeout=120) as client:
        hr("1. Login")
        auth = call(client, "POST", "/auth/login", json={"email": EMAIL, "password": PASSWORD, "role": "candidate"})
        client.headers["Authorization"] = f"Bearer {auth['token']}"  # never printed
        print(f"  logged in as {auth['user']['email']} ({auth['user']['role']})")

        hr("2. Upload CV")
        cv_path = Path(args.cv)
        with cv_path.open("rb") as f:
            cv = call(client, "POST", "/cv", files={"file": (cv_path.name, f, "application/pdf")})
        print(f"  provider        : {cv['provider']}")
        print(f"  experienceYears : {cv['cv']['experienceYears']}")

        hr("3. Start interview (frontend, text, 3 questions)")
        iv = call(client, "POST", "/interviews", json={"roleId": "frontend", "mode": "text", "count": 3})
        qs = iv["questions"]
        for i, q in enumerate(qs, 1):
            print(f"  Q{i} [{q['skill']} | {q['type']} | reason={q['reason']}]\n      {q['question']}")
        base = f"/interviews/{iv['id']}"

        if args.voice:
            hr("4. Q1 - good answer, spoken (speech-to-text)")
            spoken = good_answer(qs[0])
            wav = Path(tempfile.gettempdir()) / "intervo_demo_answer.wav"
            if speak_to_wav(spoken, wav):
                print(f"  audio         : generated with text-to-speech ({wav.stat().st_size // 1024} KB)")
            else:
                wav = FIXTURE_WAV
                print(f"  audio         : no text-to-speech tool; using {wav.name} (a tone, so expect an empty transcript)")
            try:
                with wav.open("rb") as f:
                    t = client.post(f"{base}/transcribe", files={"audio": (wav.name, f, "audio/wav")})
                if t.status_code == 503:
                    check("speech-to-text available", False, "503 Speech-to-text unavailable (set STT_PROVIDER=groq)")
                    print("  transcribe    : 503 Speech-to-text unavailable; the frontend would use browser speech recognition")
                    a1 = call(client, "POST", f"{base}/answers", json={"questionId": qs[0]["id"], "answer": spoken})
                else:
                    t.raise_for_status() if t.status_code < 400 else sys.exit(f"transcribe -> HTTP {t.status_code}: {t.text[:300]}")
                    tj = t.json()
                    print(f"  spoken text   : {spoken[:90]}...")
                    print(f"  transcript    : {tj['transcript']}")
                    print(f"  duration/lang : {tj['durationSeconds']}s / {tj['language']}   (provider: {tj['provider']})")
                    check("transcript returned", bool(tj["transcript"].strip()), f"{len(tj['transcript'].split())} words")
                    with wav.open("rb") as f:
                        a1 = call(client, "POST", f"{base}/answers", data={"questionId": qs[0]["id"]},
                                  files={"audio": (wav.name, f, "audio/wav")})
                    stored = next(q for q in call(client, "GET", base)["questions"] if q["id"] == qs[0]["id"])
                    check("answer stored as voice, transcript saved", a1["answerSource"] == "voice" and bool(stored["answer"]),
                          f"source={a1['answerSource']}")
            finally:
                if wav != FIXTURE_WAV:
                    wav.unlink(missing_ok=True)  # never keep the audio
        else:
            hr("4. Q1 - good detailed answer")
            a1 = call(client, "POST", f"{base}/answers", json={"questionId": qs[0]["id"], "answer": good_answer(qs[0])})
        show_eval(a1)
        check("provider is gemini", a1["provider"].startswith("gemini"), f"provider={a1['provider']}")

        hr("5. Q2 - weak answer, then follow-up")
        a2 = call(client, "POST", f"{base}/answers", json={"questionId": qs[1]["id"], "answer": WEAK_ANSWER})
        show_eval(a2)
        before = a2["score"]
        triggered = bool(a2["needsFollowUp"] and a2["followUp"])
        check("follow-up triggered on weak answer", triggered, f"score={before}")
        after = before
        if triggered:
            fu = call(client, "POST", f"{base}/answers/{a2['answerId']}/follow-up", json={"answer": FOLLOW_UP_BY_SKILL.get(qs[1]["skill"].lower(), FOLLOW_UP_GENERIC)})
            after = fu["score"]
            print(f"\n  re-evaluated after follow-up (provider={fu['provider']}):")
            print(f"  score before -> after : {before} -> {after}")
            for k, v in fu["criteria"].items():
                print(f"    - {k:<14}{v}")
        check("score improved after follow-up", triggered and after > before, f"{before} -> {after}")

        hr("6. Q3 - normal answer, then finish")
        a3 = call(client, "POST", f"{base}/answers", json={"questionId": qs[2]["id"], "answer": good_answer(qs[2])})
        show_eval(a3)
        if a3["needsFollowUp"]:
            print("  (follow-up offered on Q3; skipped intentionally)")
        done = call(client, "POST", f"{base}/finish")
        print(f"  session status : {done['status']}")
        print(f"  session score  : {done['score']}")
        check("session finished", done["status"] == "completed", f"score={done['score']}")

        hr("7. Progress")
        prog = call(client, "GET", "/progress")
        print(f"  sessions completed: {prog['sessionsCompleted']}   average score: {prog['averageScore']}")
        for s in prog["skills"]:
            print(f"    - {s['skill']:<22} avg={s['avg']:<5} sessions={s['sessions']} trend={s['trend']} weak={s['weak']}")
        weak = [w["skill"] for w in prog["weaknessProfile"]]
        print(f"  weak skills: {', '.join(weak) if weak else 'none'}")
        check("progress returned", prog["sessionsCompleted"] >= 1 and bool(prog["skills"]),
              f"{len(prog['skills'])} skills")

    hr("8. Results")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
