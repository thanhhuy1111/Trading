"""Seven Phase 3 artifact registries. Each is an independent ArtifactRegistry instance so a
lookup in one can never accidentally resolve against another's entries.

Note on naming: `feature_artifact_registry` here is deliberately NOT named `feature_registry`
— that name is already `packages.features.registry.feature_registry`, the calculator
registry (e.g. "adx_14 v1.0.0" as an implementation). This registry is a different, higher
granularity: a whole named FEATURE SET (e.g. "standard_v1") as a versioned, checksummed
artifact. See docs/architecture/REGISTRY_DESIGN.md for the distinction.
"""

from packages.registries.registry import ArtifactRegistry

strategy_registry = ArtifactRegistry("strategy")
model_registry = ArtifactRegistry("model")
evidence_registry = ArtifactRegistry("evidence")
feature_artifact_registry = ArtifactRegistry("feature_set")
label_registry = ArtifactRegistry("label")
universe_registry = ArtifactRegistry("universe")
policy_registry = ArtifactRegistry("policy")
