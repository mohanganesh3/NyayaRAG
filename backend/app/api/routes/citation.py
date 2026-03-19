from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.citation import (
    AppealChainResponse,
    CitationSourceResponse,
    CitationVerificationResponse,
    JudgmentResponse,
    StatuteSectionLookupResponse,
)
from app.services.citation_sources import citation_source_store

router = APIRouter(tags=["citation"])
DbSession = Annotated[Session, Depends(get_db)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "citation_not_found",
            "message": detail,
        },
    )


def _invalid_request(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "citation_request_invalid",
            "message": detail,
        },
    )


@router.get("/citation/{doc_id}/source", response_model=CitationSourceResponse)
def get_citation_source(
    doc_id: str,
    db: DbSession,
    chunk_id: Annotated[str | None, Query()] = None,
) -> CitationSourceResponse:
    try:
        source = citation_source_store.get_source(db, doc_id=doc_id, chunk_id=chunk_id)
    except ValueError as exc:
        message = str(exc)
        if "No legal document exists" in message or "No document chunk" in message:
            raise _not_found(message) from exc
        raise _invalid_request(message) from exc

    return CitationSourceResponse(data=source)


@router.get("/citation/{doc_id}/verify", response_model=CitationVerificationResponse)
def verify_citation(
    doc_id: str,
    db: DbSession,
    chunk_id: Annotated[str | None, Query()] = None,
    claim: Annotated[str | None, Query()] = None,
) -> CitationVerificationResponse:
    try:
        verification = citation_source_store.verify_citation(
            db,
            doc_id=doc_id,
            chunk_id=chunk_id,
            claim=claim,
        )
    except ValueError as exc:
        message = str(exc)
        if "No legal document exists" in message or "No document chunk" in message:
            raise _not_found(message) from exc
        raise _invalid_request(message) from exc

    return CitationVerificationResponse(data=verification)


@router.get("/citation/{doc_id}/appealchain", response_model=AppealChainResponse)
def get_appeal_chain(doc_id: str, db: DbSession) -> AppealChainResponse:
    try:
        appeal_chain = citation_source_store.get_appeal_chain(db, doc_id=doc_id)
    except ValueError as exc:
        raise _not_found(str(exc)) from exc

    return AppealChainResponse(data=appeal_chain)


@router.get("/judgment/{doc_id}", response_model=JudgmentResponse)
def get_judgment(doc_id: str, db: DbSession) -> JudgmentResponse:
    try:
        judgment = citation_source_store.get_judgment(db, doc_id=doc_id)
    except ValueError as exc:
        message = str(exc)
        if "No legal document exists" in message:
            raise _not_found(message) from exc
        raise _invalid_request(message) from exc

    return JudgmentResponse(data=judgment)


@router.get(
    "/statute/{act_id}/section/{section_number}",
    response_model=StatuteSectionLookupResponse,
)
def get_statute_section(
    act_id: str,
    section_number: str,
    db: DbSession,
) -> StatuteSectionLookupResponse:
    try:
        statute = citation_source_store.get_statute_section(
            db,
            act_id=act_id,
            section_number=section_number,
        )
    except ValueError as exc:
        message = str(exc)
        if "No statute document exists" in message or "No section" in message:
            raise _not_found(message) from exc
        raise _invalid_request(message) from exc

    return StatuteSectionLookupResponse(data=statute)
