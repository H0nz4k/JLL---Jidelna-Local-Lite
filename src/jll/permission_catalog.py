"""České popisky a skupiny oprávnění pro běžné GUI.

Interní permission stringy (`diners.view` …) zůstávají ve store a v auditu.
Běžný uživatel je v UI nikdy nevidí.
"""

from __future__ import annotations

from dataclasses import dataclass

from .policy import Permission


@dataclass(frozen=True, slots=True)
class PermissionMeta:
    permission: Permission
    group: str
    title_cs: str
    description_cs: str

    @property
    def value(self) -> str:
        return self.permission.value


PERMISSION_CATALOG: tuple[PermissionMeta, ...] = (
    PermissionMeta(
        Permission.DINERS_VIEW,
        "STRÁVNÍCI",
        "Zobrazit strávníky",
        "Vyhledávání a zobrazení karty strávníka.",
    ),
    PermissionMeta(
        Permission.DINERS_CREATE,
        "STRÁVNÍCI",
        "Přidat strávníka",
        "Založení nového strávníka.",
    ),
    PermissionMeta(
        Permission.DINERS_EDIT,
        "STRÁVNÍCI",
        "Upravit strávníka",
        "Úprava údajů existujícího strávníka.",
    ),
    PermissionMeta(
        Permission.CHIPS_VIEW,
        "ČIPY",
        "Zobrazit čipy",
        "Zobrazení čipů a identifikace strávníka čipem.",
    ),
    PermissionMeta(
        Permission.CHIPS_ASSIGN,
        "ČIPY",
        "Přidělit čip",
        "Přiřazení nového čipu strávníkovi.",
    ),
    PermissionMeta(
        Permission.CHIPS_RETURN,
        "ČIPY",
        "Vrátit čip",
        "Vrácení / odebrání přiděleného čipu.",
    ),
    PermissionMeta(
        Permission.CHIPS_BLOCK,
        "ČIPY",
        "Blokovat čip",
        "Zablokování čipu.",
    ),
    PermissionMeta(
        Permission.CHIPS_LOST,
        "ČIPY",
        "Označit čip jako ztracený",
        "Evidence ztraceného čipu.",
    ),
    PermissionMeta(
        Permission.PAYMENTS_VIEW,
        "PLATBY",
        "Zobrazit platby",
        "Historie a detail plateb / záloh za čip na kartě strávníka.",
    ),
    PermissionMeta(
        Permission.PAYMENTS_POST,
        "PLATBY",
        "Zaúčtovat platbu",
        "Ruční zaúčtování platby a finanční záloha/vratka za čip.",
    ),
    PermissionMeta(
        Permission.ORDERS_VIEW,
        "OBJEDNÁVKY",
        "Zobrazit objednávky",
        "Náhled přihlášek, odhlášek a objednaných menu.",
    ),
    PermissionMeta(
        Permission.ORDERS_CHANGE,
        "OBJEDNÁVKY",
        "Měnit objednávky",
        "Přihlášení, odhlášení a změna menu.",
    ),
    PermissionMeta(
        Permission.PICKUP_STATUS_VIEW,
        "PROVOZ",
        "Zobrazit stav výdeje",
        "Přehled objednáno / vydáno / zbývá.",
    ),
    PermissionMeta(
        Permission.REPORTS_VIEW,
        "PROVOZ",
        "Zobrazit sestavy",
        "Náhled provozních a jmenných sestav.",
    ),
    PermissionMeta(
        Permission.REPORTS_PRINT,
        "PROVOZ",
        "Tisk a PDF sestav",
        "Vytváření PDF a tisk sestav.",
    ),
    PermissionMeta(
        Permission.ADMIN_USERS,
        "ADMINISTRACE",
        "Správa uživatelů",
        "Přidávání, deaktivace a správa účtů JLL.",
    ),
    PermissionMeta(
        Permission.ADMIN_PERMISSIONS,
        "ADMINISTRACE",
        "Správa oprávnění",
        "Nastavení práv jednotlivých uživatelů.",
    ),
    PermissionMeta(
        Permission.ADMIN_CATEGORIES,
        "ADMINISTRACE",
        "Správa kategorií",
        "Nastavení kategorií dostupných této instalaci.",
    ),
    PermissionMeta(
        Permission.ADMIN_DATABASE,
        "ADMINISTRACE",
        "Nastavení databáze",
        "Zobrazení a správa nastavení databázového připojení.",
    ),
    PermissionMeta(
        Permission.ADMIN_INSTANCE,
        "ADMINISTRACE",
        "Nastavení stanice",
        "Nastavení identity této stanice.",
    ),
    PermissionMeta(
        Permission.ADMIN_AUDIT,
        "ADMINISTRACE",
        "Audit",
        "Zobrazení historie změn.",
    ),
    PermissionMeta(
        Permission.ADMIN_READER,
        "ADMINISTRACE",
        "Nastavení čtečky",
        "COM port, komunikace a test čtečky.",
    ),
)

_BY_PERMISSION = {item.permission: item for item in PERMISSION_CATALOG}

GROUP_ORDER: tuple[str, ...] = (
    "STRÁVNÍCI",
    "ČIPY",
    "PLATBY",
    "OBJEDNÁVKY",
    "PROVOZ",
    "ADMINISTRACE",
)

#: Výchozí oprávnění běžného uživatele při setupu.
DEFAULT_OPERATOR_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.DINERS_VIEW,
        Permission.CHIPS_VIEW,
        Permission.ORDERS_VIEW,
        Permission.ORDERS_CHANGE,
    }
)


def permission_meta(permission: Permission) -> PermissionMeta:
    return _BY_PERMISSION[permission]


def permission_title(permission: Permission) -> str:
    return permission_meta(permission).title_cs


def permission_description(permission: Permission) -> str:
    return permission_meta(permission).description_cs


def missing_permission_text(permission: Permission) -> str:
    return f"Nemáte oprávnění „{permission_title(permission)}“."


def permissions_in_group(
    group: str,
    *,
    include_admin: bool = True,
) -> tuple[PermissionMeta, ...]:
    return tuple(
        item
        for item in PERMISSION_CATALOG
        if item.group == group
        and (include_admin or not item.permission.value.startswith("admin."))
    )


def summarize_permissions(permissions: frozenset[Permission]) -> str:
    """Krátký lidský souhrn oprávnění pro setup souhrn."""

    lines: list[str] = []
    for group in GROUP_ORDER:
        titles = [
            item.title_cs.casefold().removeprefix("zobrazit ").removeprefix("měnit ")
            for item in permissions_in_group(group, include_admin=False)
            if item.permission in permissions
        ]
        if not titles:
            continue
        # Jednoduchý český souhrn bez technických identifikátorů.
        readable = []
        for item in permissions_in_group(group, include_admin=False):
            if item.permission not in permissions:
                continue
            readable.append(item.title_cs.casefold())
        if readable:
            lines.append(f"{group.title()}: {', '.join(readable)}")
    return "\n".join(lines) if lines else "žádná"
