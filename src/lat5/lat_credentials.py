from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


class CredentialsError(RuntimeError):
    pass


@dataclass(frozen=True)
class KiwoomCredentials:
    appkey: str = field(repr=False)
    secretkey: str = field(repr=False)


def _required(values: dict, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CredentialsError(f"missing {key}")
    cleaned = value.strip()
    if "받은_" in cleaned or cleaned.startswith("${"):
        raise CredentialsError(f"placeholder value for {key}")
    return cleaned


def load_credentials(path: str | Path) -> KiwoomCredentials:
    source = Path(path).resolve()
    if not source.is_file():
        raise CredentialsError(f".env file missing: {source}")
    values = dotenv_values(source)
    return KiwoomCredentials(
        _required(values, "LAT5_KIWOOM_APPKEY"),
        _required(values, "LAT5_KIWOOM_SECRETKEY"),
    )
