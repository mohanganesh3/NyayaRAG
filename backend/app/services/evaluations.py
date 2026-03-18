from datetime import UTC, datetime

from app.models import EvaluationRun
from sqlalchemy import select
from sqlalchemy.orm import Session


class EvaluationRunStore:
    def create_run(
        self,
        session: Session,
        *,
        suite_name: str,
        benchmark_name: str,
        benchmark_version: str | None,
        status: str,
        measured_at: datetime | None,
        query_count: int,
        is_public: bool,
        metrics: dict[str, float],
        notes: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> EvaluationRun:
        run = EvaluationRun(
            suite_name=suite_name,
            benchmark_name=benchmark_name,
            benchmark_version=benchmark_version,
            status=status,
            measured_at=measured_at or datetime.now(UTC),
            query_count=query_count,
            is_public=is_public,
            metrics=metrics,
            notes=notes,
            payload=payload,
        )
        session.add(run)
        session.flush()
        return run

    def latest_public_completed(self, session: Session) -> EvaluationRun | None:
        return session.scalar(
            select(EvaluationRun)
            .where(
                EvaluationRun.is_public.is_(True),
                EvaluationRun.status == "completed",
            )
            .order_by(EvaluationRun.measured_at.desc(), EvaluationRun.created_at.desc())
        )


evaluation_run_store = EvaluationRunStore()
