# Rules audit

Audit date: 2026-11-22; updated the same day after the fixes listed at the end. Read-only check of this backend and `C:\Users\UsEr\Intervo-Frontend` (FE). No `.env` values were read.

Status: **IMPLEMENTED**, **PARTLY**, **NOT IMPLEMENTED**. Paths are backend paths unless marked FE.

Two things apply to many rows:

- The CV regex rules (headings, dates, degrees, CGPA) in `app/services/cv_rules.py` run only in the rule-based fallback. When Gemini answers, Gemini fills those fields. Skill alias matching, contact patterns and experience months always run in Python.
- The frontend can run without the backend (`VITE_BACKEND_MODULES` empty). That "local mode" has its own copy of several rules and is weaker in places. Those cases are marked FE.

## 1. CV parsing

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Section headings | IMPLEMENTED (fallback parser only) | 7 groups: summary, education, experience, projects, skills, certifications, other. Heading max 38 chars, no 3+ digits, no `@`; match is exact or the heading word plus up to 3 more words | `app/services/cv_rules.py:13-21`, `heading_of` at `:66` |
| Date patterns | IMPLEMENTED | Optional month name, optional `d/`, year 1900-2099. Range separators: `- – — to till until`. End can be `present current now ongoing date`. Single year also found | `cv_rules.py:24-27` |
| Degree patterns | IMPLEMENTED | PhD, master's/MS/MSc/MPhil/MBA, bachelor's/BS/BSc/BE/BTech/BBA/BCS, intermediate/FSc/ICS/I.Com, A/O-levels, matric, SSC, HSSC, diploma, associate degree | `cv_rules.py:28-32`; levels 0-4 in `education_level` `:154` |
| CGPA / marks | IMPLEMENTED (fallback parser only) | `CGPA/GPA x[/y]` first, else `NN%`. Lines starting with gpa, percentage, grade, marks stay with the entry above | `cv_rules.py:33`, `:176-183` |
| Contact patterns | IMPLEMENTED | Email regex; Pakistani mobile `(+92\|0)3dd d{7}`, else any 10-17 digit number; `linkedin.com/in/…`, `github.com/…`; name = first 2-5 word line without `@ digits http`; location from 10 Pakistani city names | `cv_rules.py:37-39`, `parse_contact` `:210`; called always at `app/services/cv.py:83` |
| Skill alias matching | IMPLEMENTED, always runs | Whole-word, case-insensitive match of the skill name or any alias from the skill library. Also used as a safety net on top of Gemini | `cv_rules.py:46-54`; `cv.py:60`, `:76` |
| Experience years in Python | IMPLEMENTED | Months per job from the date text (kept per job for display). The total merges overlapping date ranges, so a calendar month counts once; the merged months / 12 are rounded to the nearest 0.5. A job without a readable date range adds its own months. Gemini's own numbers are ignored. Test: two overlapping jobs | `app/services/cv_rules.py:137` (`months_between`), `merged_months` and `years_from_months`; `app/services/cv.py:69-70`, `:91`; `tests/test_hardening_media.py` |
| 5 MB limit | IMPLEMENTED | 5 × 1024 × 1024 bytes. Reads at most limit+1 bytes. 413 if over | `app/services/cv_text.py:9`, `:100`; `app/routers/cv.py:41`. FE: `src/cvParser.js:14` |
| PDF / DOCX / TXT only | IMPLEMENTED | Extension plus content check (`%PDF-`, `PK`, no NUL bytes). `.doc` has its own error; anything else is 415. Also: PDF max 10 pages, text max 60,000 chars, DOCX max 50 MB unzipped | `cv_text.py:97-121`, `:10-13`. FE: `cvParser.js:15` |
| Scanned PDF rejected | IMPLEMENTED | Fewer than 60 letters/digits after extraction gives 422 with a "scanned image" message. Password-protected PDFs are also rejected | `cv_text.py:12`, `:123-130`. FE: `cvParser.js:40` |
| Contact details and name removed before Gemini | IMPLEMENTED | Removed: lines labelled Email, Phone, Mobile, Tel, WhatsApp, Address, Residence, Date of Birth, CNIC, Passport, Nationality, Father's name, Marital status; every email, phone number and http/www/linkedin/github link; every mention of the candidate's name (account name and the name found in the CV header); the name parts and any city/Pakistan line in the first 8 lines | `app/services/ai/prompts.py` (`CONTACT_LINE`, `CITY`, `strip_contact`); called with the names at `app/services/cv.py:138-141`; `tests/test_hardening_media.py` |

## 2. JD parsing

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Weight 3 | IMPLEMENTED, wider than the rule | Sentence containing the skill matches `must`, `required`, `requirement`, `strong`, `essential`, `proficien…`, `expert`, `solid` | `cv_rules.py:296`; Gemini prompt `prompts.py:64` |
| Weight 1 | IMPLEMENTED, wider than the rule | `nice to have`, `preferred`, `plus`, `bonus`, `familiar`, `desirable`, `good to have`. Weight 3 wins if both appear | `cv_rules.py:298` |
| Otherwise: role default, else 2 | IMPLEMENTED (differs from "otherwise 2", by design) | A skill with no must/nice-to-have wording keeps the weight the role gives that skill; only a skill the role does not list gets 2. With Gemini, a weight of 2 is replaced by the role default in the same way. Documented as the real behaviour; no code change | `cv_rules.py:295`; `app/services/cv.py:194-197` |
| Years detection | IMPLEMENTED | First `N years/yrs`, also `N+` and `N-M`. Takes the first number. Clamped 0-60 | `cv_rules.py:301`, `:307`; `cv.py:204` |
| Degree detection | IMPLEMENTED | bachelor's, master's, BS, MS, BSc, MSc, MBA, BBA, PhD, plus up to 60 chars after | `cv_rules.py:302`; checked in `requirement_checks` `:315` |
| Fresher-friendly flag | extra | `fresh`, `graduate`, `intern`, `entry level`, `0-1 years` waive the years check | `cv_rules.py:309`, `:323` |

## 3. CV match

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Matched = full weight | IMPLEMENTED | Skill in the candidate's list earns its weight (1-3) | `app/services/matching.py:30-46`; same logic in `cv_rules.py:337` |
| Partial = half weight | IMPLEMENTED | Candidate lacks the skill but has a skill in its `related` list: weight × 0.5 | `matching.py:40-42`, `:46` |
| Missing = zero | IMPLEMENTED | | `matching.py:43-44` |
| Percentage | IMPLEMENTED | `round_half_up( (Σ matched + 0.5 × Σ partial) / Σ all weights × 100 )`; 0 if no skills. Not AI | `matching.py:45-51` |
| Employer pass mark | extra | `meetsCriteria = percentage >= job.minMatch` (0-100) | `matching.py:88-89`; DB check `app/models/job.py:21` |

## 4. Question selection

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Priority weakness → gap → role | IMPLEMENTED | Rank weakness 0, CV gap 1, role 2, other 3. Ties follow the role's weight order. Gap = missing or partial skills | `app/services/interview.py:45`, `:115-119`, `:179-182` |
| At least one behavioural | IMPLEMENTED | If none was picked: random unused behavioural template, else Gemini writes one for Communication/Teamwork/Leadership. If the list is full, the last question is replaced | `interview.py:141-154` |
| No repeated skill | IMPLEMENTED | One question per skill (`used` set) | `interview.py:123-140` |
| Default count | IMPLEMENTED | 5 (`defaultQuestions`, admin-configurable). Client may send 1-10 | `interview.py:41`, `:184`; `app/schemas/interview.py:21`; `app/services/admin.py:50` |
| Skill with no template | extra | Gemini writes a technical question and saves it as a "generated" template; rules fallback gives a generic one that is not saved | `interview.py:83-100`, `:136` |

## 5. Scoring

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Criteria list | IMPLEMENTED | technical, relevance, completeness, clarity, communication, star. Stored in the DB, admin can disable or re-weight. Only criteria that apply to the question type are used | `interview.py:43`, `:209-212`; seed `scripts/seed.py:109-114` |
| Weights | IMPLEMENTED | technical 2 (technical questions only), relevance 2, completeness 2, clarity 1, communication 1, star 2 (behavioural only) | `scripts/seed.py:109-114`; fallback `interview.py:43` |
| Clamp 0-100 | IMPLEMENTED | Any number from the model is rounded and clamped to 0-100; booleans, NaN and text are rejected | `app/schemas/interview.py:66-71` |
| Pydantic validation | IMPLEMENTED | `LLMEvaluation` validates scores, tips (max 3, 220 chars) and the follow-up flag. Invalid JSON is retried once, then the rules evaluator is used | `schemas/interview.py:76-95`; `app/services/ai/__init__.py:32-54` |
| Overall score in Python | IMPLEMENTED | `round_half_up( Σ(score × weight) / Σ weight )`. Session score is the average of the answer scores | `interview.py:255-256`, `:368` |
| Fill only missing criteria | IMPLEMENTED | If Gemini omits criteria: retry once with a stricter prompt, then fill only the missing ones from the rules evaluator; provider is marked `gemini+rules` | `interview.py:238-252` |
| Rule-based evaluator checks | IMPLEMENTED | technical: keyword hits (30 + share × 62, +6 for example), clamp 25-97. relevance: skill aliases and question words found, 42 + 11 each (+8 example), clamp 30-96. completeness: 28 + 0.4 × words (max 170) (+6), clamp 22-96. clarity: 93 − 2.2 × |avg sentence length − 17|, clamp 35-95. communication: word variety and filler words, clamp 30-95. star: 32 + 16 per STAR part found, clamp 32-96 | `app/services/interview_rules.py:57-62`, `:9-17` |

## 6. Follow-up

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Trigger and threshold | IMPLEMENTED | Follow-up is needed when the model says so **or** completeness < 55 (`followUpBelow`, admin-configurable). The rules evaluator also triggers on technical < 50 for technical questions. A follow-up can be answered once; the answer is re-scored together with the first answer | `interview.py:260`, `:346`, `:349-353`; `interview_rules.py:84`; default 55 at `interview.py:41` |

## 7. Weakness rule

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Threshold and minimum sessions | IMPLEMENTED | Weak when the skill appeared in at least **2** completed sessions **and** its average is below **60**. Both are admin-configurable | `app/services/matching.py:15-17`, `:78`; `interview.py:176-177` |

## 8. Employer

| Rule | Status | Actual value | Where |
|---|---|---|---|
| CV match only, no interview data | IMPLEMENTED | Employer routes return match, checks, CV summary (top degree, years, project count) and a "Candidate #n" label (the name only after acceptance). Nothing from interview tables. Interview endpoints are candidate-only. FE text says the same | `app/services/jobs.py:220-259`; `app/services/matching.py:83-101`; `app/routers/interviews.py:15`; FE `src/EmployerApp.jsx:536` |
| Consent filter | IMPLEMENTED | Listed only if the application has `consent` **and** the candidate's profile has `share_with_employers`. Others are only counted in `hidden`. Same check for the CV and CV file endpoints | `jobs.py:235-238`; `app/services/applications.py:156` |
| Ranking | IMPLEMENTED | Sorted by CV match percentage, highest first; ties keep application order | `jobs.py:257` |
| Contact only after acceptance | IMPLEMENTED | Email and phone appear only when status is `accepted` | `jobs.py:254-255`; `applications.py:175-176` |
| Original CV only after acceptance | IMPLEMENTED | `cv-file` returns 403 unless status is `accepted`. Served with `Cache-Control: no-store` | `applications.py:184-187`; `app/routers/applications.py:559-566` |
| Candidate name before acceptance | IMPLEMENTED | Hidden. Until the candidate accepts, the employer sees "Candidate #1", "Candidate #2", … in ranking order. The real name appears only after acceptance, together with email and phone. A decline notification does not name the candidate either | `app/services/jobs.py:257-261`; `app/services/applications.py:136-141`; FE `src/api.js` (`getCandidatesSync`); `tests/test_hardening.py` |

## 9. Applications

| Rule | Status | Actual value | Where |
|---|---|---|---|
| CV required | IMPLEMENTED | 400 "Upload your CV before applying" | `jobs.py:154-156` |
| CV snapshot per application | IMPLEMENTED | Parsed CV, summary, skills and file name are deep-copied at apply time; the original file row is kept for it. Later edits or uploads do not change it | `jobs.py:157-165`; `app/services/cv_files.py:300-309` |
| One application per job | IMPLEMENTED | Check in code plus DB unique constraint on (job, candidate); race gives 409 | `jobs.py:150-152`, `:174-176`; `app/models/job.py:74` |
| One response per shortlist | IMPLEMENTED | Three layers: the candidate may respond only while the status is `shortlisted`; the application row is locked (`SELECT … FOR UPDATE`) while responding, so a second request waits and then gets 409; and a partial unique index allows at most one `accepted` / `declined_by_candidate` row per application. Migration `a7d1e3f95b21`. Tests: two simultaneous responses (one 200, one 409) and a direct duplicate insert refused by the index | `app/services/applications.py` (`respond`, `_load`); `app/models/job.py` (`uq_application_one_response`); `alembic/versions/20261122_a7d1e3f95b21_hardening.py`; `tests/test_hardening.py` |

## 10. Authentication

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Password and face both required | IMPLEMENTED | Login returns only a face-pending token. All normal endpoints need a full token and an enrolled face | `app/routers/auth.py:324-327`; `app/deps.py:50-60`; `app/services/security.py:27-39` |
| Face-pending token lifetime | IMPLEMENTED | 5 minutes | `security.py:29` |
| Password rules | IMPLEMENTED | Server: 8-128 characters with an upper-case letter, a lower-case letter and a digit (422 otherwise). The sign-up form checks the same rule before sending | `app/services/auth.py:21`, `check_password_rules`; `app/schemas/auth.py:40`; FE `src/lib.js` (`passwordMeetsRules`), `src/Auth.jsx:281` |
| Password lockout | IMPLEMENTED | 5 wrong passwords → locked 60 s (429 with `Retry-After`) | `auth.py:17-18`, `:114-122` |
| Face lockout | IMPLEMENTED | 3 wrong faces → locked 300 s; a fresh password step resets the face counter | `auth.py:19-20`, `:153`, `:167-174` |
| Blink liveness | IMPLEMENTED (evidence checked on the server; capture is in the browser) | The browser (MediaPipe, open < 0.35, closed > 0.55, 4 s window) sends the blink score of every frame it checked. The server requires 5-300 frames, strictly increasing times spanning 0.15-6 s, and open eyes followed by closed eyes; a bare `blink: true` is rejected (422). Limit: the frames are still reported by the client, so a modified client could forge a series; only server-side video analysis would prevent that | FE `src/Camera.jsx:63-65`, `landmarkLiveness`; FE `src/api.js` (`completeFace`); `app/services/liveness.py`; `app/schemas/auth.py:44-48`; `app/services/auth.py` (`verify_face`) |
| Face threshold | IMPLEMENTED | Default 0.55 similarity; admin can change it (`faceThreshold`). `similarity = max(0, 1 − mean abs difference / 0.12)` | `app/services/face.py:5-6`, `:19-23`; `auth.py:62-65`, `:166-167`; FE `src/data.js:93` |
| Face templates encrypted | IMPLEMENTED | Encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). Key: `FACE_ENCRYPTION_KEY`, or derived from `JWT_SECRET` if unset (set a separate key in production; losing it makes stored faces unreadable). The template is no longer sent to the browser: `/auth/me` returns only `face: { enrolled, enrolledAt }`. Existing rows were encrypted by migration `a7d1e3f95b21`; a plain legacy row is still readable | `app/services/face_crypto.py`; `app/models/user.py` (`EncryptedFace`); `app/schemas/auth.py:68-71`; `alembic/versions/20261122_a7d1e3f95b21_hardening.py`; FE `src/lib.js` (`hasFace`) |
| Admin face reset | IMPLEMENTED | Admin-only endpoint clears the template and counters; open sessions stop working and the user must enrol again at next sign-in | `app/routers/admin.py:152-155`; `app/services/admin.py:426-433`; `app/deps.py:56-58` |
| Admin cannot sign up | IMPLEMENTED | Sign-up accepts only `candidate` or `employer`; FE hides the admin tab on sign-up. Admins are created by the seed script | `app/schemas/auth.py:9`, `:37`; FE `src/Auth.jsx:23` |

## 11. Privacy

| Rule | Status | Actual value | Where |
|---|---|---|---|
| Argon2 | IMPLEMENTED (backend) | Argon2 through pwdlib. **Known limitation: FE local mode** (no backend) hashes passwords with salted SHA-256 in the browser, not Argon2. It is a demo mode for running without a server and is not meant for real accounts | `app/services/security.py:7`, `:13`; FE `src/lib.js:39-43` |
| No face images stored | IMPLEMENTED | Only 276 landmark distances are sent and stored; the server schema accepts only `v: 2` templates, max 2048 numbers. FE live-video frames are used only for brightness/motion and are not saved | `app/schemas/auth.py:14-17`; FE `src/faceCues.js:84-113`; FE `src/Camera.jsx:48` |
| Audio deleted after transcription | IMPLEMENTED | Audio is kept in memory, passed to Groq, and discarded; only the transcript is stored. Uploads up to 12 MB stay in memory (Starlette's default of spooling to a temp file above 1 MB is raised), so no recording touches the disk | `app/services/transcribe.py`; `app/routers/interviews.py:41`, `:77`; `app/main.py` (`MultiPartParser.spool_max_size`); `tests/test_hardening_media.py` |
| No name/email sent to Gemini | IMPLEMENTED | Interview prompts send only role, skill, question and the answer text. The CV prompt has email, phone, links, address lines, the candidate's name and header city removed (see section 1). An answer in which the candidate says their own name is not filtered | `app/services/ai/prompts.py`; `app/services/cv.py:138-141` |
| Voice size limit | IMPLEMENTED | 10 MB; types webm, ogg, wav, mp3, m4a, checked by file header | `transcribe.py:15`, `:17`, `:55-61` |
| Voice duration limit | IMPLEMENTED | 190 s. The length is read from the file before anything is sent: WAV (stdlib), WebM (Matroska timestamps), MP3 / OGG / M4A (mutagen). A longer file, or one whose length cannot be read, is refused with 422 and never reaches Groq. The provider's reported duration is still checked afterwards. FE stops recording at 3 minutes | `app/services/audio_length.py`; `app/services/transcribe.py:62-70`; FE `src/InterviewPage.jsx` (`MAX_RECORD_MS`); `tests/test_hardening_media.py` |
| English only | IMPLEMENTED | Whisper called with `language="en"`; response language fixed to `en` | `app/services/ai/speech.py:56`, `:64` |

## Open points and known differences

Fixed after the first audit (same day): encrypted face templates, server-checked blink evidence, server password rule, name and address kept from Gemini, audio length checked before upload and uploads kept in memory, merged overlapping experience, database guard for one response per shortlist, and hidden candidate names ("Candidate #n") until acceptance.

What still differs from a strict reading of the rules:

1. **Blink evidence is reported by the browser.** The server checks that it looks like a real blink, but cannot prove the frames came from a camera.
2. **Face encryption key.** If `FACE_ENCRYPTION_KEY` is not set, the key comes from `JWT_SECRET`; rotating that secret would make stored faces unreadable until users re-enrol.
3. **JD weight "otherwise 2"** is really "the role's skill weight, else 2". The keyword lists are longer than the rule (`strong`, `essential`, `proficient`, `familiar`, …).
4. **CV heading/date/degree/CGPA regex rules** apply only when Gemini is off or fails (rule-based fallback). With Gemini these fields come from the model; skill matching, contact patterns and experience months always run in Python.
5. **Frontend local mode** (no backend) hashes passwords with salted SHA-256 (not Argon2), keeps lockout counters in localStorage and holds its own copies of the CV and scoring rules. It is a known limitation of the demo mode and can drift from the backend.
6. **A name typed inside an interview answer** is sent to Gemini with the rest of the answer; only the CV text is filtered.
7. **Overlap merging needs readable dates.** A job whose dates cannot be parsed adds its own months and cannot be merged.
