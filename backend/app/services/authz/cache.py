from app.core.cache import KeyValueCache


class AuthzCache:
    """Per-user authorization cache with two invalidation granularities.

    Keys embed an org-level version: `authz:{org}:v{ver}:{kind}:{user}`.
    - invalidate_user: drop one user's entries (membership / department change).
    - invalidate_org: bump the version so every user in the org is recomputed
      (role-permission change, department tree move, group/role deletion).
    """

    KINDS = ("principals", "perms")

    def __init__(self, cache: KeyValueCache, ttl_seconds: int) -> None:
        self.cache = cache
        self.ttl = ttl_seconds

    async def _version(self, org_id: str) -> str:
        return await self.cache.get(f"authz:{org_id}:ver") or "0"

    async def key(self, kind: str, org_id: str, user_id: str) -> str:
        return f"authz:{org_id}:v{await self._version(org_id)}:{kind}:{user_id}"

    async def get(self, kind: str, org_id: str, user_id: str) -> str | None:
        return await self.cache.get(await self.key(kind, org_id, user_id))

    async def set(self, kind: str, org_id: str, user_id: str, value: str) -> None:
        await self.cache.set(await self.key(kind, org_id, user_id), value, self.ttl)

    async def invalidate_user(self, org_id: str, *user_ids: str) -> None:
        keys = [await self.key(kind, org_id, uid) for uid in user_ids for kind in self.KINDS]
        await self.cache.delete(*keys)

    async def invalidate_org(self, org_id: str) -> None:
        await self.cache.incr(f"authz:{org_id}:ver")
