from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .orders.errors import ErrorCode, OrderBusinessError


class Permission(StrEnum):
    DINERS_VIEW = "diners.view"
    DINERS_CREATE = "diners.create"
    DINERS_EDIT = "diners.edit"
    CHIPS_VIEW = "chips.view"
    CHIPS_ASSIGN = "chips.assign"
    CHIPS_RETURN = "chips.return"
    CHIPS_BLOCK = "chips.block"
    CHIPS_LOST = "chips.lost"
    ORDERS_VIEW = "orders.view"
    ORDERS_CHANGE = "orders.change"
    PICKUP_STATUS_VIEW = "pickup_status.view"
    REPORTS_VIEW = "reports.view"
    REPORTS_PRINT = "reports.print"
    ADMIN_USERS = "admin.users"
    ADMIN_PERMISSIONS = "admin.permissions"
    ADMIN_CATEGORIES = "admin.categories"
    ADMIN_DATABASE = "admin.database"
    ADMIN_INSTANCE = "admin.instance"
    ADMIN_AUDIT = "admin.audit"
    ADMIN_READER = "admin.reader"


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    user_identity: str
    allowed_categories: frozenset[str]
    permissions: frozenset[Permission]

    def __post_init__(self) -> None:
        if not self.user_identity.strip():
            raise ValueError("user_identity nesmí být prázdná.")
        if not self.allowed_categories:
            raise ValueError("allowed_categories nesmí být prázdné.")

    def require(self, permission: Permission) -> None:
        if permission not in self.permissions:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Session nemá oprávnění pro tuto operaci.",
                context={"permission": permission.value},
            )

    def scope(self) -> frozenset[str]:
        return self.allowed_categories
