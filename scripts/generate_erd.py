"""Writes docs/ERD.md: a Mermaid ER diagram built from the SQLAlchemy models.

Run from the project root after changing a model:

    python -m scripts.generate_erd

Tables, columns, keys and cardinality are read from Base.metadata, so the diagram cannot
drift from the code. Only the one-line descriptions and relationship labels live here.
"""

from pathlib import Path

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "ERD.md"

# Diagram order, grouped the way the README groups them.
GROUPS = {
    "Accounts": ["users", "candidate_profiles"],
    "Admin configuration": [
        "domains", "job_roles", "skills", "role_skills",
        "question_templates", "evaluation_criteria", "scoring_rules",
    ],
    "Jobs": ["jobs", "job_skills", "applications"],
    "Interviews": ["interview_sessions", "session_answers"],
}

DESCRIPTIONS = {
    "users": "An account: candidate, employer or admin. Holds the argon2 password hash, the optional Face ID landmark template and the sign-in attempt counters.",
    "candidate_profiles": "One per candidate: confirmed skills, parsed CV summary, target role and the consent switch for sharing results with employers.",
    "domains": "A career field (Technology, Business, Marketing, HR & Finance) that groups job roles.",
    "job_roles": "A role template inside a domain, such as Frontend Developer, used for skill-gap analysis and interviews.",
    "skills": "The skill library: name, aliases used to detect the skill in a CV, related skills for partial matches and an improvement tip.",
    "role_skills": "Which skills a role template needs and how important each one is (weight 1 to 3).",
    "question_templates": "An interview question for one skill, technical or behavioral, with expected keywords and a follow-up question.",
    "evaluation_criteria": "A rubric criterion for scoring answers (relevance, clarity, STAR structure and so on) with its weight.",
    "scoring_rules": "A single row of admin-set rules: weakness threshold, follow-up trigger, Face ID match threshold and suitability weights.",
    "jobs": "A job posting by an employer, with success criteria (minimum interview score and minimum CV match).",
    "job_skills": "The skills a job posting requires and their weights (1 to 3), used for the CV match and suitability score.",
    "applications": "A candidate's application to a job, with their consent to share evidence and the employer's decision.",
    "interview_sessions": "One finished mock interview: candidate, role, mode (text, voice or video), overall score and date.",
    "session_answers": "One question inside a session: the skill tested, score, per-criterion scores, video cues and follow-up.",
}

# (table, foreign key column) -> label on the relationship line
LABELS = {
    ("candidate_profiles", "user_id"): "has profile",
    ("candidate_profiles", "target_role_id"): "is targeted by",
    ("job_roles", "domain_id"): "groups",
    ("role_skills", "role_id"): "requires",
    ("role_skills", "skill_id"): "is required by",
    ("question_templates", "skill_id"): "is tested by",
    ("jobs", "employer_id"): "posts",
    ("jobs", "role_id"): "is template for",
    ("job_skills", "job_id"): "requires",
    ("job_skills", "skill_id"): "is required by",
    ("applications", "job_id"): "receives",
    ("applications", "candidate_id"): "submits",
    ("interview_sessions", "candidate_id"): "practises in",
    ("interview_sessions", "role_id"): "is practised in",
    ("session_answers", "session_id"): "contains",
    ("session_answers", "skill_id"): "is assessed in",
    ("session_answers", "question_id"): "is asked in",
}


def type_name(column) -> str:
    t = column.type
    if isinstance(t, JSON):
        return "jsonb"
    if isinstance(t, Boolean):
        return "boolean"
    if isinstance(t, DateTime):
        return "timestamptz"
    if isinstance(t, Integer):
        return "int"
    if isinstance(t, Text):
        return "text"
    if isinstance(t, String):
        return f"varchar({t.length})" if t.length else "varchar"
    return str(t).lower()


def unique_columns(table) -> set[str]:
    """Columns that are unique on their own (not as part of a composite constraint)."""
    names = {c.name for c in table.columns if c.unique}
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and len(constraint.columns) == 1:
            names.add(next(iter(constraint.columns)).name)
    for index in table.indexes:
        if index.unique and len(index.columns) == 1:
            names.add(next(iter(index.columns)).name)
    return names


def entity(table) -> list[str]:
    unique = unique_columns(table)
    lines = [f"    {table.name} {{"]
    for column in table.columns:
        keys = []
        if column.primary_key:
            keys.append("PK")
        if column.foreign_keys:
            keys.append("FK")
        if column.name in unique and not column.primary_key:
            keys.append("UK")
        note = "" if column.nullable is False or column.primary_key else ' "nullable"'
        key_text = f" {', '.join(keys)}" if keys else ""
        lines.append(f"        {type_name(column)} {column.name}{key_text}{note}")
    lines.append("    }")
    return lines


def relationships(tables) -> list[tuple[str, str, str, str]]:
    """(parent, connector, child, label) for every foreign key."""
    result = []
    for table in tables:
        pk = [c.name for c in table.primary_key.columns]
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                left = "|o" if column.nullable else "||"  # optional or mandatory parent
                # A foreign key that is the child's whole primary key allows one child at most.
                right = "o|" if pk == [column.name] else "o{"
                label = LABELS.get((table.name, column.name), column.name)
                result.append((parent, f"{left}--{right}", table.name, label))
    return result


CARDINALITY = {
    "||--o{": "one to many, parent required",
    "|o--o{": "one to many, parent optional",
    "||--o|": "one to zero or one",
}


def build() -> str:
    metadata = Base.metadata
    ordered = [name for names in GROUPS.values() for name in names]
    missing = sorted(set(metadata.tables) - set(ordered))
    if missing or set(ordered) - set(metadata.tables):
        raise SystemExit(f"GROUPS in scripts/generate_erd.py is out of date. Not listed: {missing}")
    tables = [metadata.tables[name] for name in ordered]
    rels = relationships(tables)

    out = [
        "# Intervo database: entity relationship diagram",
        "",
        "<!-- Generated by scripts/generate_erd.py from the SQLAlchemy models. Do not edit by hand. -->",
        "",
        f"The PostgreSQL schema has {len(tables)} tables. This file is generated from the SQLAlchemy models in "
        "`app/models/` with `python -m scripts.generate_erd`, so it always matches the code.",
        "",
        "How to read it: `PK` primary key, `FK` foreign key, `UK` unique. Columns marked \"nullable\" may be empty; "
        "all others are required. `||--o{` is one to many, `|o--o{` is one to many where the parent is optional "
        "(the foreign key may be empty), and `||--o|` is one to zero or one.",
        "",
        "```mermaid",
        "erDiagram",
    ]
    for parent, connector, child, label in rels:
        out.append(f'    {parent} {connector} {child} : "{label}"')
    out.append("")
    for table in tables:
        out.extend(entity(table))
    out += ["```", ""]

    out += [
        "## Entities",
        "",
        "| Entity (table) | Group | Description |",
        "|---|---|---|",
    ]
    for group, names in GROUPS.items():
        for name in names:
            out.append(f"| `{name}` | {group} | {DESCRIPTIONS[name]} |")
    out.append("")

    out += [
        "## Relationships",
        "",
        "| Parent | Child | Foreign key | Cardinality | On delete |",
        "|---|---|---|---|---|",
    ]
    for table in tables:
        pk = [c.name for c in table.primary_key.columns]
        for column in table.columns:
            for fk in column.foreign_keys:
                connector = ("|o" if column.nullable else "||") + "--" + ("o|" if pk == [column.name] else "o{")
                out.append(
                    f"| `{fk.column.table.name}` | `{table.name}` | `{column.name}` | "
                    f"{CARDINALITY[connector]} | {fk.ondelete or 'NO ACTION'} |"
                )
    out.append("")

    out += [
        "## Notes for the design chapter",
        "",
        "- `role_skills` and `job_skills` are associative entities. They resolve the many-to-many relationships "
        "between roles and skills, and between jobs and skills, and carry the weight of each skill.",
        "- `applications` resolves the many-to-many relationship between candidates and jobs. A candidate can apply "
        "to a job only once (unique on `job_id` + `candidate_id`).",
        "- `users` holds all three roles in one table, separated by the `role` column. Only candidates have a "
        "`candidate_profiles` row.",
        "- `jobs.employer_id` may be empty for listings that are not owned by an Intervo employer account.",
        "- `scoring_rules` has exactly one row (`id = 1`), enforced by a check constraint.",
        "- JSON columns (`jsonb`) hold lists and nested objects that are always read as a whole: skill aliases, "
        "the parsed CV, per-criterion scores and the Face ID landmark template.",
        "- Every table has `created_at` and `updated_at`. IDs are short strings such as `cand-3f9a1c2b7d4e`.",
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT}")
