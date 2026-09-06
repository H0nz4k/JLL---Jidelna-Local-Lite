"""Application routes for Flet shell."""

from __future__ import annotations

from enum import StrEnum


class Route(StrEnum):
    DINERS = "diners"
    SERVING = "serving"
    REPORTS = "reports"
    ADMIN = "admin"
    SETUP = "setup"
    DIAGNOSTICS = "diagnostics"


NAV_ITEMS: tuple[tuple[Route, str, str], ...] = (
    (Route.DINERS, "Strávníci", "people"),
    (Route.SERVING, "Stav výdeje", "restaurant"),
    (Route.REPORTS, "Sestavy", "assessment"),
    (Route.ADMIN, "Administrace", "settings"),
)
