import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.db.models import ModelRegistry

TIER_PRICING = {
    "S": 1,
    "M": 2,
    "L": 4,
    "XL": 8,
    "XXL": 16,
}


def infer_parameter_count(model_id: str) -> int:
    match = re.search(r"(\d+(?:\.\d+)?)B", model_id, re.IGNORECASE)
    if not match:
        return 7_000_000_000
    value = float(match.group(1))
    return int(value * 1_000_000_000)


def infer_quantization(model_id: str) -> str:
    match = re.search(r"(2bit|3bit|4bit|5bit|6bit|8bit|fp16|16bit)", model_id, re.IGNORECASE)
    if not match:
        return "4bit"
    return match.group(1).lower()


def estimate_ram_gb(parameter_count: int, quantization: str) -> float:
    bits_lookup = {
        "2bit": 0.25,
        "3bit": 0.375,
        "4bit": 0.5,
        "5bit": 0.625,
        "6bit": 0.75,
        "8bit": 1.0,
        "fp16": 2.0,
        "16bit": 2.0,
    }
    bytes_per_weight = bits_lookup.get(quantization, 0.5)
    base_ram = (parameter_count * bytes_per_weight) / 1_000_000_000
    return round(base_ram + 4.0, 2)


def pricing_tier_for_ram(ram_gb: float) -> str:
    if ram_gb < 8:
        return "S"
    if ram_gb < 16:
        return "M"
    if ram_gb < 32:
        return "L"
    if ram_gb < 64:
        return "XL"
    return "XXL"


async def resolve_or_create_model(session: AsyncSession, hf_id: str) -> ModelRegistry:
    existing = await session.get(ModelRegistry, hf_id)
    if existing:
        return existing

    parameter_count = infer_parameter_count(hf_id)
    quantization = infer_quantization(hf_id)
    estimated_ram_gb = estimate_ram_gb(parameter_count, quantization)
    tier = pricing_tier_for_ram(estimated_ram_gb)
    record = ModelRegistry(
        hf_id=hf_id,
        parameter_count=parameter_count,
        quantization=quantization,
        estimated_ram_gb=estimated_ram_gb,
        pricing_tier=tier,
        credits_per_1k_tokens=TIER_PRICING[tier],
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.get(ModelRegistry, hf_id)
        if existing:
            return existing
        raise
    return record


async def list_live_models(session: AsyncSession) -> list[dict]:
    nodes = (
        await session.execute(
            select(ModelRegistry).order_by(ModelRegistry.estimated_ram_gb.asc(), ModelRegistry.hf_id.asc())
        )
    ).scalars()
    return [
        {
            "hf_id": model.hf_id,
            "estimated_ram_gb": model.estimated_ram_gb,
            "pricing_tier": model.pricing_tier,
            "credits_per_1k_tokens": model.credits_per_1k_tokens,
        }
        for model in nodes
    ]
