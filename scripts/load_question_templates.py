"""Loads the question templates in scripts/data/question_templates.json.

Run from the project root, after `alembic upgrade head` and `python -m scripts.seed_config`:

    python -m scripts.load_question_templates

Each template is matched by skill + question text (ignoring capital letters and extra spaces).
A template that is already there is left exactly as it is, so running the script again adds
nothing, an admin's edits are kept, and templates that past interviews used are never changed or
deleted. A template whose skill is not in the database is skipped and reported.
"""

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, new_id
from app.models import QuestionTemplate, Skill

DATA_FILE = Path(__file__).parent / "data" / "question_templates.json"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def read_templates(path: Path = DATA_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["templates"]


def load(db: Session, templates: list[dict] | None = None) -> dict:
    """Adds the missing templates. Does not commit. Returns {"added", "existing", "skipped": [...]}."""
    templates = read_templates() if templates is None else templates
    skills = {s.name: s.id for s in db.scalars(select(Skill))}
    have = {(q.skill_id, norm(q.text)) for q in db.scalars(select(QuestionTemplate))}
    report = {"added": 0, "existing": 0, "skipped": []}
    for t in templates:
        skill_id = skills.get(t["skill"])
        if skill_id is None:
            report["skipped"].append(t["skill"])
            continue
        key = (skill_id, norm(t["text"]))
        if key in have:
            report["existing"] += 1
            continue
        # the file's id when it is free; otherwise a new one (an admin may have used that id)
        id_ = t["id"] if db.get(QuestionTemplate, t["id"]) is None else new_id("q")
        db.add(QuestionTemplate(
            id=id_, skill_id=skill_id, type=t["type"], text=t["text"].strip(), keywords=t["keywords"],
            follow_up=t["followUp"], difficulty=t["difficulty"], source="admin",
        ))
        have.add(key)
        report["added"] += 1
    db.flush()
    return report


def main() -> None:
    with SessionLocal() as db:
        report = load(db)
        db.commit()
    print(f"Templates: {report['added']} added, {report['existing']} already there")
    if report["skipped"]:
        print(f"Skipped (skill not in the database - run python -m scripts.seed_config first): "
              f"{', '.join(sorted(set(report['skipped'])))}")


if __name__ == "__main__":
    main()
