"""Vulture whitelist: symbols intentionally kept that static analysis flags.

Run dead-code detection with:

    vulture curlwright vulture_whitelist.py

Anything vulture reports *after* applying this whitelist is a genuinely new
dead-code candidate. Each entry below is grouped by why it is not dead.
"""

# Python runtime machinery (resolved by the interpreter, not by name lookup).
__getattr__  # curlwright/__init__.py — lazy public-export hook

# Enum members constructed dynamically via ChallengeState(assessment.outcome).
CHALLENGE  # curlwright/domain/policy.py

# Self-documenting context attached to each policy decision (read by humans,
# not at runtime).
reason  # curlwright/domain/policy.py — BypassDecision.reason

# Dataclass fields serialized into the JSON/SARIF output payload via asdict();
# consumed by output readers, so never referenced by name in Python.
body_excerpt  # BypassAssessment — failure diagnostics in the attempt payload
persistent_profile  # RuntimeMetadata — runtime metadata in --json-output
retry_delay_seconds  # RuntimeMetadata — runtime metadata in --json-output
trusted_session_before_request  # StateMetadata — state metadata in --json-output

# Per-domain bypass record persisted to bypass-state.json (written + serialized,
# asserted by tests); a human-inspectable audit trail rather than logic inputs.
last_url  # DomainBypassState
last_status  # DomainBypassState
success_count  # DomainBypassState
failure_count  # DomainBypassState
last_artifact_dir  # DomainBypassState

_ = None
_.last_url
_.last_status
_.success_count
_.failure_count
_.last_artifact_dir
