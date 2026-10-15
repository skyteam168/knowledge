from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    env: str


class DependencyStatus(BaseModel):
    status: Literal["up", "down"]
    required: bool
    latency_ms: float | None = None
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded", "not_ready"]
    checks: dict[str, DependencyStatus]

    def redacted(self) -> "ReadinessResponse":
        """Public view: errors and latencies can reveal internal hosts and endpoints."""
        return ReadinessResponse(
            status=self.status,
            checks={
                name: DependencyStatus(status=c.status, required=c.required)
                for name, c in self.checks.items()
            },
        )
