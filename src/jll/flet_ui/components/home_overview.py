"""HOME / Dnešní objednávky – Flet panel (read-only)."""

from __future__ import annotations

import flet as ft

from ...read_models import HomeTodayOverview, portions_cs
from .. import theme

HOME_CONTENT_WIDTH = 780


def build_home_overview(
    overview: HomeTodayOverview | None,
    *,
    error: str | None = None,
    on_retry=None,
) -> ft.Control:
    """Content-driven HOME panel podle návrhu 0.5.0."""

    controls: list[ft.Control] = []
    if error:
        controls.extend(
            [
                theme.text(
                    "Dnešní objednávky se nepodařilo načíst.",
                    theme.TextRole.BODY,
                    color=theme.COLORS["danger"],
                ),
                theme.text(error, theme.TextRole.META, color=theme.COLORS["text_secondary"]),
            ]
        )
        if on_retry is not None:
            controls.append(
                ft.OutlinedButton(
                    "Zkusit znovu", style=theme.button_style(), on_click=on_retry
                )
            )
        return _card(controls)

    if overview is None:
        controls.append(
            theme.text(
                "Načítám dnešní objednávky…",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            )
        )
        return _card(controls)

    place = f"{overview.organization_name} · {overview.workplace_name}"
    header_color = theme.COLORS["text_secondary"]
    controls.append(
        ft.Row(
            [
                theme.text(
                    place,
                    theme.TextRole.PRIMARY,
                    color=header_color,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                ),
                ft.Container(expand=True),
                theme.text(
                    overview.date_label,
                    theme.TextRole.PRIMARY,
                    color=header_color,
                    max_lines=1,
                ),
            ],
            spacing=theme.SPACING["md"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    )

    if not overview.is_cooking_day:
        controls.append(
            theme.text("Dnes se nevaří.", theme.TextRole.BODY)
        )
        if overview.next_cooking_day is not None:
            nxt = overview.next_cooking_day
            from ...read_models import BusinessCalendar

            weekday = BusinessCalendar._WEEKDAYS[nxt.weekday()]
            month = BusinessCalendar._MONTHS[nxt.month]
            titled = weekday[:1].upper() + weekday[1:]
            controls.append(
                theme.text(
                    f"Další varný den: {titled.lower()} {nxt.day}. {month} {nxt.year}",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
        return _card(controls)

    controls.append(ft.Container(height=theme.SPACING["sm"]))
    controls.append(theme.text("DNEŠNÍ OBJEDNÁVKY", theme.TextRole.ACTION))

    if not overview.meals:
        controls.append(
            theme.text(
                "Dnes nejsou žádné objednané porce.",
                theme.TextRole.BODY,
                color=theme.COLORS["text_secondary"],
            )
        )
        return _card(controls)

    for meal in overview.meals:
        controls.append(
            ft.Row(
                [
                    theme.text(meal.title_line, theme.TextRole.BODY),
                    ft.Container(expand=True),
                    theme.text(portions_cs(meal.portions), theme.TextRole.BODY),
                ],
                spacing=theme.SPACING["sm"],
                tight=True,
            )
        )
        controls.append(
            theme.text(
                meal.name_line,
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            )
        )
        controls.append(ft.Container(height=theme.SPACING["sm"]))

    controls.append(ft.Divider(height=1, color=theme.COLORS["border"]))
    controls.append(
        ft.Row(
            [
                theme.text("Celkem", theme.TextRole.ACTION),
                ft.Container(expand=True),
                theme.text(
                    portions_cs(overview.total_portions), theme.TextRole.ACTION
                ),
            ],
            tight=True,
        )
    )
    return _card(controls)


def _card(controls: list[ft.Control]) -> ft.Container:
    return ft.Container(
        content=ft.Column(controls, spacing=4, tight=True, scroll=ft.ScrollMode.AUTO),
        width=HOME_CONTENT_WIDTH,
        bgcolor=theme.COLORS["surface"],
        border=ft.border.all(
            theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
        ),
        border_radius=6,
        padding=theme.SPACING["md"],
        alignment=ft.alignment.top_left,
    )
