from collections.abc import Awaitable, Callable
from dataclasses import dataclass

ReadinessCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: dict[str, str]
    message: str


class ReadinessChecker:
    """Extensible async checker registry.

    TASK-001 deliberately registers no database or configuration check. Later tasks
    can add async checks without changing the `/ready` route contract.
    """

    def __init__(self) -> None:
        self._checks: dict[str, ReadinessCheck] = {}

    def register(self, name: str, check: ReadinessCheck) -> None:
        self._checks[name] = check

    async def check(self) -> ReadinessReport:
        if not self._checks:
            return ReadinessReport(
                ready=False,
                checks={
                    "database": "not_initialized",
                    "config": "not_initialized",
                },
                message="DB/config checker not initialized",
            )

        results: dict[str, str] = {}
        ready = True
        for name, check in self._checks.items():
            passed = await check()
            results[name] = "ok" if passed else "failed"
            ready = ready and passed
        return ReadinessReport(
            ready=ready,
            checks=results,
            message="ready" if ready else "readiness checks failed",
        )
