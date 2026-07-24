"""Immutable, version-exact prompt registry for provider-backed agents."""

from __future__ import annotations

import hashlib
from string import Formatter
from typing import Dict, Mapping, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    template: str = Field(min_length=1)
    required_variables: Tuple[str, ...]

    @model_validator(mode="after")
    def validate_template(self) -> "PromptDefinition":
        parsed = tuple(Formatter().parse(self.template))
        if any(
            field_name is not None
            and (
                not field_name.isidentifier()
                or bool(format_spec)
                or conversion is not None
            )
            for _, field_name, format_spec, conversion in parsed
        ):
            raise ValueError("prompt placeholders must be simple identifiers")
        fields = tuple(
            field_name
            for _, field_name, _, _ in parsed
            if field_name is not None
        )
        if tuple(dict.fromkeys(fields)) != self.required_variables:
            raise ValueError("prompt variables must exactly match required_variables")
        return self

    @property
    def checksum(self) -> str:
        payload = f"{self.name}\n{self.version}\n{self.template}".encode()
        return hashlib.sha256(payload).hexdigest()

    def render(self, variables: Mapping[str, str]) -> str:
        if set(variables) != set(self.required_variables):
            raise ValueError("PROMPT_VARIABLES_MISMATCH")
        return self.template.format(**variables)


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: Dict[tuple[str, str], PromptDefinition] = {}

    def register(self, prompt: PromptDefinition) -> PromptDefinition:
        key = (prompt.name, prompt.version)
        if key in self._prompts:
            raise ValueError("PROMPT_VERSION_EXISTS")
        self._prompts[key] = prompt
        return prompt

    def get(self, name: str, version: str) -> PromptDefinition | None:
        return self._prompts.get((name, version))

    def all(self) -> Tuple[PromptDefinition, ...]:
        return tuple(
            self._prompts[key]
            for key in sorted(self._prompts)
        )
