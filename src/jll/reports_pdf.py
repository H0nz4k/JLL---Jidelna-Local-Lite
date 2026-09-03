"""Tiskový PDF výstup denní sestavy.

`reportlab` je volitelná lokální závislost, proto se importuje až při
skutečném exportu. Font se hledá v systému; žádný binární asset se do
repozitáře nekopíruje, aby nebyla nutná kontrola licence bez potřeby.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .read_models import DailyReport
from .reports import group_by_category, norm_matrices, sort_named_rows

FONT_ENV_VARIABLE = "JLL_REPORT_FONT"
FONT_NAME = "JllReport"
BOLD_FONT_NAME = "JllReport-Bold"

#: Kandidáti s doloženou podporou české diakritiky v TrueType.
FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
)

MISSING_LIBRARY_TEXT = (
    "PDF export vyžaduje lokální balíček reportlab. Nainstalujte jej "
    "příkazem 'python -m pip install \"jidelna-local-lite[pdf]\"' nebo "
    "'python -m pip install reportlab'."
)

MISSING_FONT_TEXT = (
    "Pro české PDF chybí TrueType font. Nastavte cestu k fontu v "
    f"proměnné {FONT_ENV_VARIABLE}."
)


class PdfDependencyMissing(RuntimeError):
    """Chybí volitelná závislost nebo font, ne chyba dat sestavy."""


def resolve_report_fonts() -> tuple[Path, Path]:
    """Najde regular a bold font pro sestavu.

    Vlastní font uživatele má přednost; bez bold varianty se použije
    regular, aby export neselhal jen kvůli chybějícímu řezu.
    """

    override = os.environ.get(FONT_ENV_VARIABLE)
    if override:
        regular = Path(override)
        if not regular.is_file():
            raise PdfDependencyMissing(
                f"Font z {FONT_ENV_VARIABLE} neexistuje: {regular}"
            )
        bold = regular.with_name(
            regular.stem + "-Bold" + regular.suffix
        )
        return regular, bold if bold.is_file() else regular
    for regular_name, bold_name in FONT_CANDIDATES:
        regular = Path(regular_name)
        if not regular.is_file():
            continue
        bold = Path(bold_name)
        return regular, bold if bold.is_file() else regular
    raise PdfDependencyMissing(MISSING_FONT_TEXT)


def create_report_pdf(
    report: DailyReport,
    output_path: str | Path,
    *,
    grouped: bool = False,
    category_order: Sequence[str] = (),
) -> Path:
    """Vytvoří tiskovou sestavu a vrátí cestu k hotovému PDF.

    Zapisuje se přes dočasný soubor, takže nedokončený export nikdy
    nepřepíše dřívější platný výstup.
    """

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            LongTable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - závislost je volitelná
        raise PdfDependencyMissing(MISSING_LIBRARY_TEXT) from exc

    regular_font, bold_font = resolve_report_fonts()
    registered = pdfmetrics.getRegisteredFontNames()
    if FONT_NAME not in registered:
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(regular_font)))
    if BOLD_FONT_NAME not in registered:
        pdfmetrics.registerFont(TTFont(BOLD_FONT_NAME, str(bold_font)))

    target = Path(output_path).resolve()
    if target.suffix.lower() != ".pdf":
        raise ValueError("Výstupní soubor musí mít příponu .pdf.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.tmp.pdf")

    accent = colors.HexColor("#1f4f72")
    border = colors.HexColor("#d7dee5")
    stripe = colors.HexColor("#f4f6f8")

    body = ParagraphStyle(
        "Body",
        fontName=FONT_NAME,
        fontSize=7.6,
        leading=9.6,
    )
    header_cell = ParagraphStyle(
        "HeaderCell",
        parent=body,
        fontName=BOLD_FONT_NAME,
        textColor=colors.white,
    )
    title = ParagraphStyle(
        "Title",
        parent=body,
        fontName=BOLD_FONT_NAME,
        fontSize=16,
        leading=20,
        textColor=accent,
        spaceAfter=3 * mm,
    )
    section = ParagraphStyle(
        "Section",
        parent=body,
        fontName=BOLD_FONT_NAME,
        fontSize=11,
        leading=14,
        textColor=accent,
        spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
        keepWithNext=True,
    )

    page_size = landscape(A4)
    page_width, page_height = page_size
    margin = 12 * mm
    usable_width = page_width - 2 * margin
    subject = report.subject_name or "Stravovací provoz"
    date_text = report.target_date.strftime("%d.%m.%Y")

    def paragraph(value: object, style: Any = body) -> Any:
        text = (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return Paragraph(text, style)

    def table(
        headers: Sequence[str],
        rows: Sequence[Sequence[object]],
        widths: Sequence[float],
    ) -> Any:
        data = [[paragraph(item, header_cell) for item in headers]]
        data.extend(
            [paragraph(value) for value in row] for row in rows
        )
        return LongTable(
            data,
            colWidths=list(widths),
            repeatRows=1,
            splitByRow=1,
            hAlign="LEFT",
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), accent),
                    ("GRID", (0, 0), (-1, -1), 0.3, border),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
                ]
            ),
        )

    def decorate(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(FONT_NAME, 7.5)
        canvas.setFillColor(colors.HexColor("#5b6b7a"))
        canvas.drawString(margin, page_height - 8 * mm, subject)
        canvas.drawRightString(
            page_width - margin,
            page_height - 8 * mm,
            f"Objednaná strava – {date_text}",
        )
        canvas.drawCentredString(
            page_width / 2,
            6 * mm,
            f"Strana {document.page}",
        )
        canvas.setStrokeColor(border)
        canvas.line(
            margin,
            page_height - 10 * mm,
            page_width - margin,
            page_height - 10 * mm,
        )
        canvas.restoreState()

    story: list[Any] = [
        paragraph(subject, title),
        paragraph(
            f"Jmenný seznam objednané stravy · den {date_text} · "
            f"celkem porcí {report.total_portions} · "
            f"objednávek {report.total_orders}",
            body,
        ),
        Spacer(1, 3 * mm),
        paragraph("Jídelníček a počty porcí", section),
    ]
    if report.menus:
        story.append(
            table(
                ("Typ stravy", "Menu", "Počet", "Název jídla"),
                [
                    (
                        row.meal_type,
                        row.menu,
                        row.portions,
                        row.meal_name or "[název v jídelníčku nenalezen]",
                    )
                    for row in report.menus
                ],
                (
                    usable_width * 0.18,
                    usable_width * 0.08,
                    usable_width * 0.08,
                    usable_width * 0.66,
                ),
            )
        )
    else:
        story.append(paragraph("Nenalezeny žádné objednávky."))

    if report.categories:
        story.append(paragraph("Přihlášky podle kategorií", section))
        story.append(
            table(
                ("Kategorie", "Název", "Norma", "Objednávek"),
                [
                    (
                        row.category,
                        row.category_name or "[bez názvu]",
                        row.norm or "[bez normy]",
                        row.orders,
                    )
                    for row in report.categories
                ],
                (
                    usable_width * 0.16,
                    usable_width * 0.5,
                    usable_width * 0.14,
                    usable_width * 0.2,
                ),
            )
        )

    matrices = norm_matrices(report.norms)
    if matrices:
        story.append(paragraph("Objednaná menu podle norem", section))
        for matrix in matrices:
            story.append(paragraph(f"Typ stravy: {matrix.meal_type}"))
            headers = (
                "Norma",
                *(f"Menu {menu}" for menu in matrix.menus),
                "Celkem",
            )
            rows = [
                (
                    norm,
                    *(matrix.portions(norm, menu) for menu in matrix.menus),
                    matrix.norm_total(norm),
                )
                for norm in matrix.norms
            ]
            column_width = usable_width / max(1, len(headers))
            story.append(
                table(headers, rows, [column_width] * len(headers))
            )
            story.append(Spacer(1, 2 * mm))

    story.extend([PageBreak(), paragraph("Jmenný seznam strávníků", section)])
    named_headers = (
        "Jméno",
        "Kategorie",
        "Typ stravy",
        "Menu",
        "Norma",
        "Objednané jídlo",
    )
    named_widths = (
        usable_width * 0.2,
        usable_width * 0.16,
        usable_width * 0.12,
        usable_width * 0.07,
        usable_width * 0.07,
        usable_width * 0.38,
    )

    def named_rows(rows: Sequence[Any]) -> list[tuple[object, ...]]:
        return [
            (
                row.name,
                row.category_label,
                row.meal_type,
                row.menu,
                row.norm_label,
                row.meal_label,
            )
            for row in rows
        ]

    if not report.diners:
        story.append(paragraph("Pro tento den nejsou žádné objednávky."))
    elif grouped:
        for block in group_by_category(report.diners, category_order):
            story.append(
                paragraph(f"{block.label} ({len(block.rows)})", section)
            )
            story.append(
                table(named_headers, named_rows(block.rows), named_widths)
            )
            story.append(Spacer(1, 2.5 * mm))
    else:
        story.append(
            table(
                named_headers,
                named_rows(sort_named_rows(report.diners)),
                named_widths,
            )
        )

    document = SimpleDocTemplate(
        str(temporary),
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=14 * mm,
        bottomMargin=12 * mm,
        title=f"Objednaná strava {date_text}",
        author=subject,
    )
    try:
        document.build(story, onFirstPage=decorate, onLaterPages=decorate)
        if temporary.stat().st_size <= 0:
            raise RuntimeError("Vytvořené PDF je prázdné.")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
