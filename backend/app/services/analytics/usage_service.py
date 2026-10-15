"""Model usage dashboard (tokens per day, model, feature and user) from analytics_llm_usage."""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select

from app.llm.usage import FEATURE_ASSISTANT
from app.models import NO_USER, SERVICE_USER_PREFIX, AnalyticsLlmUsage, Department, User
from app.repositories.org_repo import DepartmentRepository
from app.schemas.analytics import (
    LlmUsageDailyOut,
    LlmUsageFeatureOut,
    LlmUsageModelOut,
    LlmUsageOut,
    LlmUsageSummaryOut,
    LlmUsageUserOut,
)
from app.services.analytics.analytics_service import AnalyticsService

USER_LIMIT = 100

T = AnalyticsLlmUsage
TOTALS = (
    func.sum(T.calls),
    func.sum(T.errors),
    func.sum(T.estimated_calls),
    func.sum(T.fallback_calls),
    func.sum(T.prompt_tokens),
    func.sum(T.completion_tokens),
    func.sum(T.total_tokens),
    func.sum(T.latency_ms),
)


def _totals(values: Sequence[Any]) -> dict[str, Any]:
    calls, errors, estimated, fallback, prompt, completion, total, latency = (
        int(v or 0) for v in values
    )
    return {
        "calls": calls,
        "errors": errors,
        "estimated_calls": estimated,
        "fallback_calls": fallback,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "avg_latency_ms": round(latency / calls, 1) if calls else None,
    }


class LlmUsageService(AnalyticsService):
    async def usage(
        self,
        org_id: str | None,
        date_from: date | None,
        date_to: date | None,
        user_id: str | None = None,
    ) -> LlmUsageOut:
        org = self._org(org_id)
        start, end = self._range(date_from, date_to)
        where: list[ColumnElement[bool]] = [T.org_id == org, T.day >= start, T.day <= end]
        if user_id is not None:
            where.append(T.user_id == user_id)

        def grouped(*keys: Any) -> Select[Any]:
            return select(*keys, *TOTALS).where(*where).group_by(*keys)

        summary_row = (await self.session.execute(select(*TOTALS).where(*where))).one()
        users_count = (
            await self.session.execute(
                select(func.count(func.distinct(T.user_id))).where(*where, T.user_id != NO_USER)
            )
        ).scalar_one()
        summary = LlmUsageSummaryOut(**_totals(summary_row), users=int(users_count or 0))

        by_day = {
            row[0]: _totals(row[1:]) for row in (await self.session.execute(grouped(T.day))).all()
        }
        daily: list[LlmUsageDailyOut] = []
        day = start
        while day <= end:
            t = by_day.get(day, _totals([0] * len(TOTALS)))
            daily.append(
                LlmUsageDailyOut(
                    day=day,
                    calls=t["calls"],
                    prompt_tokens=t["prompt_tokens"],
                    completion_tokens=t["completion_tokens"],
                    total_tokens=t["total_tokens"],
                )
            )
            day += timedelta(days=1)

        by_model = [
            LlmUsageModelOut(kind=kind, model=model, **_totals(rest))
            for kind, model, *rest in (await self.session.execute(grouped(T.kind, T.model))).all()
        ]
        by_model.sort(key=lambda m: (-m.total_tokens, m.kind, m.model))
        by_feature = [
            LlmUsageFeatureOut(feature=feature, **_totals(rest))
            for feature, *rest in (await self.session.execute(grouped(T.feature))).all()
        ]
        by_feature.sort(key=lambda f: -f.total_tokens)

        users, users_total = await self._users(org, where)
        refreshed = (
            await self.session.execute(select(func.max(T.refreshed_at)).where(*where))
        ).scalar()
        return LlmUsageOut(
            org_id=org,
            user_id=user_id,
            date_from=start,
            date_to=end,
            summary=summary,
            daily=daily,
            by_model=by_model,
            by_feature=by_feature,
            users=users,
            users_total=int(users_total or 0),
            refreshed_at=refreshed,
        )

    async def _users(
        self, org_id: str, where: list[ColumnElement[bool]]
    ) -> tuple[list[LlmUsageUserOut], int]:
        scoped = [*where, T.user_id != NO_USER]
        assistant = func.sum(T.total_tokens).filter(T.feature == FEATURE_ASSISTANT)
        stmt = (
            select(T.user_id, *TOTALS, assistant)
            .where(*scoped)
            .group_by(T.user_id)
            .order_by(func.sum(T.total_tokens).desc(), T.user_id)
            .limit(USER_LIMIT)
        )
        rows = (await self.session.execute(stmt)).all()
        count = (
            await self.session.execute(select(func.count(func.distinct(T.user_id))).where(*scoped))
        ).scalar_one()
        people: dict[str, User] = {}
        if rows:
            found = await self.session.execute(
                select(User).where(User.org_id == org_id, User.id.in_([r[0] for r in rows]))
            )
            people = {u.id: u for u in found.scalars()}
        paths: dict[str, str] = {}
        dept_ids = {u.department_id for u in people.values() if u.department_id}
        if dept_ids:
            found_depts = await self.session.execute(
                select(Department).where(Department.org_id == org_id, Department.id.in_(dept_ids))
            )
            paths = await DepartmentRepository(self.session).path_names(
                org_id, list(found_depts.scalars())
            )
        out: list[LlmUsageUserOut] = []
        for user_id, *rest in rows:
            *totals, assistant_tokens = rest
            u = people.get(user_id)
            out.append(
                LlmUsageUserOut(
                    user_id=user_id,
                    username=u.username if u else None,
                    display_name=u.display_name if u else None,
                    department=paths.get(u.department_id) if u and u.department_id else None,
                    is_service=bool(u and u.username.startswith(SERVICE_USER_PREFIX)),
                    assistant_tokens=int(assistant_tokens or 0),
                    **_totals(totals),
                )
            )
        return out, int(count or 0)
