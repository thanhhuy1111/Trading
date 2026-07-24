"""Provider-neutral structured-output contracts and deterministic mock."""

from __future__ import annotations

from enum import Enum
from typing import Generic, Optional, Protocol, Tuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.common.immutable import FrozenMapping

OutputT = TypeVar("OutputT", bound=BaseModel)


class LLMProviderStatus(str, Enum):
    SUCCESS = "SUCCESS"
    CONFIGURED = "CONFIGURED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    ERROR = "ERROR"


class ProviderHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: LLMProviderStatus
    provider: str
    model_id: Optional[str] = None
    reason_codes: Tuple[str, ...] = ()


class StructuredLLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1)
    prompt_name: str
    prompt_version: str
    variables: FrozenMapping[str, str]


class LLMCallTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    provider: str
    model_id: str
    served_model_version: Optional[str] = None
    prompt_name: str
    prompt_version: str
    prompt_checksum: str
    attempts: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)


class StructuredLLMResult(BaseModel, Generic[OutputT]):
    model_config = ConfigDict(frozen=True)

    status: LLMProviderStatus
    output: Optional[OutputT] = None
    telemetry: LLMCallTelemetry
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> "StructuredLLMResult[OutputT]":
        if self.status == LLMProviderStatus.SUCCESS:
            if self.output is None or self.reason_codes:
                raise ValueError("successful provider result must contain only valid output")
        elif self.output is not None or not self.reason_codes:
            raise ValueError("failed provider result cannot contain output")
        return self


class StructuredLLMProvider(Protocol):
    async def generate(
        self,
        request: StructuredLLMRequest,
        output_model: type[OutputT],
    ) -> StructuredLLMResult[OutputT]: ...
