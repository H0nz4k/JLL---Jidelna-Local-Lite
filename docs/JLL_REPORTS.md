# JLL Sestavy – read-only foundation

Stav: **IMPLEMENTOVÁNO jako GUI preview**

Sekce **Sestavy** vyžaduje `reports.view` a poskytuje:

- souhrn přihlášek pro datum: typ stravy, menu, počet a název jídla;
- seznam aktivních nesmazaných strávníků: jméno, kategorie, třída a
  evidenční číslo.

Oba backend dotazy vždy aplikují efektivní `allowed_categories`.
Přihlášky používají číselný marker `1..9` v příslušném `dXX`; názvy jídel
jsou dávkově agregované z publikovaného českého jídelníčku číslo 1. Seznam
strávníků fail-closed skončí chybou nad 5000 řádků namísto tichého
oříznutí.

GUI provede oba dotazy mimo GUI thread. Není implementován PDF, tisk ani
export; `reports.print` proto nic nezapíná. Toto omezení brání tomu, aby
první vertikální řez zapisoval potenciálně citlivé soubory mimo aplikaci.
