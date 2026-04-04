SUBCREDITS_PER_CREDIT = 100_000
SUBCREDITS_PER_1K_TOKEN_PER_CREDIT = SUBCREDITS_PER_CREDIT // 1000


def credits_to_subcredits(credits: int) -> int:
    return credits * SUBCREDITS_PER_CREDIT


def tokens_to_subcredits(output_tokens: int, credits_per_1k_tokens: int) -> int:
    return max(output_tokens, 0) * credits_per_1k_tokens * SUBCREDITS_PER_1K_TOKEN_PER_CREDIT


def format_subcredits(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), SUBCREDITS_PER_CREDIT)
    if fraction == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:05d}".rstrip("0")
