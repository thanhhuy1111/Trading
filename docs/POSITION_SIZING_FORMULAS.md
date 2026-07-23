# Position Sizing Formulas Specification

## 1. Conservative Entry Price
$$P_{entry\_conservative} = P_{ref} \times \left(1 + \frac{Slippage_{bps}}{10000}\right)$$

## 2. Stop Distance & Risk Budget
$$StopDistance = P_{entry\_conservative} - P_{stop}$$
$$Budget_{adjusted} = NAV \times RiskPerTrade_{pct} \times Conf_{weighted}$$

## 3. Quantity Caps & Round Down
$$Qty_{raw} = \frac{Budget_{adjusted}}{StopDistance}$$
$$Qty_{pre\_round} = \min(Qty_{raw}, Qty_{cash}, Qty_{symbol\_cap}, Qty_{total\_exp\_cap})$$
$$ApprovedQty = \lfloor Qty_{pre\_round} / StepSize \rfloor \times StepSize$$

## 4. Actual Risk Verification
$$Risk_{actual} = ApprovedQty \times StopDistance \le Budget_{adjusted}$$
