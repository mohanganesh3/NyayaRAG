from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.evaluation import PublicTrustResponse, PublicTrustSnapshot
from app.services.evaluations import evaluation_run_store

router = APIRouter(tags=["trust"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/trust", response_model=PublicTrustResponse)
def get_public_trust_snapshot(db: DbSession) -> PublicTrustResponse:
    run = evaluation_run_store.latest_public_completed(db)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "trust_metrics_not_found",
                "message": "No public measured trust metrics are available yet.",
                "detail": None,
            },
        )

    return PublicTrustResponse(
        data=PublicTrustSnapshot(
            run_id=run.id,
            suite_name=run.suite_name,
            benchmark_name=run.benchmark_name,
            benchmark_version=run.benchmark_version,
            measured_at=run.measured_at,
            query_count=run.query_count,
            metrics=run.metrics,
            notes=run.notes,
            payload=run.payload,
        )
    )
@router.get("/trust/scorecard")
def get_eval_scorecard():
    """Returns the latest NyayaEval scorecard."""
    import os
    import json
    report_path = "nyaya_eval_report.json"
    if not os.path.exists(report_path):
        return {
            "status": "pending",
            "message": "Evaluation report not found. Please run the evaluation suite."
        }
        
    with open(report_path, "r") as f:
        data = json.load(f)
        
    return {
        "status": "completed",
        "overall": data.get("overall"),
        "by_category": {cat: len(results) for cat, results in data.get("by_category", {}).items()}
    }
