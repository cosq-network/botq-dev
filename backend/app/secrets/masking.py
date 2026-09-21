def redact_text(text: str, secret_values: list[str], placeholder: str = "***REDACTED***") -> str:
    if not text:
        return text
    result = text
    for value in secret_values:
        if not value or len(value) < 4:
            continue
        result = result.replace(value, placeholder)
    return result


def mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def contains_secret(secret_values: list[str], text: str) -> bool:
    for value in secret_values:
        if value and len(value) >= 4 and value in text:
            return True
    return False
