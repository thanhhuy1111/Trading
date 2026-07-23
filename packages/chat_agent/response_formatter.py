"""Deterministic Vietnamese formatting of a scan_trade_opportunities tool output.

Used by `FakeLLMProvider` (so tests get fully deterministic text) and available as a
fallback formatter. Every value placed into the returned string is read directly out of
the `scan_output` dict -- which is itself a JSON-mode dump of a real `RecommendationResult`
produced by `RecommendationService` -- so nothing here can invent a number.
"""

from typing import Any, Dict, List

from packages.chat_agent.guardrails import RISK_DISCLAIMER_VI


def _format_proposal_vi(proposal: Dict[str, Any], index: int) -> str:
    take_profits = ", ".join(str(tp) for tp in proposal.get("take_profit_levels", []))
    lines = [
        f"Cơ hội {index}: {proposal.get('symbol')} — {proposal.get('side')}",
        f"- Khung phân tích: {proposal.get('timeframe')} (horizon {proposal.get('horizon_minutes')} phút)",
        f"- Vùng vào tham khảo: {proposal.get('entry_from')} - {proposal.get('entry_to')}",
        f"- Stop loss: {proposal.get('stop_loss')}",
        f"- Take profit: {take_profits}",
        f"- Xác suất có lợi nhuận ước tính: {proposal.get('probability_profit')}",
        f"- Expected gross return: {proposal.get('expected_gross_return_bps')} bps",
        f"- Chi phí ước tính: {proposal.get('estimated_cost_bps')} bps",
        f"- Expected net return: {proposal.get('expected_net_return_bps')} bps",
        f"- Risk/reward: {proposal.get('risk_reward_ratio')}",
        f"- Market regime: {proposal.get('market_regime')}",
        f"- Strategy evidence: {proposal.get('evidence_id') or 'N/A'}",
    ]
    facts = proposal.get("explanation_facts") or []
    if facts:
        lines.append("- Lý do đề xuất:")
        lines.extend(f"    - {fact}" for fact in facts)
    invalidations = proposal.get("invalidation_conditions") or []
    if invalidations:
        lines.append("- Điều kiện mất hiệu lực:")
        lines.extend(f"    - {cond}" for cond in invalidations)
    risk_flags = proposal.get("risk_flags") or []
    if risk_flags:
        lines.append(f"- Risk flags: {', '.join(risk_flags)}")
    lines.append(f"- Hết hạn lúc: {proposal.get('expires_at')}")
    return "\n".join(lines)


def format_scan_result_vietnamese(scan_output: Dict[str, Any]) -> str:
    if not scan_output:
        return (
            "Không thể tạo phần diễn giải vào lúc này. Hệ thống không phát sinh đề xuất giao dịch.\n\n"
            + RISK_DISCLAIMER_VI
        )

    status = scan_output.get("status")
    generated_at = scan_output.get("generated_at")
    symbols_evaluated = scan_output.get("symbols_evaluated") or []
    no_trade_symbols = scan_output.get("no_trade_symbols") or []
    proposals: List[Dict[str, Any]] = scan_output.get("proposals") or []

    lines = [
        f"Tôi đã quét {', '.join(symbols_evaluated) or 'các mã được yêu cầu'}.",
        f"Thời điểm dữ liệu: {generated_at}.",
    ]

    if status == "MARKET_UNAVAILABLE":
        lines.append("Dữ liệu thị trường hiện không khả dụng. Hệ thống không phát sinh đề xuất giao dịch.")
    elif status == "MARKET_DATA_STALE":
        lines.append("Dữ liệu thị trường hiện đã cũ (stale). Hệ thống không phát sinh đề xuất giao dịch.")
    elif status == "STRATEGY_NOT_APPROVED":
        lines.append(
            "Chiến lược hiện chưa được phê duyệt dựa trên bằng chứng out-of-sample "
            "(chưa đủ hoặc chưa đạt ngưỡng hiệu suất). Hệ thống không phát sinh đề xuất giao dịch."
        )
    elif status == "INSUFFICIENT_EVIDENCE":
        lines.append(
            "Chưa có mô hình dự đoán đã hiệu chỉnh (calibrated) cho các mã/khung thời gian này. "
            "Hệ thống không phát sinh đề xuất giao dịch."
        )
    elif proposals:
        lines.append(f"Hiện có {len(proposals)} cơ hội đạt điều kiện đề xuất:\n")
        for i, proposal in enumerate(proposals, start=1):
            lines.append(_format_proposal_vi(proposal, i))
            lines.append("")
    else:
        lines.append("Hiện chưa có cơ hội nào đạt điều kiện đề xuất (NO_TRADE).")

    if no_trade_symbols:
        lines.append(f"Các mã được đánh giá NO_TRADE: {', '.join(no_trade_symbols)}.")

    lines.append("")
    lines.append(RISK_DISCLAIMER_VI)

    return "\n".join(lines)
