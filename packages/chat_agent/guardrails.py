"""Prompt-injection detection, forbidden-claim filtering, and secret redaction.

These are enforced in CODE, not just in the system prompt text -- an LLM can be talked
out of following prompt instructions, but it cannot talk its way past a Python `in`
check the orchestrator runs on its own tool-call decisions and on the final answer text.
"""

import re
from typing import List

RISK_DISCLAIMER_VI = (
    "Đây là thông tin nghiên cứu định lượng, không phải lời khuyên đầu tư và không đảm bảo lợi nhuận. "
    "Giao dịch tiền điện tử có rủi ro mất vốn. Hệ thống không tự động đặt lệnh thật."
)

# Section 21 / 4 of the implementation plans: wording the final answer must never contain.
FORBIDDEN_CLAIM_PATTERNS_VI: List[str] = [
    "chắc chắn sinh lời",
    "đảm bảo có lãi",
    "đảm bảo tăng",
    "không thể thua",
    "lệnh an toàn tuyệt đối",
    "nên all-in",
    "an toàn tuyệt đối",
]
FORBIDDEN_CLAIM_PATTERNS_EN: List[str] = [
    "guaranteed profit",
    "guaranteed to win",
    "cannot lose",
    "100% safe trade",
    "go all in",
]
FORBIDDEN_CLAIM_PATTERNS = FORBIDDEN_CLAIM_PATTERNS_VI + FORBIDDEN_CLAIM_PATTERNS_EN

SAFE_FALLBACK_ANSWER_VI = (
    "Không thể tạo phần diễn giải vào lúc này. Hệ thống không phát sinh đề xuất giao dịch."
)

# Patterns a user message must never be allowed to steer the system into. Matching one of
# these does not mean the whole message is discarded -- it means the orchestrator refuses
# to let the match influence tool selection/execution and answers with a fixed refusal.
PROMPT_INJECTION_PATTERNS_VI: List[str] = [
    r"b[oỏ]\s*qua\s+risk\s+governor",
    r"đặt\s+lệnh\s+ngay",
    r"tự\s+đặt\s+lệnh",
    r"d[uù]ng\s+to[àa]n\s+b[oộ]\s+s[oố]\s+d[uư]",
    r"b[aậ]t\s+live\s+trading",
    r"ti[eế]t\s+l[oộ]\s+api\s+key",
    r"d[uù]ng\s+api\s+secret",
    r"g[oọ]i\s+url\s+n[aà]y",
    r"ch[aạ]y\s+l[eệ]nh\s+shell",
]
PROMPT_INJECTION_PATTERNS_EN: List[str] = [
    r"ignore\s+(the\s+)?risk\s+(governor|system)",
    r"place\s+the\s+order\s+now",
    r"use\s+all\s+(available\s+)?balance",
    r"enable\s+live\s+trading",
    r"reveal\s+(the\s+)?api\s+key",
    r"call\s+this\s+(arbitrary\s+)?url",
    r"run\s+this\s+shell\s+command",
    r"ignore\s+(previous|prior|all)\s+instructions",
    r"you\s+are\s+now\s+in\s+(developer|admin|debug)\s+mode",
]
_INJECTION_REGEX = re.compile(
    "|".join(PROMPT_INJECTION_PATTERNS_VI + PROMPT_INJECTION_PATTERNS_EN), re.IGNORECASE
)
_FORBIDDEN_CLAIM_REGEX = re.compile(
    "|".join(re.escape(p) for p in FORBIDDEN_CLAIM_PATTERNS), re.IGNORECASE
)

# Matches common LLM API key shapes so they can never leak into a log line, even if a
# provider error message or a user message happens to contain one.
_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Google API key shape
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # generic "sk-..." shaped secret
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?"),
]


def detect_prompt_injection(user_text: str) -> List[str]:
    """Returns the list of matched injection patterns (empty if none)."""
    return [m.group(0) for m in _INJECTION_REGEX.finditer(user_text)]


def contains_forbidden_claim(text: str) -> List[str]:
    return [m.group(0) for m in _FORBIDDEN_CLAIM_REGEX.finditer(text)]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def enforce_output_safety(text: str) -> str:
    """Final safety net on any text about to be shown to a user: if it slipped past the
    prompt and still contains a forbidden profit-guarantee claim, replace it with the
    fixed safe fallback rather than forwarding an unsafe claim.
    """
    if contains_forbidden_claim(text):
        return SAFE_FALLBACK_ANSWER_VI
    return text
