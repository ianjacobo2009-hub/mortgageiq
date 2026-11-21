import pytest

from mortgageiq.finance import (apr_to_monthly, colombia, colombia_checks, ea_to_monthly, monthly_to_ea, payment,
                                pmi_end_month, rent_vs_buy, us_dti, usa)


def test_ea_round_trip():
    assert monthly_to_ea(ea_to_monthly(12.5)) == pytest.approx(12.5)
    assert ea_to_monthly(12.5) == pytest.approx(0.009863, abs=1e-6)  # not 12.5 / 12 = 1.0417%


def test_colombia_fixed_uses_ea_correctly():
    r = colombia(300_000_000, 90_000_000, 20, 12.5)
    assert r.loan == 210_000_000
    assert r.first_payment == pytest.approx(payment(210e6, ea_to_monthly(12.5), 240))
    # an early prototype treated 12.5 as nominal and charged more
    assert r.first_payment < payment(210e6, 0.125 / 12, 240)
    assert r.effective_annual == pytest.approx(12.5)
    assert r.schedule[-1].balance == pytest.approx(0, abs=1e-3)


def test_colombia_uvr_payment_rises_with_inflation():
    r = colombia(300e6, 90e6, 20, 7.5, uvr=True, inflation=5)
    assert r.schedule[12].payment > r.schedule[0].payment
    assert r.schedule[12].payment / r.schedule[0].payment == pytest.approx(1.05)
    fixed = colombia(300e6, 90e6, 20, 12.5)
    assert r.first_payment < fixed.first_payment          # starts lower...
    assert r.total_paid > 0 and r.schedule[-1].balance == pytest.approx(0, abs=1e-3)
    assert r.effective_annual == pytest.approx((1.075 * 1.05 - 1) * 100)


def test_colombia_checks():
    r = colombia(180e6, 36e6, 20, 12.5)
    c = colombia_checks(r, income=4_000_000, smmlv=1_423_500)
    assert c.is_vis and c.min_down_pct == 20 and c.max_ltv_ok
    assert c.income_ok_for_subsidy is True
    assert c.ratio == pytest.approx(r.first_payment / 4e6 * 100)
    big = colombia(600e6, 120e6, 20, 12.5)
    cb = colombia_checks(big, 0)
    assert not cb.is_vis and cb.min_down_pct == 30 and not cb.max_ltv_ok and cb.ratio is None


def test_usa_conventional_pmi_drops_at_78_percent():
    r = usa(400_000, 40_000, 30, 6.8)
    assert r.first_payment == pytest.approx(payment(360_000, apr_to_monthly(6.8), 360))
    assert "pmi" in r.notes and r.first_extra > 0
    end = pmi_end_month(r)
    assert end is not None
    assert r.schedule[end - 2].balance <= 0.78 * 400_000 < r.schedule[end - 3].balance
    assert usa(400_000, 80_000, 30, 6.8).first_extra == 0


def test_usa_fha_and_arm():
    f = usa(300_000, 10_500, 30, 6.5, "fha")
    assert f.loan == pytest.approx(289_500 * 1.0175)
    assert all(x.extra > 0 for x in f.schedule)               # <10% down: MIP for the life of the loan
    f10 = usa(300_000, 30_000, 30, 6.5, "fha")
    assert f10.schedule[131].extra > 0 and f10.schedule[132].extra == 0
    assert "fha_min_down" in usa(300_000, 5_000, 30, 6.5, "fha").notes
    a = usa(400_000, 80_000, 30, 6.3, "arm", arm_reset_apr=8.3)
    assert a.schedule[60].payment > a.schedule[59].payment
    assert a.schedule[-1].balance == pytest.approx(0, abs=1e-3)


def test_dti_includes_taxes_and_other_debts():
    r = usa(400_000, 80_000, 30, 6.8)
    front, back = us_dti(r, 10_000, 500)
    assert front == pytest.approx(r.housing_payment / 100)
    assert back == pytest.approx(front + 5)
    assert r.housing_payment > r.first_payment


def test_rent_vs_buy():
    r = colombia(300e6, 90e6, 20, 12.5)
    cheap_rent, be = rent_vs_buy(r, 500_000, 6, 4, 9)
    assert be is None and cheap_rent[-1].rent_net_worth > cheap_rent[-1].buy_net_worth
    years, be2 = rent_vs_buy(r, 3_000_000, 6, 5, 9)
    assert be2 is not None and len(years) == 30


def test_invalid():
    with pytest.raises(ValueError):
        colombia(100, 200, 20, 12)
