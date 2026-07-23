"""Deterministic Vietnamese formatting of a scan_trade_opportunities tool output.

Used by `FakeLLMProvider` (so tests get fully deterministic text) and available as a
fallback formatter. Every value placed into the returned string is read directly out of the
`scan_output` dict -- which is itself `packages.chat_agent.tool_registry`'s JSON-mode dump of
a real `RecommendationResult` produced by `BaselineRecommendationService` -- so nothing here
can invent a number.
"""

from typing import Any, Dict, List

from packages.chat_agent.guardrails import RISK_DISCLAIMER_VI

_NO_DATA_STATES = {"NO_CANDIDATE", "DATA_QUALITY_FAILED"}
_NOT_APPROVED_STATES = {"STRATEGY_NOT_APPROVED", "MODEL_NOT_AVAILABLE"}


def _format_proposal_vi(proposal: Dict[str, Any], index: int) -> str:
    lines = [
        f"Cơ hội {index}: {proposal.get('symbol')} — {proposal.get('direction')}",
        f"- Khung thời gian: {proposal.get('timeframe')}",
        f"- Giá tham chiếu vào lệnh: {proposal.get('entry_reference')}",
        f"- Stop loss: {proposal.get('stop_loss')}",
        f"- Take profit: {proposal.get('take_profit')}",
        f"- Risk/reward: {proposal.get('risk_reward_ratio')}",
        f"- Xác suất có lợi nhuận đã hiệu chỉnh: {proposal.get('calibrated_probability')}",
        f"- Expected net return: {proposal.get('expected_net_return_bps')} bps",
        f"- Chi phí ước tính (fee+spread+slippage): "
        f"{proposal.get('estimated_fee_bps')}+{proposal.get('estimated_spread_bps')}+"
        f"{proposal.get('estimated_slippage_bps')} bps",
        f"- Trạng thái evidence: {proposal.get('evidence_status')}",
        f"- Trạng thái kết quả: {proposal.get('application_result_state')}",
        f"- Rủi ro đã duyệt: {proposal.get('approved_risk_pct') or 'Chưa duyệt (research-only)'}",
    ]
    reason_codes = proposal.get("reason_codes") or []
    if reason_codes:
        lines.append(f"- Reason codes: {', '.join(reason_codes)}")
    lines.append(f"- Hết hạn lúc: {proposal.get('proposal_expiry')}")
    return "\n".join(lines)


def format_scan_result_vietnamese(scan_output: Dict[str, Any]) -> str:
    if not scan_output:
        return (
            "Không thể tạo phần diễn giải vào lúc này. Hệ thống không phát sinh đề xuất giao dịch.\n\n"
            + RISK_DISCLAIMER_VI
        )

    state = scan_output.get("application_result_state")
    generated_at = scan_output.get("generated_at")
    proposals: List[Dict[str, Any]] = scan_output.get("proposals") or []
    reason_codes = scan_output.get("reason_codes") or []

    lines = [f"Thời điểm dữ liệu: {generated_at}."]

    if proposals:
        lines.append(f"Hiện có {len(proposals)} cơ hội:\n")
        for i, proposal in enumerate(proposals, start=1):
            lines.append(_format_proposal_vi(proposal, i))
            lines.append("")
    elif state in _NO_DATA_STATES:
        lines.append("Dữ liệu thị trường hiện không khả dụng. Hệ thống không phát sinh đề xuất giao dịch.")
    elif state == "STALE_DATA":
        lines.append("Dữ liệu thị trường hiện đã cũ (stale). Hệ thống không phát sinh đề xuất giao dịch.")
    elif state in _NOT_APPROVED_STATES:
        lines.append(
            "Chiến lược hoặc mô hình hiện chưa được phê duyệt dựa trên bằng chứng out-of-sample. "
            "Hệ thống không phát sinh đề xuất giao dịch."
        )
    elif state == "INSUFFICIENT_EVIDENCE":
        lines.append(
            "Chưa có đủ bằng chứng out-of-sample đã được phê duyệt cho các mã/khung thời gian này. "
            "Hệ thống không phát sinh đề xuất giao dịch."
        )
    else:
        lines.append("Hiện chưa có cơ hội nào đạt điều kiện đề xuất (NO_TRADE).")

    if reason_codes:
        lines.append(f"Reason codes: {', '.join(reason_codes)}.")

    lines.append("")
    lines.append(RISK_DISCLAIMER_VI)

    return "\n".join(lines)
