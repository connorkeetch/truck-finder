"""Loan and acquisition-cost math. Standard fixed-rate amortization; every assumption is explicit."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace


def monthly_payment(principal: float, apr_pct: float, months: int) -> float:
    """Fixed monthly payment: P * r / (1 - (1 + r)^-n), with r = APR/12. Zero APR -> P/n."""
    if months <= 0:
        raise ValueError("months must be positive")
    if principal <= 0:
        return 0.0
    r = apr_pct / 100.0 / 12.0
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def max_principal(payment: float, apr_pct: float, months: int) -> float:
    """Largest amount that can be financed for a given monthly payment (inverse of monthly_payment)."""
    if months <= 0:
        raise ValueError("months must be positive")
    if payment <= 0:
        return 0.0
    r = apr_pct / 100.0 / 12.0
    if r == 0:
        return payment * months
    return payment * (1 - (1 + r) ** -months) / r


def total_interest(principal: float, apr_pct: float, months: int) -> float:
    return monthly_payment(principal, apr_pct, months) * months - max(principal, 0.0)


@dataclass
class FinanceAssumptions:
    target_monthly: float = 1000.0
    terms: list[int] = field(default_factory=lambda: [60, 72])
    aprs: list[float] = field(default_factory=lambda: [6.0])
    trade_payoff: float = 0.0
    trade_in_low: float = 0.0
    trade_in_high: float = 0.0
    cash_offer: float = 0.0
    sales_tax_rate: float = 0.0          # percent; set your local rate
    dmv_fees: float = 0.0
    doc_fee: float = 0.0
    extra_cash_down: float = 0.0
    default_transport_cost: float = 0.0
    trade_in_reduces_taxable: bool = False
    cash_sale_reduces_taxable: bool = False
    primary_scenario: str = "cash_sale"
    primary_term: int = 72
    primary_apr: float = 6.0
    current_vehicle: str = ""
    # e.g. [{"seller": "carvana", "amount": 1000, "when": "trade"}] — "trade" = only in trade-in scenarios
    discounts: list[dict] = field(default_factory=list)

    @classmethod
    def from_settings(cls, finance: dict) -> "FinanceAssumptions":
        known = {k: v for k, v in finance.items() if k in cls.__dataclass_fields__}
        return cls(**known)


SCENARIO_LABELS = {
    "trade_low": "Trade-in to dealer (low estimate)",
    "trade_high": "Trade-in to dealer (high estimate)",
    "cash_sale": "Sell current vehicle separately (cash offer)",
}


@dataclass
class ScenarioResult:
    scenario: str
    label: str
    price: float
    transport: float
    credit_value: float           # trade-in allowance or cash-offer proceeds
    payoff: float
    equity: float                 # credit_value - payoff (negative = upside down)
    taxable_amount: float
    sales_tax: float
    fees: float
    total_acquisition_cost: float  # price + tax + fees + transport (before applying equity)
    amount_financed: float
    payments: dict[str, float]          # "72@4.99" -> monthly payment
    cash_to_target: dict[str, float]    # extra cash needed to bring payment down to the target
    total_interest: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _key(term: int, apr: float) -> str:
    return f"{term}@{apr:g}"


def discount_for(a: FinanceAssumptions, seller: str | None, kind: str) -> float:
    """Seller discount that applies to this scenario (e.g. Carvana's $1,000 when you trade in)."""
    total = 0.0
    for d in a.discounts or []:
        who = (d.get("seller") or "").lower()
        if who not in ("any", (seller or "").lower()):
            continue
        if d.get("when", "always") == "trade" and not kind.startswith("trade"):
            continue
        total += float(d.get("amount") or 0)
    return total


def scenario(price: float, a: FinanceAssumptions, kind: str, transport: float | None = None,
             seller: str | None = None) -> ScenarioResult:
    """Compute one acquisition scenario for a vehicle price (after any seller discount that applies)."""
    if kind not in SCENARIO_LABELS:
        raise ValueError(f"unknown scenario {kind}")
    price = max(price - discount_for(a, seller, kind), 0.0)
    transport = a.default_transport_cost if transport is None else transport
    if kind == "cash_sale":
        credit = a.cash_offer
        reduces_tax = a.cash_sale_reduces_taxable
    else:
        credit = a.trade_in_low if kind == "trade_low" else a.trade_in_high
        reduces_tax = a.trade_in_reduces_taxable
    taxable = max(price - credit, 0.0) if reduces_tax else price
    tax = round(taxable * a.sales_tax_rate / 100.0, 2)
    fees = a.dmv_fees + a.doc_fee
    total_cost = price + tax + fees + transport
    equity = credit - a.trade_payoff
    financed = max(total_cost - equity - a.extra_cash_down, 0.0)

    payments, cash_needed, interest = {}, {}, {}
    for term in a.terms:
        for apr in a.aprs:
            k = _key(term, apr)
            payments[k] = round(monthly_payment(financed, apr, term), 2)
            cash_needed[k] = round(max(financed - max_principal(a.target_monthly, apr, term), 0.0), 2)
            interest[k] = round(total_interest(financed, apr, term), 2)
    return ScenarioResult(
        scenario=kind, label=SCENARIO_LABELS[kind], price=price, transport=transport, credit_value=credit,
        payoff=a.trade_payoff, equity=equity, taxable_amount=taxable, sales_tax=tax, fees=fees,
        total_acquisition_cost=round(total_cost, 2), amount_financed=round(financed, 2),
        payments=payments, cash_to_target=cash_needed, total_interest=interest,
    )


def all_scenarios(price: float, a: FinanceAssumptions, transport: float | None = None,
                  seller: str | None = None) -> list[ScenarioResult]:
    return [scenario(price, a, k, transport, seller) for k in SCENARIO_LABELS]


# Compare how selling your current vehicle changes the loan amount.
PAYMENT_TABLE_DEFAULTS = {"sale_from": 0.0, "sale_to": 0.0, "sale_step": 1000.0, "aprs": [6.0],
                          "term": 72, "trade_offers": []}


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def trade_offer_for(offers: list[dict], *seller_names: str | None) -> dict | None:
    """The dealer trade-in offer that applies to this vehicle's seller (ignoring spaces and punctuation)."""
    names = [_norm(n) for n in seller_names if _norm(n)]
    for o in offers or []:
        want = _norm(o.get("dealer"))
        if want and float(o.get("amount") or 0) > 0 and any(want in n or n in want for n in names):
            return o
    return None


def sale_prices(cfg: dict, limit: int = 8) -> list[float]:
    lo, hi, step = float(cfg["sale_from"]), float(cfg["sale_to"]), float(cfg["sale_step"]) or 1.0
    out = [lo]
    while out[-1] + step <= hi + 0.01 and len(out) < limit:
        out.append(out[-1] + step)
    return out


def payment_table(price: float, a: FinanceAssumptions, cfg: dict, transport: float | None = None,
                  seller: str | None = None, trade_offer: dict | None = None) -> list[dict]:
    """One row per sale price of your current vehicle (sold separately: no tax credit), plus a row for the
    seller's trade-in offer when there is one — the dealer pays off the loan and the trade lowers the taxable price
    (if 'trade_in_reduces_taxable'), which a private sale doesn't."""
    term, rows = int(cfg["term"]), []
    plans = [("sale", p, replace(a, cash_offer=p), "cash_sale") for p in sale_prices(cfg)]
    if trade_offer:
        amt = float(trade_offer["amount"])
        plans.append(("trade", amt, replace(a, trade_in_high=amt), "trade_high"))
    for kind, credit, assumptions, sc_kind in plans:
        r = scenario(price, assumptions, sc_kind, transport, seller)
        full_tax = round(r.price * a.sales_tax_rate / 100.0, 2)
        rows.append({"kind": kind, "credit": credit, "dealer": (trade_offer or {}).get("dealer") if kind == "trade" else "",
                     "cash_left": r.equity, "price": r.price, "sales_tax": r.sales_tax,
                     "tax_saved": round(full_tax - r.sales_tax, 2), "fees": r.fees, "transport": r.transport,
                     "out_the_door": r.total_acquisition_cost, "financed": r.amount_financed,
                     "payments": {float(apr): round(monthly_payment(r.amount_financed, float(apr), term), 2)
                                  for apr in cfg["aprs"]}})
        if kind == "trade":     # what a private sale would have to fetch to finance the same amount
            private = scenario(price, replace(a, cash_offer=credit), "cash_sale", transport, seller)
            rows[-1]["same_as_selling_for"] = round(credit + private.amount_financed - r.amount_financed, 2)
    return rows


def best_price(price: float | None, a: FinanceAssumptions, seller: str | None = None) -> float | None:
    """Lowest price you'd pay across scenarios after seller discounts."""
    if not price:
        return price
    return max(price - max(discount_for(a, seller, k) for k in SCENARIO_LABELS), 0.0)


def primary_summary(price: float | None, a: FinanceAssumptions, transport: float | None = None,
                    seller: str | None = None) -> dict:
    """The single scenario/term/APR shown in the inventory table."""
    if not price:
        return {"est_monthly": None, "cash_to_target": None, "amount_financed": None, "total_cost": None}
    res = scenario(price, a, a.primary_scenario, transport, seller)
    k = _key(a.primary_term, a.primary_apr)
    if k not in res.payments:  # primary term/APR not in the grid: compute directly
        pay = round(monthly_payment(res.amount_financed, a.primary_apr, a.primary_term), 2)
        cash = round(max(res.amount_financed - max_principal(a.target_monthly, a.primary_apr, a.primary_term), 0), 2)
    else:
        pay, cash = res.payments[k], res.cash_to_target[k]
    return {"est_monthly": pay, "cash_to_target": cash, "amount_financed": res.amount_financed,
            "total_cost": res.total_acquisition_cost, "sales_tax": res.sales_tax}
