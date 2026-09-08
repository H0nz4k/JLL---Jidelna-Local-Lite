"""HOME / Dnešní objednávky – Flet panel (read-only, blokový layout)."""

from __future__ import annotations

import flet as ft

from ...read_models import HomeTodayOverview, portions_cs
from .. import theme

HOME_CONTENT_WIDTH = 640
HOME_BLOCK_GAP = theme.SPACING["sm"]


def build_home_overview(
    overview: HomeTodayOverview | None,
    *,
    error: str | None = None,
    on_retry=None,
) -> ft.Control:
    """HOME jako sloupec samostatných bloků (připraveno na další sekce)."""

    if error:
        controls: list[ft.Control] = [
            theme.text(
                "Dnešní objednávky se nepodařilo načíst.",
                theme.TextRole.BODY,
                color=theme.COLORS["danger"],
            ),
            theme.text(error, theme.TextRole.META, color=theme.COLORS["text_secondary"]),
        ]
        if on_retry is not None:
            controls.append(
                ft.OutlinedButton(
                    "Zkusit znovu", style=theme.button_style(), on_click=on_retry
                )
            )
        return _home_stack([_home_block(controls)])

    if overview is None:
        return _home_stack(
            [
                _home_block(
                    [
                        theme.text(
                            "Načítám dnešní objednávky…",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        )
                    ]
                )
            ]
        )

    # Provozovna · stanice vlevo, datum vpravo – jeden tučný černý řádek.
    place = f"{overview.organization_name} · {overview.workplace_name}"
    header_block = _home_block(
        [
            ft.Row(
                [
                    theme.text(
                        place,
                        theme.TextRole.ACTION,
                        color="#000000",
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        expand=True,
                    ),
                    theme.text(
                        overview.date_label,
                        theme.TextRole.ACTION,
                        color="#000000",
                        max_lines=1,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]
    )

    if not overview.is_cooking_day:
        non_cook: list[ft.Control] = [
            theme.text("Dnešní objednávky", theme.TextRole.ACTION),
            theme.text("Dnes se nevaří.", theme.TextRole.BODY),
        ]
        if overview.next_cooking_day is not None:
            nxt = overview.next_cooking_day
            from ...read_models import BusinessCalendar

            weekday = BusinessCalendar._WEEKDAYS[nxt.weekday()]
            month = BusinessCalendar._MONTHS[nxt.month]
            titled = weekday[:1].upper() + weekday[1:]
            non_cook.append(
                theme.text(
                    f"Další varný den: {titled.lower()} {nxt.day}. {month} {nxt.year}",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
        return _home_stack([header_block, _home_block(non_cook)])

    order_controls: list[ft.Control] = [
        theme.text("Dnešní objednávky", theme.TextRole.ACTION),
    ]
    if not overview.meals:
        order_controls.append(
            theme.text(
                "Dnes nejsou žádné objednané porce.",
                theme.TextRole.BODY,
                color=theme.COLORS["text_secondary"],
            )
        )
    else:
        meal_rows: list[ft.Control] = []
        for meal in overview.meals:
            meal_rows.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                theme.text(
                                    meal.title_line,
                                    theme.TextRole.BODY,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True,
                                ),
                                theme.text(
                                    portions_cs(meal.portions),
                                    theme.TextRole.ACTION,
                                    color="#000000",
                                    max_lines=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        theme.text(
                            meal.name_line,
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=0,
                    tight=True,
                )
            )
        order_controls.append(
            ft.Column(meal_rows, spacing=theme.SPACING["xs"], tight=True)
        )
        order_controls.append(ft.Divider(height=1, color=theme.COLORS["border"]))
        order_controls.append(
            ft.Row(
                [
                    theme.text("Celkem", theme.TextRole.ACTION, expand=True),
                    theme.text(
                        portions_cs(overview.total_portions),
                        theme.TextRole.ACTION,
                        color="#000000",
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    return _home_stack([header_block, _home_block(order_controls)])


def _home_block(controls: list[ft.Control]) -> ft.Container:
    """Jeden HOME blok – do budoucna se skládá více vedle sebe ve stacku."""

    return ft.Container(
        content=ft.Column(controls, spacing=theme.SPACING["xs"], tight=True),
        width=HOME_CONTENT_WIDTH,
        bgcolor=theme.COLORS["surface"],
        border=ft.border.all(
            theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
        ),
        border_radius=6,
        padding=theme.SPACING["md"],
        alignment=ft.alignment.top_left,
    )


def _home_stack(blocks: list[ft.Control]) -> ft.Control:
    return ft.Column(
        blocks,
        spacing=HOME_BLOCK_GAP,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.START,
    )
