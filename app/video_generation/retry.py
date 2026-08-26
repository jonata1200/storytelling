def exponential_backoff_seconds(attempt: int, base_seconds: int = 2, cap_seconds: int = 300) -> int:
    if attempt <= 0:
        return base_seconds
    delay = base_seconds * (2 ** (attempt - 1))
    return int(min(cap_seconds, delay))
