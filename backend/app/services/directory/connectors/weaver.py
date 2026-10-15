"""Weaver e-cology 9 (泛微 OA) HR tables over a read-only database account.

Tree: subcompanies (HrmSubCompany) become nodes "sub:<id>", departments (HrmDepartment)
"dept:<id>" under their parent department or, at the top, under their subcompany.
People: HrmResource; status 0-3 = employed (试用/正式/临时/试用延期), 4+ = left / dismissed /
retired / invalid. A secondary account (accounttype=1, belongto=<main id>) adds its department
to the main account. Every query can be overridden for customized schemas (same columns).
"""

import asyncio
import re
from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from app.services.directory.connectors.base import ConnectorError, DirectoryConnector
from app.services.directory.snapshot import DeptRecord, Snapshot, UserRecord

DEFAULT_SQL = {
    "sql_subcompanies": (
        "SELECT id, subcompanyname AS name, supsubcomid AS parent_id, "
        "showorder AS sort_order, canceled FROM HrmSubCompany"
    ),
    "sql_departments": (
        "SELECT id, departmentname AS name, supdepid AS parent_id, "
        "subcompanyid1 AS subcompany_id, showorder AS sort_order, canceled FROM HrmDepartment"
    ),
    "sql_users": (
        "SELECT r.id, r.loginid, r.workcode, r.lastname AS name, r.email, r.mobile, "
        "r.departmentid, r.status, r.accounttype, r.belongto, j.jobtitlename AS title "
        "FROM HrmResource r LEFT JOIN HrmJobTitles j ON j.id = r.jobtitle"
    ),
}
DEFAULT_PORTS = {"sqlserver": 1433, "oracle": 1521, "mysql": 3306}
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|exec|execute|grant|call)\b", re.I
)


class WeaverConfig(BaseModel):
    db_type: Literal["sqlserver", "oracle", "mysql"]
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    # SQL Server / MySQL database name; Oracle service name.
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    include_subcompanies: bool = True
    active_statuses: list[int] = [0, 1, 2, 3]
    sql_subcompanies: str | None = None
    sql_departments: str | None = None
    sql_users: str | None = None

    @field_validator("sql_subcompanies", "sql_departments", "sql_users")
    @classmethod
    def _read_only(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        sql = value.strip().rstrip(";")
        if ";" in sql or not re.match(r"^(select|with)\b", sql, re.I) or _FORBIDDEN.search(sql):
            raise ValueError("Only a single SELECT statement is allowed")
        return sql

    def sql(self, name: str) -> str:
        return str(getattr(self, name) or DEFAULT_SQL[name])


class _Cursor(Protocol):
    description: Any

    def execute(self, sql: str) -> Any: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> Any: ...


class _Connection(Protocol):
    def cursor(self) -> Any: ...
    def close(self) -> Any: ...


ConnectFn = Callable[[WeaverConfig, int], _Connection]


def default_connect(cfg: WeaverConfig, timeout: int) -> _Connection:
    port = cfg.port or DEFAULT_PORTS[cfg.db_type]
    if cfg.db_type == "sqlserver":
        import pymssql

        conn: Any = pymssql.connect(
            server=cfg.host,
            port=str(port),
            user=cfg.username,
            password=cfg.password,
            database=cfg.database,
            login_timeout=timeout,
            timeout=timeout,
        )
        return conn  # type: ignore[no-any-return]
    if cfg.db_type == "oracle":
        import oracledb

        conn = oracledb.connect(
            user=cfg.username,
            password=cfg.password,
            dsn=f"{cfg.host}:{port}/{cfg.database}",
            tcp_connect_timeout=float(timeout),
        )
        conn.call_timeout = timeout * 1000
        return conn  # type: ignore[no-any-return]
    import pymysql

    conn = pymysql.connect(
        host=cfg.host,
        port=port,
        user=cfg.username,
        password=cfg.password,
        database=cfg.database,
        charset="utf8mb4",
        connect_timeout=timeout,
        read_timeout=timeout,
    )
    return conn  # type: ignore[no-any-return]


def _rows(conn: _Connection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        columns = [str(c[0]).lower() for c in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _id(value: Any) -> str | None:
    number = _int(value, 0)
    return str(number) if number > 0 else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class WeaverConnector(DirectoryConnector):
    config_model = WeaverConfig
    secret_fields = ("password",)

    def __init__(
        self,
        config: dict[str, Any],
        settings: Any,
        connect: ConnectFn | None = None,
    ) -> None:
        super().__init__(config, settings)
        self.connect = connect or default_connect

    def _query_all(self, cfg: WeaverConfig) -> dict[str, list[dict[str, Any]]]:
        timeout = int(self.settings.directory_db_timeout_seconds)
        try:
            conn = self.connect(cfg, timeout)
        except Exception as exc:
            raise ConnectorError(
                f"无法连接泛微数据库：{type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
        try:
            result: dict[str, list[dict[str, Any]]] = {}
            names = ["sql_departments", "sql_users"]
            if cfg.include_subcompanies:
                names.insert(0, "sql_subcompanies")
            for name in names:
                try:
                    result[name] = _rows(conn, cfg.sql(name))
                except Exception as exc:
                    raise ConnectorError(
                        f"查询失败（{name}）：{type(exc).__name__}: {str(exc)[:300]}",
                        detail={"query": name},
                    ) from exc
            return result
        finally:
            conn.close()

    async def fetch(self) -> Snapshot:
        cfg = WeaverConfig.model_validate(self.raw_config)
        data = await asyncio.to_thread(self._query_all, cfg)
        return build_snapshot(cfg, data)


def build_snapshot(cfg: WeaverConfig, data: dict[str, list[dict[str, Any]]]) -> Snapshot:
    depts: list[DeptRecord] = []
    subcompanies = data.get("sql_subcompanies", [])
    for row in subcompanies:
        sid = _id(row.get("id"))
        if not sid:
            continue
        parent = _id(row.get("parent_id"))
        depts.append(
            DeptRecord(
                external_id=f"sub:{sid}",
                name=_text(row.get("name")) or f"分部{sid}",
                parent_external_id=f"sub:{parent}" if parent else None,
                order=_int(row.get("sort_order")),
                active=_int(row.get("canceled")) != 1,
            )
        )
    for row in data.get("sql_departments", []):
        did = _id(row.get("id"))
        if not did:
            continue
        parent = _id(row.get("parent_id"))
        sub = _id(row.get("subcompany_id"))
        if parent:
            parent_ext: str | None = f"dept:{parent}"
        elif sub and cfg.include_subcompanies:
            parent_ext = f"sub:{sub}"
        else:
            parent_ext = None
        depts.append(
            DeptRecord(
                external_id=f"dept:{did}",
                name=_text(row.get("name")) or f"部门{did}",
                parent_external_id=parent_ext,
                order=_int(row.get("sort_order")),
                active=_int(row.get("canceled")) != 1,
            )
        )

    active_statuses = set(cfg.active_statuses)
    mains: dict[str, UserRecord] = {}
    secondary: list[tuple[str, str]] = []
    for row in data.get("sql_users", []):
        rid = _id(row.get("id"))
        if not rid:
            continue
        dept = _id(row.get("departmentid"))
        belongto = _id(row.get("belongto"))
        if _int(row.get("accounttype")) == 1 and belongto:
            if dept and _int(row.get("status")) in active_statuses:
                secondary.append((belongto, f"dept:{dept}"))
            continue
        workcode = _text(row.get("workcode"))
        mains[rid] = UserRecord(
            external_id=rid,
            username=_text(row.get("loginid")) or workcode or f"weaver{rid}",
            name=_text(row.get("name")) or rid,
            email=_text(row.get("email")),
            mobile=_text(row.get("mobile")),
            employee_no=workcode,
            title=_text(row.get("title")),
            dept_external_ids=[f"dept:{dept}"] if dept else [],
            primary_dept=f"dept:{dept}" if dept else None,
            active=_int(row.get("status"), -1) in active_statuses,
        )
    for main_id, dept_ext in secondary:
        user = mains.get(main_id)
        if user and dept_ext not in user.dept_external_ids:
            user.dept_external_ids.append(dept_ext)
    return Snapshot(departments=depts, users=list(mains.values()))
