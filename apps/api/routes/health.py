"""Endpoint de health check — usado por orquestradores de deploy e CI."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Checagem simples de disponibilidade do serviço."""
    return {"status": "ok", "service": "plantao-ai"}
