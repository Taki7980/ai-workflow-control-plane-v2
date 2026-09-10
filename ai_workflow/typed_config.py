from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class ControlPlaneConfig(Mapping[str, Any]):
    """Recursively immutable, mapping-compatible control-plane configuration."""

    _data: Mapping[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ControlPlaneConfig:
        if not isinstance(data, Mapping):
            raise TypeError("control-plane configuration must be a mapping")
        return cls(_freeze(dict(data)))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    @property
    def version(self) -> int:
        return int(self._data["version"])

    @property
    def context(self) -> Mapping[str, Any]:
        return self._data["context"]

    @property
    def execution(self) -> Mapping[str, Any]:
        return self._data["execution"]

    @property
    def workspace(self) -> Mapping[str, Any]:
        return self._data["workspace"]

    @property
    def memory(self) -> Mapping[str, Any]:
        return self._data["memory"]

    @property
    def budgets(self) -> Mapping[str, Any]:
        return self._data["budgets"]

    @property
    def models(self) -> Mapping[str, Any]:
        return self._data["models"]

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._data)
