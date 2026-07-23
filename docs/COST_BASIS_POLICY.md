# Cost Basis Policy Specification

## 1. Weighted Average Cost Basis
When increasing position:
$$Cost_{total\_new} = Cost_{old} + QuoteQty_{buy} + Fee_{buy}$$
$$Qty_{new} = Qty_{old} + Qty_{buy}$$
$$P_{avg\_new} = \frac{Cost_{total\_new}}{Qty_{new}}$$

When selling position:
$$Cost_{released} = Qty_{sell} \times P_{avg\_old}$$
$$Cost_{remaining} = Cost_{old} - Cost_{released}$$
$$P_{avg\_remaining} = P_{avg\_old}$$
