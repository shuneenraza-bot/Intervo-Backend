"""Face ID template comparison. Mirrors compareGeometry in the frontend's src/faceCues.js."""

from typing import Any

GEOMETRY_SCALE = 0.12  # mean distance difference that maps to similarity 0
DEFAULT_FACE_THRESHOLD = 0.55


def is_landmark_template(template: Any) -> bool:
    """True for a current landmark template ({"v": 2, "features": [...]}); legacy pixel arrays don't count."""
    return (
        isinstance(template, dict)
        and template.get("v") == 2
        and isinstance(template.get("features"), list)
        and len(template["features"]) > 0
    )


def compare_geometry(a: list[float], b: list[float]) -> float:
    """similarity = max(0, 1 - mean(|a - b|) / 0.12), in the range 0..1."""
    if not a or not b or len(a) != len(b):
        return 0.0
    mean_diff = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    return max(0.0, 1 - mean_diff / GEOMETRY_SCALE)
