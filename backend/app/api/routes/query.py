from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.schemas.query import QueryAcceptedResponse, QuerySubmissionRequest
from app.services.query_runtime import query_runtime

router = APIRouter(tags=["query"])


@router.post("/query", status_code=status.HTTP_202_ACCEPTED, response_model=QueryAcceptedResponse)
def submit_query(request: QuerySubmissionRequest) -> QueryAcceptedResponse:
    record = query_runtime.create_query(request.query)
    return QueryAcceptedResponse(data=query_runtime.build_acceptance(record))


@router.get("/query/{query_id}/stream")
async def stream_query(query_id: str) -> StreamingResponse:
    record = query_runtime.get_query(query_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "query_not_found",
                "message": f"Query '{query_id}' does not exist.",
                "detail": {"query_id": query_id},
            },
        )

    async def event_generator() -> AsyncIterator[str]:
        events = await query_runtime.stream_query_events(query_id)
        for event in events:
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
