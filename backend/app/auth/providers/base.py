from typing import Protocol

from ..models import User


class AuthProvider(Protocol):
    name: str

    def authenticate(self, **kwargs) -> User | None: ...

    def list_providers(self) -> list[str]: ...
