from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    suite_name: str
    benchmark_name: str
    benchmark_version: str | None = None
    status: str
    measured_at: datetime
    query_count: int
    is_public: bool
    metrics: dict[str, float]
    notes: str | None = None
    payload: dict[str, object] | None = None


class PublicTrustSnapshot(BaseModel):
    run_id: str
    suite_name: str
    benchmark_name: str
    benchmark_version: str | None = None
    measured_at: datetime
    query_count: int
    metrics: dict[str, float]
    notes: str | None = None
    payload: dict[str, object] | None = None


class PublicTrustResponse(BaseModel):
    success: Literal[True] = True
    data: PublicTrustSnapshot
