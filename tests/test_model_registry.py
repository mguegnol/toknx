from toknx_coordinator.services.model_registry import (
    estimate_ram_gb,
    infer_parameter_count,
    infer_quantization,
    pricing_tier_for_ram,
)


def test_parameter_count_inference():
    assert infer_parameter_count("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit") == 32_000_000_000


def test_quantization_inference():
    assert infer_quantization("mlx-community/Qwen2.5-Coder-7B-Instruct-4bit") == "4bit"


def test_ram_estimate_uses_runtime_overhead():
    assert estimate_ram_gb(7_000_000_000, "4bit") == 7.5
    assert estimate_ram_gb(32_000_000_000, "4bit") == 20.0


def test_pricing_tier_mapping():
    assert pricing_tier_for_ram(7.9) == "S"
    assert pricing_tier_for_ram(8.0) == "M"
    assert pricing_tier_for_ram(18.0) == "L"
