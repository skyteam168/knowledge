"""Source-independent view of an organization directory, produced by every connector."""

from dataclasses import dataclass, field

from app.core.exceptions import AppError


class SnapshotError(AppError):
    code = "DIRECTORY_SNAPSHOT_INVALID"
    message = "Directory data is invalid"


@dataclass
class DeptRecord:
    external_id: str
    name: str
    parent_external_id: str | None = None
    order: int = 0
    # False = removed / sealed upstream (archived locally).
    active: bool = True


@dataclass
class UserRecord:
    external_id: str
    username: str
    name: str
    email: str | None = None
    mobile: str | None = None
    employee_no: str | None = None
    title: str | None = None
    dept_external_ids: list[str] = field(default_factory=list)
    primary_dept: str | None = None
    active: bool = True
    union_id: str | None = None


@dataclass
class Snapshot:
    departments: list[DeptRecord] = field(default_factory=list)
    users: list[UserRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def normalized(self) -> "Snapshot":
        """Dedupe ids, drop dangling parents, reject cycles, trim text fields."""
        warnings = list(self.warnings)
        depts: dict[str, DeptRecord] = {}
        for d in self.departments:
            ext = str(d.external_id).strip()
            if not ext:
                continue
            if ext in depts:
                warnings.append(f"重复的部门 ID：{ext}")
                continue
            parent = str(d.parent_external_id).strip() if d.parent_external_id else None
            depts[ext] = DeptRecord(
                external_id=ext,
                name=(d.name or "").strip()[:128] or ext,
                parent_external_id=parent or None,
                order=d.order,
                active=d.active,
            )
        for d in depts.values():
            if d.parent_external_id == d.external_id or (
                d.parent_external_id and d.parent_external_id not in depts
            ):
                if d.parent_external_id and d.parent_external_id != d.external_id:
                    warnings.append(f"部门「{d.name}」的上级 {d.parent_external_id} 不存在，挂到根")
                d.parent_external_id = None
        for d in depts.values():
            seen = {d.external_id}
            cursor = d.parent_external_id
            while cursor:
                if cursor in seen:
                    raise SnapshotError(
                        "Department tree has a cycle", detail={"department": d.external_id}
                    )
                seen.add(cursor)
                cursor = depts[cursor].parent_external_id

        users: dict[str, UserRecord] = {}
        for u in self.users:
            ext = str(u.external_id).strip()
            if not ext:
                continue
            if ext in users:
                warnings.append(f"重复的人员 ID：{ext}")
                continue
            dept_ids = [str(x).strip() for x in u.dept_external_ids if str(x).strip()]
            unknown = [x for x in dept_ids if x not in depts]
            if unknown:
                warnings.append(f"人员「{u.name}」的部门 {','.join(unknown)} 不存在，已忽略")
            dept_ids = list(dict.fromkeys(x for x in dept_ids if x in depts))
            primary = str(u.primary_dept).strip() if u.primary_dept else None
            if primary not in dept_ids:
                primary = dept_ids[0] if dept_ids else None
            users[ext] = UserRecord(
                external_id=ext,
                username=(u.username or "").strip()[:128] or ext,
                name=(u.name or "").strip()[:128] or (u.username or ext),
                email=_clean(u.email, 255),
                mobile=_clean(u.mobile, 32),
                employee_no=_clean(u.employee_no, 64),
                title=_clean(u.title, 100),
                dept_external_ids=dept_ids,
                primary_dept=primary,
                active=u.active,
                union_id=_clean(u.union_id, 128),
            )
        return Snapshot(list(depts.values()), list(users.values()), warnings)


def _clean(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_len] or None
