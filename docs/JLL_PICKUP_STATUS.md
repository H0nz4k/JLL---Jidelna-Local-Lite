# JLL Stav výdeje – read-only LAB modul

Stav: **IMPLEMENTOVÁNO jako LAB full-day preview; business kontrakt PARTIAL**

Modul pouze zobrazuje agregovaný stav. Samotný výdej ani volání
`zapis_odber` neimplementuje.

Pro vybraný den načítá v jednom scopeovaném dotazu:

- typ stravy a menu;
- `objednáno` z číselných denních markerů `public.prihlas.dXX`;
- `vydáno` z odpovídajícího znaku `O` v `public.odebral.odebral`;
- `zbývá = objednáno - vydáno`.

Vazba `odebral` používá strávníka, rok, měsíc, normalizovaný typ stravy a
`poradiprihl`, stejně jako referenční `RucniOdberStrav`. Počty používají
`DISTINCT p.id`, aby případná duplicita výdejního řádku nenásobila přihlášky.

Modul vědomě zobrazuje celodenní stav z `prihlas`/`odebral`. Neomezuje se na
aktuální `typstrav.vydejod/vydejdo` a nefiltruje přes výdejní `relace`.
Per-strávník interpretace `O = vydáno` je doložená, ale autoritativní DEMO
agregace „celý den vs. aktivní výdejní okno“ ve zdrojích není. GUI proto
výsledek prezentuje jako read-only LAB stav, nikoli jako účetní uzávěrku.

GUI zobrazuje každý řádek jako samostatný panel, ve kterém je `ZBÝVÁ`
dominantní hodnota (typografická role `PRIMARY` z FÁZE 3C); objednáno a
vydáno zůstávají jako kontext v roli `META`. Dokončený řádek (`zbývá <= 0`)
dostane přes centrální theme zelené pozadí a akcent, takže hospodářka pozná
hotový výdej bez čtení čísel. Panel je pouze pro čtení a nemá vlastní QSS.

Backend před otevřením DB vyžaduje `pickup_status.view`. Každý dotaz spojuje
`prihlas` se `stravnik` a omezuje `s.kategorie =
ANY(effective_allowed_categories)`. GUI načítá data přes worker thread a
neobsahuje business SQL.

Omezení: jde o stav podle `odebral` kontraktu, nikoli o nový autoritativní
write protokol. Modul neřeší produkční mixed-writer blocker.
