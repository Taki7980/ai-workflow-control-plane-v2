from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from .models import ContextItem
from .provider_runner import CommandProviderSpec, run_command_provider_async
from .retrieval_contracts import ProviderResult, RetrievalRequest, Retriever


@dataclass
class SyncRetrieverAdapter:
    retriever: Retriever
    @property
    def name(self) -> str:
        return self.retriever.name
    async def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        return await asyncio.to_thread(self.retriever.retrieve, request)


@dataclass
class CallableRetrieverAdapter:
    name: str
    callback: Callable[[RetrievalRequest], ProviderResult | list[ContextItem] | tuple[ContextItem, ...]]
    async def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        value = await asyncio.to_thread(self.callback, request)
        return value if isinstance(value, ProviderResult) else ProviderResult(self.name, tuple(value))


class LocalRetrieverAdapter(CallableRetrieverAdapter): pass
class CRGRetrieverAdapter(CallableRetrieverAdapter): pass
class MemoryRetrieverAdapter(CallableRetrieverAdapter): pass


@dataclass
class CommandRetrieverAdapter:
    spec: CommandProviderSpec
    source: str | None = None
    @property
    def name(self) -> str:
        return self.spec.name
    async def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        return await run_command_provider_async(self.spec, request, source=self.source or self.spec.name)


class SemanticRetrieverAdapter(CommandRetrieverAdapter): pass
class ExternalRetrieverAdapter(CommandRetrieverAdapter): pass
