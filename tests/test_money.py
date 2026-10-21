from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from data_generator.money import ext_cents, hours_cents


def _decimal_cents(qty: float, price: float, qdp: int, pdp: int) -> int:
    q = Decimal(str(round(qty, qdp)))
    p = Decimal(str(round(price, pdp)))
    return int((q * p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def test_ext_cents_matches_decimal_half_up():
    rng = np.random.default_rng(1)
    qty = np.round(rng.uniform(0, 5000, 2000), 3)
    price = np.round(rng.uniform(0.01, 150, 2000), 4)
    got = ext_cents(qty, price)
    want = [_decimal_cents(q, p, 3, 4) for q, p in zip(qty, price, strict=True)]
    assert got.tolist() == want


def test_ext_cents_half_up_boundary():
    # 1.005 rounds up to 1.01 (float math would give 1.00)
    assert ext_cents([1.0], [1.005]).tolist() == [101]
    assert ext_cents([3.0], [0.335]).tolist() == [101]  # 1.005 -> 1.01


def test_hours_cents():
    assert hours_cents([7.5], [38.27]).tolist() == [28703]  # 287.025 -> 287.03
    assert hours_cents([0.25], [40.0]).tolist() == [1000]
