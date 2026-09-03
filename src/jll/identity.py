from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


@dataclass(frozen=True, slots=True)
class ActorContext:
    site_id: str
    instance_id: str
    user_id: str
    short_code: str
    session_id: str
    client_version: str

    def __post_init__(self) -> None:
        for name in ("site_id", "instance_id", "user_id", "short_code"):
            value = getattr(self, name)
            if not IDENTIFIER_PATTERN.fullmatch(value):
                raise ValueError(f"{name} nemá platný formát.")
        if not self.session_id or len(self.session_id) > 64:
            raise ValueError("session_id nemá platný formát.")
        if not self.client_version or len(self.client_version) > 10:
            raise ValueError("client_version nemá platný formát.")
        if len(self.audit_actor) > 25:
            raise ValueError("Audit actor se nevejde do udalosti.uzivatel.")

    @property
    def audit_actor(self) -> str:
        return f"{self.instance_id}:{self.short_code}".upper()


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user_id: str
    session_id: str
    login_time: datetime

    @classmethod
    def create(cls, user_id: str) -> AuthenticatedSession:
        return cls(
            user_id=user_id,
            session_id=uuid.uuid4().hex,
            login_time=datetime.now(timezone.utc),
        )
