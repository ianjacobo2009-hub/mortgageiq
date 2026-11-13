"""Mortgage math for Colombia (COP, E.A. rates, UVR) and the USA (USD, APR, PMI/FHA/ARM).

Every function here is pure, so the desktop app and the tests share the same numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- reference data (editable in Settings)
CO_BANKS = {"Bancolombia": 12.5, "Davivienda": 12.8, "BBVA Colombia": 12.2, "Banco de Bogotá": 12.9, "AV Villas": 13.1}
US_PRODUCTS = {  # name: (APR %, term in years, loan type)
    "30-Year Fixed": (6.8, 30, "conventional"),
    "15-Year Fixed": (6.1, 15, "conventional"),
    "FHA 30-Year": (6.5, 30, "fha"),
    "5/1 ARM": (6.3, 30, "arm"),
    "Jumbo 30-Year": (7.1, 30, "conventional"),
}
DEFAULTS = {
    "smmlv": 1_423_500,          # Colombian monthly minimum wage (2025 value; update each January)
    "uvr_inflation": 5.0,        # expected yearly inflation for UVR loans, %
    "co_closing": 2.0,           # notary, registry, appraisal, % of price
    "us_closing": 3.0,
    "us_tax": 1.1,               # property tax, % of value per year
    "us_insurance": 0.6,         # homeowners insurance, % of value per year
    "pmi": 0.8,                  # PMI, % of loan per year
    "fha_upfront": 1.75,         # FHA upfront MIP, % of base loan (financed)
    "fha_annual": 0.55,          # FHA annual MIP, % of loan per year
}


# ---------------------------------------------------------------- rates
def ea_to_monthly(ea_pct: float) -> float:
    """Colombian effective annual rate (E.A.) → effective monthly rate (decimal)."""
    return (1 + ea_pct / 100) ** (1 / 12) - 1


def monthly_to_ea(i: float) -> float:
    return ((1 + i) ** 12 - 1) * 100


def apr_to_monthly(apr_pct: float) -> float:
    """US APR is a nominal rate compounded monthly."""
    return apr_pct / 100 / 12


def payment(principal: float, i: float, n: int) -> float:
    """Level (French) payment."""
    if n <= 0:
        return 0.0
    if i == 0:
        return principal / n
    return principal * i / (1 - (1 + i) ** -n)


# ---------------------------------------------------------------- results
@dataclass
class Row:
    month: int
    payment: float      # principal + interest (pesos/dollars of that month)
    principal: float
    interest: float
    balance: float
    extra: float = 0.0  # PMI / MIP that month

    @property
    def year(self) -> int:
        return (self.month - 1) // 12 + 1


@dataclass
class Result:
    country: str                 # "CO" or "US"
    loan_type: str               # fixed, uvr, conventional, fha, arm
    price: float
    down: float
    years: int
    rate: float                  # the rate the user typed (E.A. for CO, APR for US)
    loan: float                  # amount borrowed (FHA includes financed upfront MIP)
    first_payment: float         # principal + interest, month 1
    effective_annual: float      # % per year
    schedule: list[Row] = field(default_factory=list)
    closing: float = 0.0
    tax_monthly: float = 0.0
    insurance_monthly: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def months(self) -> int:
        return len(self.schedule)

    @property
    def total_paid(self) -> float:
        return sum(r.payment for r in self.schedule)

    @property
    def total_interest(self) -> float:
        return sum(r.interest for r in self.schedule)

    @property
    def total_insurance_fees(self) -> float:
        return sum(r.extra for r in self.schedule)

    @property
    def down_pct(self) -> float:
        return self.down / self.price * 100 if self.price else 0.0

    @property
    def first_extra(self) -> float:
        return self.schedule[0].extra if self.schedule else 0.0

    @property
    def housing_payment(self) -> float:
        """What leaves the bank account in month 1: P&I + PMI/MIP (+ tax and insurance in the US)."""
        return self.first_payment + self.first_extra + self.tax_monthly + self.insurance_monthly

    @property
    def upfront(self) -> float:
        return self.down + self.closing

    def yearly(self) -> list[Row]:
        out: dict[int, Row] = {}
        for r in self.schedule:
            y = out.setdefault(r.year, Row(r.year, 0, 0, 0, 0))
            y.payment += r.payment; y.principal += r.principal; y.interest += r.interest
            y.extra += r.extra; y.balance = r.balance
        return list(out.values())


def _amortize(loan: float, rates: list[float], n: int, indexation: list[float] | None = None) -> list[Row]:
    """Amortize with a rate per month. Payment is recomputed only when the rate changes (ARM reset).

    indexation: for UVR loans, the peso value of 1 UVR each month relative to month 0. The schedule is built in
    UVR units and converted to pesos, which is how a constant-UVR-payment loan works.
    """
    rows, bal, pay, last_i = [], loan, 0.0, None
    for m in range(1, n + 1):
        i = rates[m - 1]
        if i != last_i:
            pay = payment(bal, i, n - m + 1); last_i = i
        intr = bal * i
        princ = min(pay - intr, bal)
        bal = max(0.0, bal - princ)
        f = indexation[m - 1] if indexation else 1.0
        rows.append(Row(m, (princ + intr) * f, princ * f, intr * f, bal * f))
    return rows


# ---------------------------------------------------------------- Colombia
def colombia(price: float, down: float, years: int, ea: float, uvr: bool = False,
             inflation: float = DEFAULTS["uvr_inflation"], closing_pct: float = DEFAULTS["co_closing"]) -> Result:
    """Fixed-peso loan: `ea` is the E.A. rate. UVR loan: `ea` is the spread over UVR (e.g. 7.5 means UVR + 7.5%)."""
    loan, n = price - down, years * 12
    if loan <= 0 or n <= 0 or ea <= 0:
        raise ValueError("invalid inputs")
    i = ea_to_monthly(ea)
    index = None
    notes = []
    if uvr:
        g = (1 + inflation / 100) ** (1 / 12)
        index = [g ** m for m in range(1, n + 1)]
        eff = ((1 + ea / 100) * (1 + inflation / 100) - 1) * 100
        notes.append("uvr")
    else:
        eff = ea
    sched = _amortize(loan, [i] * n, n, index)
    return Result("CO", "uvr" if uvr else "fixed", price, down, years, ea, loan, sched[0].payment, eff, sched,
                  closing=price * closing_pct / 100, notes=notes)


@dataclass
class ColombiaChecks:
    max_ltv_ok: bool
    min_down_pct: float
    is_vis: bool
    vis_cap: float
    income_ok_for_subsidy: bool | None
    ratio: float | None          # first payment / income, %
    ratio_ok: bool | None        # banks cap the first payment at 30% of household income


def colombia_checks(r: Result, income: float, smmlv: float = DEFAULTS["smmlv"]) -> ColombiaChecks:
    vis_cap = 150 * smmlv                          # VIS: up to 150 SMMLV (135 outside the large cities)
    is_vis = r.price <= vis_cap
    min_down = 20.0 if is_vis else 30.0           # banks finance up to 80% (VIS) or 70% (non-VIS)
    ratio = r.first_payment / income * 100 if income > 0 else None
    return ColombiaChecks(
        max_ltv_ok=r.down_pct >= min_down - 1e-9, min_down_pct=min_down, is_vis=is_vis, vis_cap=vis_cap,
        income_ok_for_subsidy=(income <= 4 * smmlv) if income > 0 else None,
        ratio=ratio, ratio_ok=(ratio <= 30) if ratio is not None else None)


# ---------------------------------------------------------------- USA
def usa(price: float, down: float, years: int, apr: float, loan_type: str = "conventional",
        arm_reset_apr: float | None = None, tax_pct: float = DEFAULTS["us_tax"],
        insurance_pct: float = DEFAULTS["us_insurance"], pmi_pct: float = DEFAULTS["pmi"],
        fha_upfront: float = DEFAULTS["fha_upfront"], fha_annual: float = DEFAULTS["fha_annual"],
        closing_pct: float = DEFAULTS["us_closing"]) -> Result:
    base, n = price - down, years * 12
    if base <= 0 or n <= 0 or apr <= 0:
        raise ValueError("invalid inputs")
    notes = []
    loan = base
    if loan_type == "fha":
        if down / price < 0.035 - 1e-9:
            notes.append("fha_min_down")
        loan = base * (1 + fha_upfront / 100)
    i = apr_to_monthly(apr)
    rates = [i] * n
    if loan_type == "arm":
        reset = arm_reset_apr if arm_reset_apr is not None else apr + 2.0
        rates = [i] * min(60, n) + [apr_to_monthly(reset)] * max(0, n - 60)
        notes.append("arm")
    sched = _amortize(loan, rates, n)

    # mortgage insurance, month by month
    ltv0 = base / price
    if loan_type == "fha":
        mip_months = 132 if ltv0 <= 0.90 else n     # 11 years with 10%+ down, otherwise life of loan
        prev = loan
        for r in sched:
            if r.month <= mip_months:
                r.extra = prev * fha_annual / 100 / 12
            prev = r.balance
    elif ltv0 > 0.80:
        notes.append("pmi")
        prev = loan
        for r in sched:
            if prev > 0.78 * price:                 # PMI ends automatically at 78% of the original value
                r.extra = loan * pmi_pct / 100 / 12
            prev = r.balance
    return Result("US", loan_type, price, down, years, apr, loan, sched[0].payment,
                  monthly_to_ea(i), sched, closing=price * closing_pct / 100,
                  tax_monthly=price * tax_pct / 100 / 12, insurance_monthly=price * insurance_pct / 100 / 12,
                  notes=notes)


def pmi_end_month(r: Result) -> int | None:
    paid = [x.month for x in r.schedule if x.extra > 0]
    return (paid[-1] + 1) if paid and paid[-1] < r.months else None


def us_dti(r: Result, income: float, other_debts: float = 0.0) -> tuple[float, float] | None:
    """Front-end (housing ÷ income) and back-end ((housing + other debts) ÷ income) ratios, in %."""
    if income <= 0:
        return None
    h = r.housing_payment
    return h / income * 100, (h + other_debts) / income * 100


# ---------------------------------------------------------------- rent vs buy
@dataclass
class RentBuyYear:
    year: int
    home_value: float
    buy_net_worth: float
    rent_net_worth: float


def rent_vs_buy(r: Result, rent: float, appreciation: float, rent_growth: float, invest_return: float,
                horizon: int = 30, maintenance_pct: float = 1.0, selling_pct: float = 5.0) -> tuple[list[RentBuyYear], int | None]:
    """Compare two people with the same budget.

    The buyer pays the down payment and closing costs, then the mortgage, insurance, taxes and maintenance.
    The renter invests that same upfront cash instead, pays rent, and each month invests whatever they save
    compared with the buyer (if renting costs more, the buyer invests the difference instead).
    Buyer's net worth = home value − mortgage balance − cost of selling + their own investments.
    """
    mi = (1 + invest_return / 100) ** (1 / 12) - 1
    renter = r.upfront
    buyer_side = 0.0
    out, breakeven = [], None
    for m in range(1, horizon * 12 + 1):
        value = r.price * (1 + appreciation / 100) ** (m / 12)
        row = r.schedule[m - 1] if m <= r.months else None
        own_cost = (row.payment + row.extra if row else 0.0) + r.tax_monthly + r.insurance_monthly \
            + value * maintenance_pct / 100 / 12
        rent_now = rent * (1 + rent_growth / 100) ** ((m - 1) // 12)
        renter *= 1 + mi; buyer_side *= 1 + mi
        diff = own_cost - rent_now
        if diff > 0:
            renter += diff
        else:
            buyer_side -= diff
        if m % 12 == 0:
            bal = row.balance if row else 0.0
            buy = value * (1 - selling_pct / 100) - bal + buyer_side
            out.append(RentBuyYear(m // 12, value, buy, renter))
            if breakeven is None and buy > renter:
                breakeven = m // 12
    return out, breakeven
