from typing import Any

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models import LOCAL_SOURCE, Department
from app.models.base import new_id
from app.repositories.org_repo import DepartmentRepository, build_path_name
from app.repositories.user_repo import UserRepository
from app.schemas.identity import DepartmentCreate, DepartmentNode, DepartmentUpdate
from app.services.audit_service import audited
from app.services.context import BaseService


async def _load(self: "DepartmentService", dept_id: str, *_: Any, **__: Any) -> Department:
    return await self.get(dept_id)


def build_tree(departments: list[Department]) -> list[DepartmentNode]:
    names = {d.id: d.name for d in departments}
    nodes = {
        d.id: DepartmentNode.model_validate(d).model_copy(
            update={"path_name": build_path_name(d, names)}
        )
        for d in departments
    }
    roots: list[DepartmentNode] = []
    for dept in departments:
        node = nodes[dept.id]
        parent = nodes.get(dept.parent_id) if dept.parent_id else None
        (parent.children if parent else roots).append(node)
    return roots


class DepartmentService(BaseService):
    @property
    def repo(self) -> DepartmentRepository:
        return DepartmentRepository(self.session)

    async def get(self, dept_id: str) -> Department:
        dept = await self.repo.get(self.org_id, dept_id)
        if dept is None:
            raise NotFoundError("Department not found")
        return dept

    async def tree(self) -> list[DepartmentNode]:
        return build_tree(await self.repo.list_all(self.org_id))

    async def subtree_ids(self, dept_id: str) -> list[str]:
        dept = await self.get(dept_id)
        return [d.id for d in await self.repo.list_subtree(self.org_id, dept.path)]

    @audited("department.create", "department")
    async def create(self, data: DepartmentCreate) -> Department:
        parent_path = "/"
        if data.parent_id:
            parent_path = (await self.get(data.parent_id)).path
        dept_id = new_id()
        dept = Department(
            id=dept_id,
            org_id=self.org_id,
            parent_id=data.parent_id,
            name=data.name,
            sort_order=data.sort_order,
            path=f"{parent_path}{dept_id}/",
        )
        return await self.repo.add(dept)

    @audited("department.update", "department", load=_load)
    async def update(self, dept_id: str, data: DepartmentUpdate) -> Department:
        dept = await self.get(dept_id)
        if dept.source != LOCAL_SOURCE:
            locked = [
                f
                for f in ("name", "parent_id")
                if f in data.model_fields_set and getattr(data, f) != getattr(dept, f)
            ]
            if locked:
                raise AppError(
                    "Fields are managed by the directory source",
                    code="DIRECTORY_MANAGED",
                    detail={"fields": locked, "source": dept.source},
                )
        if data.name is not None:
            dept.name = data.name
        if data.sort_order is not None:
            dept.sort_order = data.sort_order
        if "parent_id" in data.model_fields_set and data.parent_id != dept.parent_id:
            await self._move(dept, data.parent_id)
        await self.session.flush()
        return dept

    async def _move(self, dept: Department, new_parent_id: str | None) -> None:
        parent_path = "/"
        if new_parent_id:
            parent = await self.get(new_parent_id)
            if parent.path.startswith(dept.path):
                raise AppError("Cannot move a department under itself", code="INVALID_PARENT")
            parent_path = parent.path
        old_path = dept.path
        new_path = f"{parent_path}{dept.id}/"
        for node in await self.repo.list_subtree(self.org_id, old_path):
            node.path = new_path + node.path[len(old_path) :]
        dept.parent_id = new_parent_id
        # Ancestor chains of every user in the subtree changed.
        await self.authz_cache.invalidate_org(self.org_id)

    @audited("department.delete", "department", load=_load)
    async def delete(self, dept_id: str) -> None:
        dept = await self.get(dept_id)
        if dept.source != LOCAL_SOURCE:
            raise AppError(
                "Department is managed by the directory source",
                code="DIRECTORY_MANAGED",
                detail={"source": dept.source},
            )
        if await self.repo.has_children(self.org_id, dept_id):
            raise ConflictError("Department has sub-departments")
        if await UserRepository(self.session).count_in_departments(self.org_id, [dept_id]):
            raise ConflictError("Department still has users")
        await self.repo.delete(dept)
