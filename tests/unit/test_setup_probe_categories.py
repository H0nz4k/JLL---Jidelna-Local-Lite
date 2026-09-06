"""Setup probe načítá katalog kategorií z public.kategor."""

from __future__ import annotations

from pathlib import Path

import jll.setup_probe as setup_probe


def test_setup_probe_categories_come_from_kategor_not_stravnik_distinct() -> None:
    source = Path(setup_probe.__file__).read_text(encoding="utf-8")
    assert "FROM public.kategor" in source
    assert "DISTINCT btrim(s.kategorie)" not in source
    kategor_block = source[source.index("category_rows") :]
    assert "FROM public.kategor" in kategor_block
    assert "DISTINCT" not in kategor_block.split("category_options")[0]
