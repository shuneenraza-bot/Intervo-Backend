from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """JSON uses camelCase (createdAt); Python uses snake_case (created_at)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def to_ms(dt: datetime | None) -> int | None:
    """datetime -> Unix epoch milliseconds, the timestamp format the frontend uses."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
