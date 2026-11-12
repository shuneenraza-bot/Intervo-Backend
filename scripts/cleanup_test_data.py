"""Removes leftover test data from the database in DATABASE_URL (.env).

1. Lists users whose email is not shaped like name@domain.tld and, after confirmation,
   deletes them with their profile, applications and interview sessions.
2. Strips stray quote characters from the start or end of job titles.

Run from the project root:

    python -m scripts.cleanup_test_data --dry-run     # show what would change, change nothing
    python -m scripts.cleanup_test_data               # fix titles, ask before deleting users
    python -m scripts.cleanup_test_data --skip-users  # fix titles only
    python -m scripts.cleanup_test_data --yes         # fix titles and delete without asking

Jobs posted by a deleted employer are deleted too (with their applications), otherwise
they would stay behind as listings nobody can manage.
"""

import argparse
import re
import sys

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import Application, CandidateProfile, InterviewSession, Job, User

# name@domain.tld: one @, no spaces, at least one dot in the domain, alphabetic TLD of 2+ letters.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")

QUOTES = "\"'“”‘’`"
STRIP_CHARS = QUOTES + " \t\r\n"


def is_valid_email(email: str | None) -> bool:
    return bool(email) and EMAIL_RE.fullmatch(email) is not None


def clean_title(title: str) -> str:
    return title.strip(STRIP_CHARS)


def find_invalid_users(db) -> list[dict]:
    rows = []
    for user in db.scalars(select(User).order_by(User.created_at)):
        if is_valid_email(user.email):
            continue

        def count(model, column) -> int:
            return db.scalar(select(func.count()).select_from(model).where(column == user.id)) or 0

        rows.append({
            "user": user,
            "profile": count(CandidateProfile, CandidateProfile.user_id),
            "applications": count(Application, Application.candidate_id),
            "sessions": count(InterviewSession, InterviewSession.candidate_id),
            "jobs": count(Job, Job.employer_id),
        })
    return rows


def print_invalid_users(rows: list[dict]) -> None:
    if not rows:
        print("Users with an invalid email: none.")
        return
    print(f"Users with an invalid email: {len(rows)}")
    header = f"  {'id':<20} {'role':<10} {'name':<24} {'email':<32} {'created':<10} prof apps sess jobs"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        u = row["user"]
        print(
            f"  {u.id:<20} {u.role:<10} {u.name[:24]:<24} {u.email[:32]!r:<32} "
            f"{u.created_at:%Y-%m-%d} {row['profile']:>4} {row['applications']:>4} "
            f"{row['sessions']:>4} {row['jobs']:>4}"
        )


def delete_users(db, rows: list[dict]) -> None:
    ids = [row["user"].id for row in rows]
    # Explicit deletes, children first, so nothing depends on the database's cascade rules.
    job_ids = list(db.scalars(select(Job.id).where(Job.employer_id.in_(ids))))
    for job in db.scalars(select(Job).where(Job.id.in_(job_ids))):
        db.delete(job)  # ORM cascade removes its job_skills and applications
    db.flush()
    db.execute(delete(Application).where(Application.candidate_id.in_(ids)))
    for session in db.scalars(select(InterviewSession).where(InterviewSession.candidate_id.in_(ids))):
        db.delete(session)  # ORM cascade removes its answers
    db.flush()
    db.execute(delete(CandidateProfile).where(CandidateProfile.user_id.in_(ids)))
    db.execute(delete(User).where(User.id.in_(ids)))


def find_bad_titles(db) -> list[tuple[Job, str]]:
    return [
        (job, clean_title(job.title))
        for job in db.scalars(select(Job).order_by(Job.created_at))
        if job.title and (job.title[0] in QUOTES or job.title[-1] in QUOTES)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    parser.add_argument("--yes", action="store_true", help="delete the listed users without asking")
    parser.add_argument("--skip-users", action="store_true", help="only fix job titles")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # curly quotes on Windows consoles

    with SessionLocal() as db:
        # ---- job titles ----
        titles = find_bad_titles(db)
        print(f"Job titles with stray quotes: {len(titles) or 'none.'}")
        for job, fixed in titles:
            if not fixed:
                print(f"  {job.id}: {job.title!r} is only quotes, left unchanged")
                continue
            print(f"  {job.id}: {job.title!r} -> {fixed!r}")
            if not args.dry_run:
                job.title = fixed
        if not args.dry_run:
            db.commit()
            if titles:
                print("Job titles fixed.")
        print()

        # ---- users ----
        rows = find_invalid_users(db)
        print_invalid_users(rows)
        if not rows or args.dry_run or args.skip_users:
            if rows:
                print("\nNo users were deleted.")
            return 0

        if not args.yes:
            if not sys.stdin.isatty():
                print("\nNot deleting: no terminal to confirm on. Re-run with --yes to delete.")
                return 0
            answer = input(f'\nType "delete" to remove these {len(rows)} users and their data: ')
            if answer.strip().lower() != "delete":
                print("Nothing deleted.")
                return 0

        delete_users(db, rows)
        db.commit()
        print(f"\nDeleted {len(rows)} users with their profiles, applications, sessions and jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
