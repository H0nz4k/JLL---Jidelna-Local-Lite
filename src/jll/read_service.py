from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ContextManager, Iterator

from psycopg import Connection, sql
from psycopg.rows import dict_row

from .lab_guard import assert_lab_identity
from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import Diner, MealType, OrderAction, OrderServiceSettings
from .orders.preflight import (
    assert_deadline,
    calculate_credit,
    deadline_fields,
    decimal_from_db,
)
from .orders.repository import DAY_COLUMNS
from .policy import Permission, SessionPolicy
from .read_models import (
    ActionAvailability,
    DinerDay,
    DinerChip,
    DinerDetail,
    DinerReportRow,
    DinerSummary,
    LabDiagnostics,
    MealDay,
    MenuCapability,
    MenuOption,
    OrderReportRow,
    PickupStatusRow,
)

ConnectionFactory = Callable[
    [], Connection[Any] | ContextManager[Connection[Any]]
]

NORMALIZED_NAME_SQL = sql.SQL(
    "translate(lower(regexp_replace(btrim(s.jmeno), '\\s+', ' ', 'g')), "
    "'áäčďéěëíňóöřšťúůüýž', 'aacdeeeinoorstuuuuyz')"
)


def normalize_search_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


class OrderReadRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def fetchone(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] | Mapping[str, Any] = (),
    ) -> Mapping[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def fetchall(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] | Mapping[str, Any] = (),
    ) -> list[Mapping[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())

    def identity(self) -> Mapping[str, Any]:
        row = self.fetchone(
            """
            SELECT
                current_database() AS database_name,
                host(inet_server_addr()) AS server_address,
                inet_server_port() AS server_port,
                (SELECT system_identifier::text FROM pg_control_system())
                    AS system_identifier
            """
        )
        if row is None:
            raise OrderBusinessError(
                ErrorCode.LAB_GUARD_FAILED,
                "Lokální LAB databázi nelze ověřit.",
            )
        return row

    def configure_read_transaction(self, timezone: str, timeout_ms: int) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{timeout_ms}ms",),
            )
            cursor.execute("SELECT set_config('TimeZone', %s, true)", (timezone,))
            cursor.execute("SELECT current_setting('TimeZone')")
            row = cursor.fetchone()
            if row is None or row[0] != timezone:
                raise OrderBusinessError(
                    ErrorCode.LAB_GUARD_FAILED,
                    "Business časovou zónu nelze bezpečně nastavit.",
                )


class OrderReadService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        settings: OrderServiceSettings,
        policy: SessionPolicy | Callable[[], SessionPolicy],
        *,
        search_limit: int = 30,
    ) -> None:
        if not 1 <= search_limit <= 100:
            raise ValueError("search_limit musí být v rozsahu 1..100.")
        self._connection_factory = connection_factory
        self.settings = settings
        self._policy_provider = (
            policy if callable(policy) else lambda: policy
        )
        self.search_limit = search_limit

    def _scope(self, permission: Permission) -> frozenset[str]:
        policy = self.policy
        policy.require(permission)
        return policy.scope()

    @property
    def policy(self) -> SessionPolicy:
        return self._policy_provider()

    @contextmanager
    def _session(
        self,
    ) -> Iterator[tuple[Connection[Any], OrderReadRepository]]:
        with self._connection_factory() as connection:
            if not connection.autocommit:
                connection.autocommit = True
            repository = OrderReadRepository(connection)
            assert_lab_identity(self.settings, repository.identity())
            yield connection, repository

    def verify_lab(self) -> LabDiagnostics:
        with self._session() as (_connection, repository):
            identity = repository.identity()
            return LabDiagnostics(
                database_name=str(identity["database_name"]),
                server_address=str(identity["server_address"]),
                server_port=int(identity["server_port"]),
                system_identifier=str(identity["system_identifier"]),
                business_timezone=self.settings.business_timezone,
            )

    def server_today(self) -> date:
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                row = repository.fetchone(
                    "SELECT clock_timestamp() AS server_now"
                )
                if row is None or not isinstance(row["server_now"], datetime):
                    raise OrderBusinessError(
                        ErrorCode.LAB_GUARD_FAILED,
                        "Serverové datum nelze bezpečně určit.",
                    )
                return row["server_now"].date()

    def list_diners(self) -> list[DinerSummary]:
        scope = self._scope(Permission.DINERS_VIEW)
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                rows = repository.fetchall(
                    """
                    SELECT s.evidcislo, btrim(s.jmeno) AS name,
                           btrim(s.kategorie) AS category,
                           COALESCE(btrim(s.trida), '') AS class_name
                    FROM public.stravnik AS s
                    WHERE s.stav = 'A'
                      AND COALESCE(s.deleted, false) = false
                      AND s.hromadny IS NOT TRUE
                      AND s.kategorie = ANY(%s::varchar[])
                    ORDER BY lower(btrim(s.jmeno)), s.evidcislo
                    LIMIT %s
                    """,
                    (sorted(scope), self.search_limit),
                )
                return [
                    DinerSummary(
                        evidcislo=int(row["evidcislo"]),
                        name=str(row["name"]),
                        category=str(row["category"]),
                        class_name=str(row["class_name"]),
                    )
                    for row in rows
                ]

    def search_diners(self, text: str) -> list[DinerSummary]:
        normalized = normalize_search_text(text)
        if len(normalized) < 2:
            return []
        tokens = normalized.split()
        scope = self._scope(Permission.DINERS_VIEW)
        token_conditions = sql.SQL(" AND ").join(
            sql.SQL("position({placeholder} in {name}) > 0").format(
                placeholder=sql.Placeholder(f"token{index}"),
                name=NORMALIZED_NAME_SQL,
            )
            for index in range(len(tokens))
        )
        query = sql.SQL(
            """
            SELECT s.evidcislo, btrim(s.jmeno) AS name,
                   btrim(s.kategorie) AS category,
                   COALESCE(btrim(s.trida), '') AS class_name
            FROM public.stravnik AS s
            WHERE s.stav = 'A'
              AND COALESCE(s.deleted, false) = false
              AND s.hromadny IS NOT TRUE
              AND s.kategorie = ANY(%(scope)s::varchar[])
              AND (
                    ({token_conditions})
                    OR s.evidcislo::text = %(query)s
                    OR EXISTS (
                        SELECT 1
                        FROM public.cipy AS c
                        WHERE c.stravnik = s.evidcislo
                          AND lower(btrim(c.cislo)) = %(query)s
                          AND c.stav = 'P'
                    )
              )
            ORDER BY
              CASE
                WHEN s.evidcislo::text = %(query)s THEN 0
                WHEN {name} = %(query)s THEN 1
                WHEN left({name}, length(%(query)s)) = %(query)s THEN 2
                ELSE 3
              END,
              {name},
              s.evidcislo
            LIMIT %(limit)s
            """
        ).format(token_conditions=token_conditions, name=NORMALIZED_NAME_SQL)
        parameters: dict[str, Any] = {
            "scope": sorted(scope),
            "query": normalized,
            "limit": self.search_limit,
            **{f"token{index}": token for index, token in enumerate(tokens)},
        }
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                rows = repository.fetchall(query, parameters)
                return [
                    DinerSummary(
                        evidcislo=int(row["evidcislo"]),
                        name=str(row["name"]),
                        category=str(row["category"]),
                        class_name=str(row["class_name"]),
                    )
                    for row in rows
                ]

    def load_pickup_status(self, target: date) -> list[PickupStatusRow]:
        if not isinstance(target, date):
            raise ValueError("target musí být date.")
        scope = self._scope(Permission.PICKUP_STATUS_VIEW)
        day = sql.Identifier(DAY_COLUMNS[target.day - 1])
        query = sql.SQL(
            """
            SELECT btrim(p.typsluzby) AS meal_type,
                   p.{day}::integer AS menu,
                   count(DISTINCT p.id)::integer AS ordered,
                   count(DISTINCT p.id) FILTER (
                     WHERE COALESCE(substr(o.odebral, %s, 1), '') = 'O'
                   )::integer AS picked_up
            FROM public.prihlas AS p
            JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
            LEFT JOIN public.odebral AS o
              ON o.stravnik = p.stravnik
             AND o.rok = p.rok
             AND o.mesic = p.mesic
             AND lower(btrim(o.typstravy)) = lower(btrim(p.typsluzby))
             AND o.poradiprihl = p.poradiprihl
            WHERE p.rok = %s
              AND p.mesic = %s
              AND p.{day} ~ '^[1-9]$'
              AND s.kategorie = ANY(%s::varchar[])
              AND COALESCE(s.deleted, false) = false
            GROUP BY btrim(p.typsluzby), p.{day}
            ORDER BY btrim(p.typsluzby), p.{day}::integer
            """
        ).format(day=day)
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                rows = repository.fetchall(
                    query,
                    (target.day, target.year, target.month, sorted(scope)),
                )
                return [
                    PickupStatusRow(
                        meal_type=str(row["meal_type"]),
                        menu=int(row["menu"]),
                        ordered=int(row["ordered"]),
                        picked_up=int(row["picked_up"]),
                    )
                    for row in rows
                ]

    def load_order_report(self, target: date) -> list[OrderReportRow]:
        if not isinstance(target, date):
            raise ValueError("target musí být date.")
        scope = self._scope(Permission.REPORTS_VIEW)
        day = sql.Identifier(DAY_COLUMNS[target.day - 1])
        query = sql.SQL(
            """
            WITH orders AS (
              SELECT btrim(p.typsluzby) AS meal_type,
                     p.{day}::integer AS menu,
                     count(*)::integer AS portions
              FROM public.prihlas AS p
              JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
              WHERE p.rok = %s
                AND p.mesic = %s
                AND p.{day} ~ '^[1-9]$'
                AND s.kategorie = ANY(%s::varchar[])
                AND COALESCE(s.deleted, false) = false
              GROUP BY btrim(p.typsluzby), p.{day}
            ),
            meals AS (
              SELECT btrim(j.typstravy) AS meal_type,
                     t.oznaceni::integer AS menu,
                     string_agg(
                       NULLIF(btrim(j.nazev), ''),
                       ' • ' ORDER BY m.caststravy, j.idjidelnicku
                     ) AS meal_name
              FROM public.jidelnicek AS j
              JOIN public.menustravy AS m
                ON m.id = j.idmenustravy AND m.typstravy = j.typstravy
              JOIN public.typstrj AS t ON t.id = m.idtypstrj
              WHERE j.datum = %s
                AND lower(btrim(j.jazyk)) = lower('česky')
                AND j.cislojidelnicku = 1
                AND btrim(t.oznaceni) ~ '^[1-9]$'
              GROUP BY btrim(j.typstravy), t.oznaceni
            )
            SELECT o.meal_type, o.menu, o.portions, m.meal_name
            FROM orders AS o
            LEFT JOIN meals AS m
              ON lower(m.meal_type) = lower(o.meal_type)
             AND m.menu = o.menu
            ORDER BY o.meal_type, o.menu
            """
        ).format(day=day)
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                rows = repository.fetchall(
                    query,
                    (target.year, target.month, sorted(scope), target),
                )
                return [
                    OrderReportRow(
                        meal_type=str(row["meal_type"]),
                        menu=int(row["menu"]),
                        portions=int(row["portions"]),
                        meal_name=(
                            str(row["meal_name"])
                            if row["meal_name"] is not None
                            else None
                        ),
                    )
                    for row in rows
                ]

    def load_diner_report(self) -> list[DinerReportRow]:
        scope = self._scope(Permission.REPORTS_VIEW)
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                rows = repository.fetchall(
                    """
                    SELECT s.evidcislo, btrim(s.jmeno) AS name,
                           btrim(s.kategorie) AS category,
                           COALESCE(btrim(s.trida), '') AS class_name
                    FROM public.stravnik AS s
                    WHERE s.stav = 'A'
                      AND COALESCE(s.deleted, false) = false
                      AND s.kategorie = ANY(%s::varchar[])
                    ORDER BY lower(btrim(s.jmeno)), s.evidcislo
                    LIMIT 5001
                    """,
                    (sorted(scope),),
                )
                if len(rows) > 5000:
                    raise OrderBusinessError(
                        ErrorCode.POSTCONDITION_FAILED,
                        "Náhled sestavy překročil bezpečný limit 5000 řádků.",
                    )
                return [
                    DinerReportRow(
                        evidcislo=int(row["evidcislo"]),
                        name=str(row["name"]),
                        category=str(row["category"]),
                        class_name=str(row["class_name"]),
                    )
                    for row in rows
                ]

    def load_diner_day(self, evidcislo: int, target: date) -> DinerDay:
        if isinstance(evidcislo, bool) or not isinstance(evidcislo, int):
            raise ValueError("evidcislo musí být celé číslo.")
        if not isinstance(target, date):
            raise ValueError("target musí být date.")
        scope = self._scope(Permission.DINERS_VIEW)
        self.policy.require(Permission.ORDERS_VIEW)
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                now_row = repository.fetchone(
                    "SELECT clock_timestamp() AS server_now"
                )
                if now_row is None or not isinstance(
                    now_row["server_now"], datetime
                ):
                    raise OrderBusinessError(
                        ErrorCode.POSTCONDITION_FAILED,
                        "Serverový čas nelze bezpečně načíst.",
                    )
                server_now = now_row["server_now"]
                diner = self._load_diner(repository, evidcislo, scope)
                meals = self._load_meals(
                    repository,
                    diner,
                    target,
                    server_now,
                )
                return DinerDay(diner, target, server_now, meals)

    def _load_diner(
        self,
        repository: OrderReadRepository,
        evidcislo: int,
        scope: frozenset[str],
    ) -> DinerDetail:
        rows = repository.fetchall(
            """
            SELECT evidcislo, btrim(jmeno) AS name,
                   btrim(kategorie) AS category,
                   COALESCE(btrim(trida), '') AS class_name,
                   NULLIF(btrim(cip), '') AS chip_number,
                   hromadny, preplatekmm, platittm, platitpm, platbatm, platbabm
            FROM public.stravnik
            WHERE evidcislo = %s
              AND kategorie = ANY(%s::varchar[])
              AND stav = 'A'
              AND COALESCE(deleted, false) = false
              AND hromadny IS NOT TRUE
            """,
            (evidcislo, sorted(scope)),
        )
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Strávník není pro tuto LAB provozovnu dostupný.",
            )
        row = rows[0]
        chips: tuple[DinerChip, ...] = ()
        if Permission.CHIPS_VIEW in self.policy.permissions:
            chip_rows = repository.fetchall(
                """
                SELECT btrim(c.cislo) AS code,
                       NULLIF(btrim(c.stav), '') AS status_code
                FROM public.cipy AS c
                WHERE c.stravnik = %s
                  AND NULLIF(btrim(c.cislo), '') IS NOT NULL
                ORDER BY
                  CASE WHEN c.stav = 'P' THEN 0 ELSE 1 END,
                  c.vydano DESC NULLS LAST,
                  c.id DESC NULLS LAST,
                  c.cislo
                """,
                (evidcislo,),
            )
            chips = tuple(
                DinerChip(
                    code=str(chip["code"]),
                    status_code=(
                        str(chip["status_code"])
                        if chip["status_code"] is not None
                        else None
                    ),
                    status_label=_chip_status_label(chip["status_code"]),
                )
                for chip in chip_rows
            )
        credit = calculate_credit(
            Diner(
                evidcislo=int(row["evidcislo"]),
                kategorie=str(row["category"]),
                hromadny=bool(row["hromadny"]),
                preplatekmm=row["preplatekmm"],
                platittm=row["platittm"],
                platitpm=row["platitpm"],
                platbatm=row["platbatm"],
                platbabm=row["platbabm"],
            )
        )
        return DinerDetail(
            evidcislo=int(row["evidcislo"]),
            name=str(row["name"]),
            category=str(row["category"]),
            class_name=str(row["class_name"]),
            available_credit=credit,
            chip_number=(
                str(row["chip_number"])
                if Permission.CHIPS_VIEW in self.policy.permissions
                and row["chip_number"] is not None
                else None
            ),
            chips=chips,
        )

    def get_allowed_menu_numbers(
        self,
        category: str,
        target: date,
    ) -> tuple[MenuCapability, ...]:
        """Povolená čísla menu podle `public.sazby` pro kategorii a den.

        GUI nesmí počet menu odvozovat samo; capability model je autoritativní
        pouze zde.
        """

        if not isinstance(category, str) or not category.strip():
            raise ValueError("category musí být neprázdný text.")
        if not isinstance(target, date):
            raise ValueError("target musí být date.")
        scope = self._scope(Permission.DINERS_VIEW)
        self.policy.require(Permission.ORDERS_VIEW)
        if category not in scope:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Kategorie není v povoleném rozsahu této session.",
            )
        with self._session() as (connection, repository):
            with connection.transaction():
                repository.configure_read_transaction(
                    self.settings.business_timezone,
                    self.settings.statement_timeout_ms,
                )
                meal_types = [item for item, _order in self._load_meal_types(repository)]
                capabilities = self._load_menu_capabilities(
                    repository,
                    category,
                    [item.typstravy for item in meal_types],
                    target,
                )
                return tuple(
                    MenuCapability(
                        meal_type=item.typstravy,
                        allowed_menus=capabilities.get(item.typstravy, ()),
                    )
                    for item in meal_types
                )

    @staticmethod
    def _load_meal_types(
        repository: OrderReadRepository,
    ) -> list[tuple[MealType, int]]:
        type_rows = repository.fetchall(
            """
            SELECT kod, btrim(typstravy) AS typstravy,
                   COALESCE(poradi, 9999) AS poradi,
                   prihlasdo, prihlasdnu, menudo, menudnu, odhlasdo, odhlasdnu,
                   spolecnes, vyloucenos
            FROM public.typstrav
            WHERE typsluzby = 'strava'
              AND pouzivatpcbox = true
              AND COALESCE(nepouzivat, false) = false
            ORDER BY COALESCE(poradi, 9999), typstravy
            """
        )
        return [
            (
                MealType(
                    typstravy=str(row["typstravy"]),
                    kod=str(row["kod"]),
                    prihlasdo=row["prihlasdo"],
                    prihlasdnu=row["prihlasdnu"],
                    menudo=row["menudo"],
                    menudnu=row["menudnu"],
                    odhlasdo=row["odhlasdo"],
                    odhlasdnu=row["odhlasdnu"],
                    spolecnes=(
                        str(row["spolecnes"])
                        if row["spolecnes"] is not None
                        else None
                    ),
                    vyloucenos=(
                        str(row["vyloucenos"])
                        if row["vyloucenos"] is not None
                        else None
                    ),
                ),
                int(row["poradi"]),
            )
            for row in type_rows
        ]

    @staticmethod
    def _load_menu_capabilities(
        repository: OrderReadRepository,
        category: str,
        meal_names: Sequence[str],
        target: date,
    ) -> dict[str, tuple[int, ...]]:
        """Jeden dávkový dotaz pro všechny zobrazené typy stravy."""

        if not meal_names:
            return {}
        rate_rows = repository.fetchall(
            """
            SELECT btrim(typstravy) AS typstravy, pocetmenu
            FROM public.sazby
            WHERE kategorie = %s
              AND typstravy = ANY(%s::varchar[])
              AND platnostod <= %s
              AND COALESCE(platnostdo, %s) >= %s
            ORDER BY typstravy, platnostod
            """,
            (category, list(meal_names), target, target, target),
        )
        capabilities: dict[str, tuple[int, ...]] = {}
        for row in rate_rows:
            meal_name = str(row["typstravy"])
            if meal_name in capabilities:
                raise OrderBusinessError(
                    ErrorCode.RELATION_CONFIG_INVALID,
                    "Pro den existuje více platných sazeb stejného typu stravy.",
                )
            count = int(row["pocetmenu"] or 0)
            # prihlas ukládá stav dne do jednoho znaku, proto je 9 horní hranice.
            if not 0 <= count <= 9:
                raise OrderBusinessError(
                    ErrorCode.RELATION_CONFIG_INVALID,
                    "Počet povolených menu v sazby musí být 0 až 9.",
                )
            capabilities[meal_name] = tuple(range(1, count + 1))
        return capabilities

    def _load_meals(
        self,
        repository: OrderReadRepository,
        diner: DinerDetail,
        target: date,
        server_now: datetime,
    ) -> tuple[MealDay, ...]:
        loaded_types = self._load_meal_types(repository)
        meal_types = [item for item, _order in loaded_types]
        display_orders = [order for _item, order in loaded_types]
        allowed_menus = self._load_menu_capabilities(
            repository,
            diner.category,
            [item.typstravy for item in meal_types],
            target,
        )
        day_identifiers = sql.SQL(", ").join(
            sql.Identifier(column) for column in DAY_COLUMNS
        )
        state_rows = repository.fetchall(
            sql.SQL(
                """
                SELECT btrim(typsluzby) AS typstravy, {days}
                FROM public.prihlas
                WHERE stravnik = %s AND rok = %s AND mesic = %s
                  AND typsluzby = ANY(%s::varchar[])
                """
            ).format(days=day_identifiers),
            (
                diner.evidcislo,
                target.year,
                target.month,
                [item.typstravy for item in meal_types],
            ),
        )
        month_states: dict[str, tuple[str | None, ...]] = {}
        for row in state_rows:
            key = str(row["typstravy"])
            if key in month_states:
                raise OrderBusinessError(
                    ErrorCode.AMBIGUOUS_ORDER_ROW,
                    "Měsíční objednávkový řádek není jednoznačný.",
                )
            month_states[key] = tuple(
                str(row[column]).strip() if row[column] is not None else None
                for column in DAY_COLUMNS
            )

        menu_rows = repository.fetchall(
            """
            WITH allowed_menu AS (
                SELECT a.typstravy, menu
                FROM unnest(%s::varchar[], %s::integer[])
                     AS a(typstravy, pocetmenu)
                CROSS JOIN LATERAL
                     generate_series(1, a.pocetmenu) AS menu
            ),
            menu_lines AS (
                SELECT btrim(j.typstravy) AS typstravy,
                       t.oznaceni::integer AS menu,
                       string_agg(NULLIF(btrim(j.nazev), ''), ' • '
                                  ORDER BY m.caststravy, j.idjidelnicku)
                           AS dish_name
                FROM public.jidelnicek AS j
                JOIN public.menustravy AS m
                  ON m.id = j.idmenustravy AND m.typstravy = j.typstravy
                JOIN public.typstrj AS t ON t.id = m.idtypstrj
                WHERE j.datum = %s
                  AND j.jazyk = 'česky'
                  AND j.zverejneny = true
                  AND j.cislojidelnicku = 1
                  AND t.oznaceni ~ '^[1-9]$'
                  AND j.typstravy = ANY(%s::varchar[])
                GROUP BY j.typstravy, t.oznaceni
            )
            SELECT a.typstravy, a.menu,
                   NULLIF(btrim(ml.dish_name), '') AS dish_name,
                   price.cena, price.ok
            FROM allowed_menu AS a
            LEFT JOIN menu_lines AS ml
              ON ml.typstravy = a.typstravy AND ml.menu = a.menu
            LEFT JOIN LATERAL public.getcenamenuden(
                a.typstravy, %s, %s, %s, %s, a.menu
            ) AS price ON true
            ORDER BY a.typstravy, a.menu
            """,
            (
                [
                    name
                    for name, menus in allowed_menus.items()
                    if menus
                ],
                [
                    len(menus)
                    for menus in allowed_menus.values()
                    if menus
                ],
                target,
                [item.typstravy for item in meal_types],
                diner.category,
                target.year,
                target.month,
                target.day,
            ),
        )
        options: dict[str, list[MenuOption]] = {}
        for row in menu_rows:
            meal_type = str(row["typstravy"])
            menu = int(row["menu"])
            if not bool(row["ok"]):
                continue
            price = decimal_from_db(
                row["cena"],
                field="getcenamenuden.cena",
                null_is_zero=False,
                error_code=ErrorCode.PRICE_INVALID,
            )
            if price < Decimal(0):
                raise OrderBusinessError(
                    ErrorCode.PRICE_INVALID,
                    "Cena menu nesmí být záporná.",
                )
            published = row["dish_name"] is not None
            options.setdefault(meal_type, []).append(
                MenuOption(
                    menu=menu,
                    dish_name=(
                        str(row["dish_name"])
                        if published
                        else "Jídelníček není zveřejněn"
                    ),
                    price=price,
                    published=published,
                )
            )

        months = {
            (server_now.year, server_now.month),
            (target.year, target.month),
        }
        next_month = 1 if server_now.month == 12 else server_now.month + 1
        next_year = (
            server_now.year + 1 if server_now.month == 12 else server_now.year
        )
        months.add((next_year, next_month))
        calendar_rows = repository.fetchall(
            sql.SQL(
                """
                SELECT btrim(typsluzby) AS typstravy, rok, mesic, {days}
                FROM public.varnedny
                WHERE typsluzby = ANY(%s::varchar[])
                  AND make_date(rok, mesic, 1) = ANY(%s::date[])
                """
            ).format(days=day_identifiers),
            (
                [item.typstravy for item in meal_types],
                [date(year, month, 1) for year, month in sorted(months)],
            ),
        )
        calendars_by_type: dict[
            str, dict[tuple[int, int], dict[int, bool]]
        ] = {}
        for row in calendar_rows:
            meal_name = str(row["typstravy"])
            key = (int(row["rok"]), int(row["mesic"]))
            if key in calendars_by_type.setdefault(meal_name, {}):
                raise OrderBusinessError(
                    ErrorCode.RELATION_CONFIG_INVALID,
                    "Kalendář varných dnů není jednoznačný.",
                )
            calendars_by_type[meal_name][key] = {
                day: str(row[f"d{day:02d}"] or "").strip() == "A"
                for day in range(1, 32)
            }

        result: list[MealDay] = []
        for position, meal_type in enumerate(meal_types):
            states = month_states.get(meal_type.typstravy, ())
            calendars = calendars_by_type.get(meal_type.typstravy, {})
            availability = tuple(
                self._deadline_availability(
                    meal_type,
                    action,
                    target,
                    server_now,
                    calendars,
                )
                for action in OrderAction
            )
            result.append(
                MealDay(
                    code=meal_type.kod,
                    meal_type=meal_type.typstravy,
                    display_order=display_orders[position],
                    current_state=(
                        states[target.day - 1] if len(states) == 31 else None
                    ),
                    options=tuple(options.get(meal_type.typstravy, [])),
                    availability=availability,
                    exclusive_codes=frozenset(
                        character
                        for character in (meal_type.vyloucenos or "")
                        if character.strip()
                    ),
                    allowed_menus=allowed_menus.get(meal_type.typstravy, ()),
                    month_states=states,
                    cooking_days=frozenset(
                        day
                        for day, is_cooking in calendars.get(
                            (target.year, target.month), {}
                        ).items()
                        if is_cooking
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _deadline_availability(
        meal_type: MealType,
        action: OrderAction,
        target: date,
        server_now: datetime,
        calendars: Mapping[tuple[int, int], Mapping[int, bool]],
    ) -> ActionAvailability:
        day_offset, cutoff = deadline_fields(
            action,
            prihlasdnu=meal_type.prihlasdnu,
            prihlasdo=meal_type.prihlasdo,
            menudnu=meal_type.menudnu,
            menudo=meal_type.menudo,
            odhlasdnu=meal_type.odhlasdnu,
            odhlasdo=meal_type.odhlasdo,
        )
        try:
            assert_deadline(
                server_now=server_now,
                target=target,
                day_offset=day_offset,
                cutoff=cutoff,
                target_is_cooking=bool(
                    calendars.get((target.year, target.month), {}).get(target.day)
                ),
                calendars=calendars,
            )
        except OrderBusinessError as exc:
            if exc.code not in {
                ErrorCode.DEADLINE_EXPIRED,
                ErrorCode.NON_COOKING_DAY,
            }:
                raise
            return ActionAvailability(action, False, exc.code)
        return ActionAvailability(action, True)


def _chip_status_label(value: object) -> str:
    code = str(value).strip() if value is not None else ""
    if code == "P":
        return "Přidělen"
    if code == "Z":
        return "Ztracen"
    if code == "B":
        return "Blokován"
    if not code:
        return "Stav neuveden"
    return f"Stav {code} (význam nedoložen)"
