"""Čistá agregační logika denních sestav.

Modul nezná databázi ani GUI. Řadí a seskupuje už načtené řádky, aby stejná
pravidla platila pro náhled v GUI i pro tiskový výstup.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Sequence

from .read_models import (
    DEFAULT_NORMS,
    MISSING_NORM,
    NamedOrderRow,
    NormMenuSummary,
)


def czech_sort_key(text: str) -> tuple[str, str]:
    """Řazení, ve kterém diakritika nerozhazuje abecedu.

    Primárně se porovnává text bez diakritiky, takže `Čermák` je mezi
    `Cejnar` a `Dvořák` a ne až za `Z`. Digraf `ch` se neřeší, protože bez
    doložené collation databáze by šlo jen o odhad.
    """

    folded = text.casefold()
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFKD", folded)
        if not unicodedata.combining(char)
    )
    return (stripped, folded)


def sort_named_rows(rows: Sequence[NamedOrderRow]) -> list[NamedOrderRow]:
    """Řazení jmenného seznamu: jméno, typ stravy, číslo menu."""

    return sorted(
        rows,
        key=lambda row: (
            czech_sort_key(row.name),
            czech_sort_key(row.meal_type),
            row.menu,
            row.evidcislo,
        ),
    )


@dataclass(frozen=True, slots=True)
class CategoryBlock:
    category: str
    label: str
    rows: tuple[NamedOrderRow, ...]


def group_by_category(
    rows: Sequence[NamedOrderRow],
    category_order: Sequence[str] = (),
) -> list[CategoryBlock]:
    """Bloky jmenného seznamu podle kategorií.

    Kategorie bez objednávky blok nevytváří, aby v sestavě nezůstávaly
    prázdné oddíly. Pořadí respektuje `category_order`; kategorie mimo něj
    se doplní abecedně na konec.
    """

    grouped: dict[str, list[NamedOrderRow]] = {}
    for row in rows:
        grouped.setdefault(row.category, []).append(row)
    ordered_keys = [key for key in category_order if key in grouped]
    ordered_keys.extend(
        sorted(key for key in grouped if key not in set(category_order))
    )
    blocks: list[CategoryBlock] = []
    for key in ordered_keys:
        block_rows = sort_named_rows(grouped[key])
        label = next(
            (row.category_name for row in block_rows if row.category_name),
            key,
        )
        blocks.append(CategoryBlock(key, label, tuple(block_rows)))
    return blocks


@dataclass(frozen=True, slots=True)
class NormMatrix:
    """Tabulka norma × menu pro jeden typ stravy."""

    meal_type: str
    menus: tuple[int, ...]
    norms: tuple[str, ...]
    counts: dict[tuple[str, int], int]

    def portions(self, norm: str, menu: int) -> int:
        return self.counts.get((norm, menu), 0)

    def norm_total(self, norm: str) -> int:
        return sum(self.portions(norm, menu) for menu in self.menus)

    def menu_total(self, menu: int) -> int:
        return sum(self.portions(norm, menu) for norm in self.norms)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def norm_matrices(rows: Sequence[NormMenuSummary]) -> list[NormMatrix]:
    """Rozpad menu podle norem; A–D zůstávají i s nulou jako v referenci."""

    matrices: list[NormMatrix] = []
    for meal_type in sorted({row.meal_type for row in rows}, key=str.casefold):
        meal_rows = [row for row in rows if row.meal_type == meal_type]
        menus = tuple(sorted({row.menu for row in meal_rows}))
        extra = sorted(
            {
                row.norm_label
                for row in meal_rows
                if row.norm_label not in DEFAULT_NORMS
            },
            key=str.casefold,
        )
        counts: dict[tuple[str, int], int] = {}
        for row in meal_rows:
            key = (row.norm_label, row.menu)
            counts[key] = counts.get(key, 0) + row.portions
        matrices.append(
            NormMatrix(
                meal_type=meal_type,
                menus=menus,
                norms=(*DEFAULT_NORMS, *extra),
                counts=counts,
            )
        )
    return matrices


def norm_label(value: str | None) -> str:
    return value or MISSING_NORM
