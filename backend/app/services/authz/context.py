from dataclasses import dataclass, field

from app.core.permissions import has_any_permission, has_permission
from app.services.authz.principals import Principals


@dataclass(frozen=True)
class CurrentUser:
    id: str
    org_id: str
    username: str
    display_name: str | None
    principals: Principals
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_platform_admin: bool = False

    def has_permission(self, code: str) -> bool:
        return has_permission(self.permissions, code)

    def has_any_permission(self, *codes: str) -> bool:
        return has_any_permission(self.permissions, codes)

    @property
    def is_superuser(self) -> bool:
        return "*" in self.permissions
