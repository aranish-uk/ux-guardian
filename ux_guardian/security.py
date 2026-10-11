import os

from pydantic import BaseModel

SECRET_NAMES = ("TINYFISH_API_KEY", "LLM_API_KEY", "TEST_EMAIL", "TEST_PASSWORD", "GITHUB_TOKEN")


def redact(value: str) -> str:
    for name in SECRET_NAMES:
        secret = os.environ.get(name)
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def redact_data(value: object) -> object:
    """Redact string values before JSON encoding, including quotes and newlines."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, BaseModel):
        return redact_model(value)
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    return value


def redact_model[T: BaseModel](value: T) -> T:
    """Keep the model shape while redacting nested string values before rendering."""
    updates = {name: redact_data(getattr(value, name)) for name in type(value).model_fields}
    return value.model_copy(update=updates)
