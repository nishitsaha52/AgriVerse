from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.db import get_db
from agriverse.dependencies import enforce_ai_quota, require_permissions
from agriverse.models import (
    AgentConversation,
    AgentMessage,
    Diagnosis,
    Scan,
    SoilTest,
    UsageRecord,
)
from agriverse.routers.soil import authorize_field
from agriverse.schemas import AgentAnswer, AgentQuestion
from agriverse.security import Principal
from agriverse.services.ai import vision_provider
from agriverse.services.retrieval import (
    citations_from_document_rows,
    embedding_service,
    search_documents,
)
from agriverse.services.safety import contains_prompt_injection
from agriverse.services.weather import weather_service

router = APIRouter(prefix="/agronomist", tags=["agronomist agent"])


@router.post("/ask", response_model=AgentAnswer)
async def ask_agronomist(
    payload: AgentQuestion,
    principal: Principal = Depends(require_permissions("agent:use")),
    quota_principal: Principal = Depends(enforce_ai_quota),
    db: AsyncSession = Depends(get_db),
) -> AgentAnswer:
    del quota_principal
    if contains_prompt_injection(payload.question):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The request contains instruction-override language and was not processed",
        )
    field = await authorize_field(db, principal, payload.field_id)
    if payload.conversation_id is None:
        conversation = AgentConversation(
            field_id=field.id,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            title=payload.question[:120],
            language=payload.language,
        )
        db.add(conversation)
        await db.flush()
    else:
        existing_conversation = await db.scalar(
            select(AgentConversation).where(
                AgentConversation.id == payload.conversation_id,
                AgentConversation.organization_id == principal.organization_id,
                AgentConversation.user_id == principal.user_id,
                AgentConversation.field_id == field.id,
            )
        )
        if existing_conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        conversation = existing_conversation

    soil = await db.scalar(
        select(SoilTest)
        .where(SoilTest.field_id == field.id)
        .order_by(SoilTest.created_at.desc())
        .limit(1)
    )
    scan_rows = (
        await db.execute(
            select(Scan, Diagnosis)
            .outerjoin(Diagnosis, Diagnosis.scan_id == Scan.id)
            .where(Scan.field_id == field.id)
            .order_by(Scan.created_at.desc())
            .limit(3)
        )
    ).all()
    try:
        forecast = await weather_service.get_current(
            cache_region=f"{field.state}:{field.district}",
            latitude=float(field.latitude),
            longitude=float(field.longitude),
        )
        weather_context: dict[str, Any] | None = forecast.model_dump(mode="json")
    except Exception:
        weather_context = None

    document_rows: list[dict[str, Any]] = []
    try:
        query_embedding = (
            await embedding_service.embed_texts([payload.question], input_type="query")
        )[0]
        document_rows = await search_documents(
            db,
            query_embedding=query_embedding,
            agro_climatic_zone=field.agro_climatic_zone,
            query=payload.question,
        )
    except Exception:
        pass
    citations = citations_from_document_rows(document_rows)
    context = {
        "field": {
            "id": str(field.id),
            "crop": field.current_crop,
            "state": field.state,
            "district": field.district,
            "agro_climatic_zone": field.agro_climatic_zone,
        },
        "latest_soil_test": (
            {
                "fertility_index": str(soil.fertility_index),
                "algorithm_version": soil.algorithm_version,
                "n": str(soil.n),
                "p": str(soil.p),
                "k": str(soil.k),
                "ph": str(soil.ph),
            }
            if soil
            else None
        ),
        "weather": weather_context,
        "recent_scans": [
            {
                "status": scan.status,
                "created_at": scan.created_at.isoformat(),
                "diagnosis": diagnosis.full_response if diagnosis else None,
            }
            for scan, diagnosis in scan_rows
        ],
        "retrieved_documents": [
            {
                "chunk_id": str(row["chunk_id"]),
                "content": row["content"],
                "tier": row["tier"],
                "publisher": row["publisher"],
            }
            for row in document_rows
        ],
    }
    answer, metadata = await vision_provider.answer(
        question=payload.question,
        context=context,
        language=payload.language,
    )
    db.add_all(
        [
            AgentMessage(
                conversation_id=conversation.id,
                organization_id=principal.organization_id,
                role="user",
                content=payload.question,
            ),
            AgentMessage(
                conversation_id=conversation.id,
                organization_id=principal.organization_id,
                role="assistant",
                content=answer,
                citations=[citation.model_dump(mode="json") for citation in citations],
                provider_metadata=metadata,
            ),
        ]
    )
    usage = metadata.get("usage", {})
    db.add(
        UsageRecord(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            call_type="agronomist_agent",
            tokens_used=int(usage.get("total_tokens", 0)),
            cost_usd=0,
        )
    )
    record_audit(
        db,
        principal,
        action="ai.agent_called",
        resource_type="agent_conversation",
        resource_id=conversation.id,
        after={
            "provider": metadata.get("provider", "unknown"),
            "model": metadata.get("model"),
            "response_id": metadata.get("response_id"),
            "usage": usage,
        },
    )
    await db.commit()
    return AgentAnswer(
        conversation_id=conversation.id,
        answer=answer,
        citations=citations,
    )
