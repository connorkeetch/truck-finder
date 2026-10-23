import pytest

from rivian_finder import finance
from rivian_finder.finance import (FinanceAssumptions, all_scenarios, max_principal, monthly_payment, primary_summary,
                                   scenario, total_interest)


def sample_assumptions(**overrides):
    """Fictional worked-example inputs; production defaults carry no trade or tax assumptions."""
    values = dict(target_monthly=800, terms=[60, 66, 72], aprs=[4.49, 4.99], primary_apr=4.99,
                  trade_payoff=10000, trade_in_low=20000, trade_in_high=25000, cash_offer=22000,
                  sales_tax_rate=8, dmv_fees=400, trade_in_reduces_taxable=True)
    values.update(overrides)
    return FinanceAssumptions(**values)


def test_standard_amortization_matches_closed_form():
    # $50,000 at 4.99% APR for 72 months; reference computed with 40-digit Decimal arithmetic.
    assert monthly_payment(50000, 4.99, 72) == pytest.approx(805.0147, abs=1e-3)
    assert monthly_payment(50000, 4.49, 60) == pytest.approx(931.92, abs=0.01)


def test_zero_apr_is_straight_division():
    assert monthly_payment(36000, 0, 60) == 600
    assert max_principal(600, 0, 60) == 36000


def test_max_principal_is_inverse_of_payment():
    for apr in (4.49, 4.99, 7.0):
        for n in (60, 66, 72):
            p = max_principal(800, apr, n)
            assert monthly_payment(p, apr, n) == pytest.approx(800, abs=1e-6)


def test_total_interest():
    assert total_interest(50000, 4.99, 72) == pytest.approx(805.0147 * 72 - 50000, abs=0.1)


def test_invalid_term():
    with pytest.raises(ValueError):
        monthly_payment(1000, 5, 0)


def test_cash_sale_does_not_get_trade_in_tax_credit():
    a = sample_assumptions()
    s = scenario(60000, a, "cash_sale")
    assert s.taxable_amount == 60000
    assert s.sales_tax == pytest.approx(4800.00)              # 8% of the full price
    assert s.total_acquisition_cost == pytest.approx(65200)   # + $400 DMV
    assert s.equity == pytest.approx(12000)
    assert s.amount_financed == pytest.approx(53200)
    # Payment and additional cash references use independent 40-digit Decimal calculations.
    assert s.payments["72@4.99"] == pytest.approx(856.54, abs=0.01)
    assert s.cash_to_target["72@4.99"] == pytest.approx(3511.47, abs=0.01)


def test_dealer_trade_in_reduces_taxable_amount_when_enabled():
    a = sample_assumptions()
    s = scenario(60000, a, "trade_low")
    assert s.taxable_amount == 40000
    assert s.sales_tax == pytest.approx(3200, abs=0.01)
    assert s.amount_financed == pytest.approx(53600, abs=0.01)


def test_trade_in_tax_credit_can_be_disabled():
    a = sample_assumptions(trade_in_reduces_taxable=False)
    assert scenario(60000, a, "trade_high").taxable_amount == 60000


def test_cash_sale_credit_toggle_is_explicit():
    a = sample_assumptions(cash_sale_reduces_taxable=True)
    assert scenario(60000, a, "cash_sale").taxable_amount == 38000


def test_negative_equity_increases_amount_financed():
    a = sample_assumptions(trade_payoff=30000, trade_in_low=20000)
    s = scenario(50000, a, "trade_low")
    assert s.equity == -10000
    assert s.amount_financed == pytest.approx(62800)


def test_transport_and_fees_included_in_total_cost():
    a = sample_assumptions(doc_fee=300)
    s = scenario(50000, a, "cash_sale", transport=1200)
    assert s.total_acquisition_cost == pytest.approx(55900)


def test_grid_covers_every_term_and_apr():
    a = sample_assumptions()
    s = scenario(55000, a, "cash_sale")
    assert set(s.payments) == {f"{t}@{r:g}" for t in (60, 66, 72) for r in (4.49, 4.99)}
    assert len(all_scenarios(55000, a)) == 3


def test_cash_needed_is_zero_when_under_target():
    a = sample_assumptions()
    assert scenario(30000, a, "cash_sale").cash_to_target["72@4.99"] == 0


def test_primary_summary_handles_missing_price():
    assert primary_summary(None, FinanceAssumptions())["est_monthly"] is None


def test_payment_table_matches_the_hand_worked_example():
    a = FinanceAssumptions(trade_payoff=10000, sales_tax_rate=0, dmv_fees=0)
    cfg = {**finance.PAYMENT_TABLE_DEFAULTS, "sale_from": 24000, "sale_to": 26000, "aprs": [4.5, 5.0]}
    rows = finance.payment_table(64000, a, cfg, transport=0)
    assert [r["credit"] for r in rows] == [24000, 25000, 26000]
    assert [(r["cash_left"], r["financed"]) for r in rows] == [(14000, 50000), (15000, 49000), (16000, 48000)]
    assert rows[0]["payments"] == {4.5: 793.70, 5.0: 805.25}
    assert rows[2]["payments"] == {4.5: 761.95, 5.0: 773.04}


def test_trade_in_offer_row_saves_sales_tax():
    a = FinanceAssumptions(trade_payoff=10000, sales_tax_rate=8, dmv_fees=400, trade_in_reduces_taxable=True)
    offer = finance.trade_offer_for([{"dealer": "ExampleMotors", "amount": 24000}], "Example Motors Inc", "")
    assert offer and finance.trade_offer_for([{"dealer": "ExampleMotors", "amount": 24000}], "Other Dealer") is None
    cfg = {**finance.PAYMENT_TABLE_DEFAULTS, "sale_from": 24000, "sale_to": 26000}
    rows = finance.payment_table(60000, a, cfg, transport=0, trade_offer=offer)
    trade = rows[-1]
    assert trade["kind"] == "trade" and trade["cash_left"] == 14000
    assert trade["tax_saved"] == 1920.0                                # 24,000 × 8% not taxed
    assert rows[0]["financed"] == 51200.0
    assert trade["financed"] == 49280.0 == rows[0]["financed"] - 1920.0  # same $24k credit as the private sale row
    assert trade["same_as_selling_for"] == 25920.0


def test_sale_prices_steps_and_cap():
    assert finance.sale_prices({"sale_from": 24000, "sale_to": 26000, "sale_step": 1000}) == [24000, 25000, 26000]
    assert len(finance.sale_prices({"sale_from": 0, "sale_to": 99999, "sale_step": 100})) == 8
