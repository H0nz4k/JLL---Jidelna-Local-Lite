"""Setup probe načítá katalog kategorií z public.kategor."""

from __future__ import annotations

from pathlib import Path

import jll.setup_probe as setup_probe


def test_setup_probe_categories_come_from_kategor_not_stravnik_distinct() -> None:
    source = Path(setup_probe.__file__).read_text(encoding="utf-8")
    assert "FROM public.kategor" in source
    assert "DISTINCT btrim(s.kategorie)" not in source
    assert "def list_category_options" in source
    fn = source[source.index("def list_category_options") :]
    block = fn.split("def probe_lab_database")[0]
    assert "FROM public.kategor" in block
    assert "DISTINCT" not in block
