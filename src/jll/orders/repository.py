from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection, sql
from psycopg.rows import dict_row

from .errors import ErrorCode, OrderBusinessError
from .models import Diner, MealType, OrderCommand, OrderRow, Transition
from .preflight import decimal_from_db

DAY_COLUMNS = tuple(f"d{day:02d}" for day in range(1, 32))

CONFIG_LOCK_SQL = """
LOCK TABLE
  public.cenik,
  public.jidelnicek,
  public.kategor,
  public.menustravy,
  public.parametry,
  public.sazby,
  public.signaly,
  public.slozky_ceny,
  public.stravobv,
  public.typstrav,
  public.typstrj,
  public.varnedny
IN SHARE MODE
"""


class OrderRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def _fetchone(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] = (),
    ) -> Mapping[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def _fetchall(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] = (),
    ) -> list[Mapping[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())

    def configure_transaction(
        self,
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
        business_timezone: str,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cursor.execute(
                "SELECT set_config('lock_timeout', %s, true)",
                (f"{lock_timeout_ms}ms",),
            )
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{statement_timeout_ms}ms",),
            )
            cursor.execute(
                "SELECT set_config('TimeZone', %s, true)",
                (business_timezone,),
            )
            cursor.execute("SELECT current_setting('TimeZone')")
            timezone_row = cursor.fetchone()
            if timezone_row is None or timezone_row[0] != business_timezone:
                raise OrderBusinessError(
                    ErrorCode.DEADLINE_EXPIRED,
                    "Databázovou business časovou zónu nelze bezpečně nastavit.",
                )

    def lab_identity(self) -> Mapping[str, Any]:
        row = self._fetchone(
            """
            SELECT
                current_database() AS database_name,
                host(inet_server_addr()) AS server_address,
                inet_server_port() AS server_port,
                (SELECT system_identifier::text FROM pg_control_system())
                    AS system_identifier,
                version() AS server_version
            """
        )
        if row is None:
            raise OrderBusinessError(
                ErrorCode.LAB_GUARD_FAILED,
                "Lokální LAB databázi nelze ověřit.",
            )
        return row

    def acquire_month_lock(self, key: int) -> None:
        self._fetchone("SELECT pg_advisory_xact_lock(%s) AS locked", (key,))

    def lock_configuration(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(CONFIG_LOCK_SQL)

    def lock_diner(self, command: OrderCommand) -> Diner:
        rows = self._fetchall(
            """
            SELECT
                s.evidcislo,
                s.kategorie,
                s.hromadny,
                s.preplatekmm,
                s.platittm,
                s.platitpm,
                s.platbatm,
                s.platbabm
            FROM public.stravnik AS s
            WHERE s.evidcislo = %s
              AND s.kategorie = ANY(%s::varchar[])
              AND s.stav = 'A'
              AND COALESCE(s.deleted, false) = false
            FOR UPDATE
            """,
            (command.evidcislo, sorted(command.allowed_categories)),
        )
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Strávník není pro tuto provozovnu dostupný.",
            )
        row = rows[0]
        diner = Diner(
            evidcislo=int(row["evidcislo"]),
            kategorie=str(row["kategorie"]),
            hromadny=bool(row["hromadny"]),
            preplatekmm=row["preplatekmm"],
            platittm=row["platittm"],
            platitpm=row["platitpm"],
            platbatm=row["platbatm"],
            platbabm=row["platbabm"],
        )
        if diner.hromadny:
            raise OrderBusinessError(
                ErrorCode.HOUSEHOLD_ACCOUNT_UNSUPPORTED,
                "Hromadný strávník není v LAB objednávkové službě podporován.",
            )
        return diner

    def assert_scope(self, command: OrderCommand) -> Diner:
        row = self._fetchone(
            """
            SELECT
                s.evidcislo,
                s.kategorie,
                s.hromadny,
                s.preplatekmm,
                s.platittm,
                s.platitpm,
                s.platbatm,
                s.platbabm
            FROM public.stravnik AS s
            WHERE s.evidcislo = %s
              AND s.kategorie = ANY(%s::varchar[])
              AND s.stav = 'A'
              AND COALESCE(s.deleted, false) = false
              AND s.hromadny IS NOT TRUE
            """,
            (command.evidcislo, sorted(command.allowed_categories)),
        )
        if row is None:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Strávník není pro tuto provozovnu dostupný.",
            )
        return Diner(
            evidcislo=int(row["evidcislo"]),
            kategorie=str(row["kategorie"]),
            hromadny=False,
            preplatekmm=row["preplatekmm"],
            platittm=row["platittm"],
            platitpm=row["platitpm"],
            platbatm=row["platbatm"],
            platbabm=row["platbabm"],
        )

    def assert_ordering_open(self) -> None:
        rows = self._fetchall(
            """
            SELECT hodnota
            FROM public.signaly
            WHERE nazev = 'UZAVERKA'
            FOR SHARE
            """
        )
        if len(rows) != 1 or rows[0]["hodnota"] is None:
            raise OrderBusinessError(
                ErrorCode.ORDERING_CLOSED,
                "Stav uzávěrky nelze bezpečně určit.",
            )
        if str(rows[0]["hodnota"]).strip() == "A":
            raise OrderBusinessError(
                ErrorCode.ORDERING_CLOSED,
                "Během uzávěrky nelze měnit objednávky.",
            )

    def use_pricelist(self) -> bool:
        rows = self._fetchall(
            """
            SELECT hodnota
            FROM public.parametry
            WHERE sekce = 'BACKUP'
              AND parametr = 'PouzivatCenik'
            FOR SHARE
            """
        )
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "Cenový režim nelze bezpečně určit.",
            )
        raw_value = str(rows[0]["hodnota"] or "").strip()
        if raw_value not in {"0", "1"}:
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "Cenový režim má neplatnou hodnotu.",
            )
        function_row = self._fetchone("SELECT public.pouzivatcenik() AS value")
        if (
            function_row is None
            or function_row["value"] is None
            or bool(function_row["value"]) != (raw_value == "1")
        ):
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "Cenový parametr a DB business funkce se neshodují.",
            )
        return raw_value == "1"

    @staticmethod
    def _meal_type(row: Mapping[str, Any]) -> MealType:
        return MealType(
            typstravy=str(row["typstravy"]).strip(),
            kod=str(row["kod"]).strip(),
            prihlasdo=row["prihlasdo"],
            prihlasdnu=row["prihlasdnu"],
            menudo=row["menudo"],
            menudnu=row["menudnu"],
            odhlasdo=row["odhlasdo"],
            odhlasdnu=row["odhlasdnu"],
            spolecnes=(
                str(row["spolecnes"]).strip() if row["spolecnes"] else None
            ),
            vyloucenos=(
                str(row["vyloucenos"]).strip() if row["vyloucenos"] else None
            ),
        )

    def get_meal_type(self, typstravy: str) -> MealType:
        rows = self._fetchall(
            """
            SELECT
                typstravy,
                kod,
                prihlasdo,
                prihlasdnu,
                menudo,
                menudnu,
                odhlasdo,
                odhlasdnu,
                spolecnes,
                vyloucenos
            FROM public.typstrav
            WHERE typstravy = %s
              AND typsluzby = 'strava'
              AND pouzivatpcbox = true
            FOR SHARE
            """,
            (typstravy,),
        )
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Typ stravy není bezpečně dostupný.",
            )
        return self._meal_type(rows[0])

    def get_related_types(self, codes: Iterable[str]) -> dict[str, MealType]:
        wanted = sorted(set(codes))
        if not wanted:
            return {}
        rows = self._fetchall(
            """
            SELECT
                typstravy,
                kod,
                prihlasdo,
                prihlasdnu,
                menudo,
                menudnu,
                odhlasdo,
                odhlasdnu,
                spolecnes,
                vyloucenos
            FROM public.typstrav
            WHERE kod = ANY(%s::varchar[])
              AND typsluzby = 'strava'
              AND pouzivatpcbox = true
            ORDER BY kod, typstravy
            FOR SHARE
            """,
            (wanted,),
        )
        result: dict[str, MealType] = {}
        for raw in rows:
            item = self._meal_type(raw)
            if item.kod in result:
                raise OrderBusinessError(
                    ErrorCode.RELATION_CONFIG_INVALID,
                    "Vztahový kód typu stravy není jednoznačný.",
                )
            result[item.kod] = item
        if set(result) != set(wanted):
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Související typ stravy nebyl nalezen.",
            )
        return result

    def get_category_limit(self, category: str) -> Any:
        rows = self._fetchall(
            """
            SELECT limitprihlasky
            FROM public.kategor
            WHERE oznaceni = %s
            FOR SHARE
            """,
            (category,),
        )
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.CREDIT_DATA_INVALID,
                "Kategorie strávníka nebyla nalezena.",
            )
        return rows[0]["limitprihlasky"]

    def get_server_now(self) -> datetime:
        row = self._fetchone("SELECT clock_timestamp() AS value")
        if row is None or not isinstance(row["value"], datetime):
            raise OrderBusinessError(
                ErrorCode.DEADLINE_EXPIRED,
                "Serverový čas nelze bezpečně určit.",
            )
        return row["value"]

    def get_calendar(
        self,
        typstravy: str,
        year: int,
        month: int,
    ) -> dict[int, bool] | None:
        identifiers = sql.SQL(", ").join(sql.Identifier(value) for value in DAY_COLUMNS)
        query = sql.SQL(
            """
            SELECT {days}
            FROM public.varnedny
            WHERE typsluzby = %s
              AND rok = %s
              AND mesic = %s
            FOR SHARE
            """
        ).format(days=identifiers)
        rows = self._fetchall(query, (typstravy, year, month))
        if not rows:
            return None
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Kalendář varných dnů není jednoznačný.",
            )
        return {
            day: str(rows[0][f"d{day:02d}"] or "").strip() == "A"
            for day in range(1, 32)
        }

    def exact_menu_available(
        self,
        target: date,
        typstravy: str,
        menu: int,
    ) -> bool:
        row = self._fetchone(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.jidelnicek AS j
                JOIN public.menustravy AS m
                  ON m.id = j.idmenustravy
                 AND m.typstravy = j.typstravy
                JOIN public.typstrj AS t ON t.id = m.idtypstrj
                WHERE j.datum = %s
                  AND j.typstravy = %s
                  AND j.jazyk = 'česky'
                  AND j.zverejneny = true
                  AND j.cislojidelnicku = 1
                  AND t.oznaceni = %s
            ) AS value
            """,
            (target, typstravy, str(menu)),
        )
        return bool(row and row["value"])

    def active_rate(
        self,
        category: str,
        typstravy: str,
        target: date,
    ) -> Mapping[str, Any]:
        rows = self._fetchall(
            """
            SELECT sazba, pocetmenu, dotace, fksp
            FROM public.sazby
            WHERE kategorie = %s
              AND typstravy = %s
              AND platnostod <= %s
              AND platnostdo >= %s
            ORDER BY platnostod
            FOR SHARE
            """,
            (category, typstravy, target, target),
        )
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "Platná sazba není jednoznačná.",
            )
        return rows[0]

    def rate_price(self, category: str, typstravy: str, target: date) -> Any:
        row = self._fetchone(
            "SELECT public.dej_sazbu(%s, %s, %s) AS value",
            (category, typstravy, target.strftime("%d%m%Y")),
        )
        return None if row is None else row["value"]

    def write_path_price(
        self,
        category: str,
        typstravy: str,
        target: date,
        menu: int,
    ) -> tuple[Any, bool]:
        row = self._fetchone(
            """
            SELECT cena, ok
            FROM public.getcenamenuden(%s, %s, %s, %s, %s, %s)
            """,
            (
                typstravy,
                category,
                target.year,
                target.month,
                target.day,
                menu,
            ),
        )
        if row is None:
            return None, False
        return row["cena"], bool(row["ok"])

    def assert_zero_subsidy(
        self,
        category: str,
        typstravy: str,
        target: date,
        menu: int,
    ) -> None:
        rows = self._fetchall(
            """
            SELECT c.dotace, c.fksp
            FROM public.cenik AS c
            JOIN public.typstrav AS t ON t.kod = c.kod_stravy
            WHERE t.typstravy = %s
              AND c.kategorie = %s
              AND c.rok = %s
              AND c.mesic = %s
              AND c.den = %s
              AND c.menu = %s
            FOR SHARE OF c
            """,
            (
                typstravy,
                category,
                target.year,
                target.month,
                target.day,
                menu,
            ),
        )
        if not rows:
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "Pro menu chybí materializovaná cena.",
            )
        for row in rows:
            dotace = decimal_from_db(
                row["dotace"],
                field="cenik.dotace",
                null_is_zero=True,
                error_code=ErrorCode.PRICE_INVALID,
            )
            fksp = decimal_from_db(
                row["fksp"],
                field="cenik.fksp",
                null_is_zero=True,
                error_code=ErrorCode.PRICE_INVALID,
            )
            if dotace != 0 or fksp != 0:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "Nenulová dotace není v LAB pilotu podporována.",
                )

    def lock_order_rows(
        self,
        command: OrderCommand,
        meal_types: Iterable[str],
    ) -> dict[str, OrderRow]:
        return self._order_rows(command, meal_types, for_update=True)

    def read_order_rows(
        self,
        command: OrderCommand,
        meal_types: Iterable[str],
    ) -> dict[str, OrderRow]:
        return self._order_rows(command, meal_types, for_update=False)

    def _order_rows(
        self,
        command: OrderCommand,
        meal_types: Iterable[str],
        *,
        for_update: bool,
    ) -> dict[str, OrderRow]:
        types = sorted(set(meal_types))
        day_column = sql.Identifier(f"d{command.datum.day:02d}")
        query = sql.SQL(
            """
            SELECT
                stravnik,
                typsluzby,
                rok,
                mesic,
                poradiprihl,
                {day_column} AS state,
                cena,
                pocet
            FROM public.prihlas
            WHERE stravnik = %s
              AND rok = %s
              AND mesic = %s
              AND typsluzby = ANY(%s::varchar[])
            ORDER BY typsluzby, poradiprihl
            {lock_clause}
            """
        ).format(
            day_column=day_column,
            lock_clause=sql.SQL("FOR UPDATE") if for_update else sql.SQL(""),
        )
        rows = self._fetchall(
            query,
            (
                command.evidcislo,
                command.datum.year,
                command.datum.month,
                types,
            ),
        )
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["typsluzby"]).strip(), []).append(row)
        ambiguous = [name for name, items in grouped.items() if len(items) != 1]
        if ambiguous:
            raise OrderBusinessError(
                ErrorCode.AMBIGUOUS_ORDER_ROW,
                "Měsíční přihláška není jednoznačná.",
                context={"types": sorted(ambiguous)},
            )
        result: dict[str, OrderRow] = {}
        for name, items in grouped.items():
            raw = items[0]
            if raw["pocet"] is None:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "prihlas.pocet nesmí být NULL.",
                )
            try:
                count = int(raw["pocet"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "prihlas.pocet není platné celé číslo.",
                ) from exc
            if count < 0:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "prihlas.pocet nesmí být záporný.",
                )
            result[name] = OrderRow(
                stravnik=int(raw["stravnik"]),
                typsluzby=name,
                rok=int(raw["rok"]),
                mesic=int(raw["mesic"]),
                poradiprihl=int(raw["poradiprihl"]),
                state=(
                    str(raw["state"]).strip() if raw["state"] is not None else None
                ),
                cena=decimal_from_db(
                    raw["cena"],
                    field="prihlas.cena",
                    null_is_zero=False,
                    error_code=ErrorCode.POSTCONDITION_FAILED,
                ),
                pocet=count,
            )
        return result

    def call_plus(self, command: OrderCommand, transition: Transition) -> Any:
        row = self._fetchone(
            """
            SELECT public.objednavka_plus(%s, %s, %s, %s, %s, %s) AS result
            """,
            (
                command.datum.year,
                command.datum.month,
                command.datum.day,
                transition.after_state,
                command.evidcislo,
                transition.typstravy,
            ),
        )
        return None if row is None else row["result"]

    def call_minus(self, command: OrderCommand, transition: Transition) -> Any:
        row = self._fetchone(
            """
            SELECT public.objednavka_minus(%s, %s, %s, %s, %s, %s) AS result
            """,
            (
                command.datum.year,
                command.datum.month,
                command.datum.day,
                transition.before_state,
                command.evidcislo,
                transition.typstravy,
            ),
        )
        return None if row is None else row["result"]

    def penden_aggregate(
        self,
        command: OrderCommand,
        meal_types: Iterable[str],
    ) -> dict[str, tuple[Decimal, int]]:
        rows = self._fetchall(
            """
            SELECT
                typstravy,
                COALESCE(SUM(castka), 0) AS amount,
                COUNT(*) AS count
            FROM public.penden
            WHERE evidcislo = %s
              AND rok = %s
              AND mesic = %s
              AND typ = 'R'
              AND typstravy = ANY(%s::varchar[])
            GROUP BY typstravy
            """,
            (
                command.evidcislo,
                command.datum.year,
                command.datum.month,
                sorted(set(meal_types)),
            ),
        )
        return {
            str(row["typstravy"]): (
                decimal_from_db(
                    row["amount"],
                    field="penden.castka",
                    null_is_zero=True,
                    error_code=ErrorCode.POSTCONDITION_FAILED,
                ),
                int(row["count"]),
            )
            for row in rows
        }

    def insert_audit(
        self,
        command: OrderCommand,
        transition: Transition,
        *,
        note: str,
        price: int | None,
    ) -> bool:
        row = self._fetchone(
            """
            SELECT public.insert_udalost(
                %s,
                'Přihláška',
                'P',
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            ) AS result
            """,
            (
                command.actor,
                note,
                command.client_version,
                command.evidcislo,
                command.datum.strftime("%d%m%Y"),
                price,
                transition.typstravy,
            ),
        )
        return bool(row and row["result"] is True)
