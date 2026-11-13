"""MortgageIQ desktop app (PySide6 / Qt). Spanish and English."""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSlider, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import __version__
from . import finance as F
from .i18n import T

ASSETS = (Path(getattr(sys, "_MEIPASS", "")) / "assets") if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent.parent / "assets"
HOME = Path(os.environ.get("MORTGAGEIQ_HOME", Path.home() / ".mortgageiq"))
SETTINGS = HOME / "settings.json"
BG, CARD, LINE, TEXT, MUTED = "#f4f7fb", "#ffffff", "#dfe6f0", "#0f172a", "#64748b"
BLUE, GREEN, AMBER, RED = "#1a56db", "#057a55", "#b45309", "#c81e1e"

QSS = f"""
* {{ font-family: 'Helvetica Neue', 'Segoe UI', Arial, sans-serif; color: {TEXT}; }}
QMainWindow, QScrollArea, QWidget#page {{ background: {BG}; border: none; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#hero {{ font-size: 28px; font-weight: 800; }}
QLabel#h2 {{ font-size: 18px; font-weight: 700; }}
QLabel#h3 {{ font-size: 14px; font-weight: 700; }}
QLabel#kpi {{ font-size: 22px; font-weight: 800; }}
QPushButton {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; padding: 8px 14px; }}
QPushButton:hover {{ border-color: {BLUE}; }}
QPushButton:checked {{ background: {BLUE}; color: white; border-color: {BLUE}; }}
QPushButton#primary {{ background: {BLUE}; color: white; border: none; font-weight: 600; padding: 11px 22px; }}
QPushButton#primary:disabled {{ background: #9db6ea; }}
QPushButton#green {{ background: {GREEN}; color: white; border: none; font-weight: 600; padding: 11px 22px; }}
QLineEdit, QDoubleSpinBox {{ border: 1px solid {LINE}; border-radius: 9px; padding: 8px; background: white; font-size: 15px; }}
QSlider::groove:horizontal {{ height: 6px; background: #dbe3ef; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {BLUE}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: white; border: 3px solid {BLUE}; width: 16px; margin: -7px 0; border-radius: 10px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ padding: 8px 16px; color: {MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {BLUE}; border-bottom: 2px solid {BLUE}; font-weight: 600; }}
QTableWidget {{ background: white; border: 1px solid {LINE}; border-radius: 10px; gridline-color: {LINE}; }}
QHeaderView::section {{ background: #f6f9fe; color: {MUTED}; border: none; padding: 6px; font-weight: 600; }}
"""


# ---------------------------------------------------------------- settings
def load_settings() -> dict:
    s = {"values": dict(F.DEFAULTS), "co_banks": dict(F.CO_BANKS),
         "us_rates": {k: v[0] for k, v in F.US_PRODUCTS.items()}, "lang": "es"}
    try:
        d = json.loads(SETTINGS.read_text())
        for k in ("values", "co_banks", "us_rates"):
            s[k].update(d.get(k, {}))
        s["lang"] = d.get("lang", "es")
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False))


def money(x: float, country: str) -> str:
    s = f"{round(x):,}"
    return "$" + (s.replace(",", ".") if country == "CO" else s)


# ---------------------------------------------------------------- small widgets
def label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lb = QLabel(text); lb.setWordWrap(wrap)
    if name:
        lb.setObjectName(name)
    return lb


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(); f.setObjectName("card")
    lay = QVBoxLayout(f); lay.setContentsMargins(20, 18, 20, 18); lay.setSpacing(10)
    return f, lay


def badge(text: str, color: str) -> QLabel:
    lb = QLabel(text); lb.setWordWrap(True)
    c = QColor(color); rgb = f"{c.red()}, {c.green()}, {c.blue()}"
    lb.setStyleSheet(f"background: rgba({rgb}, 0.09); color: {color}; border: 1px solid rgba({rgb}, 0.35);"
                     " border-radius: 9px; padding: 8px 12px; font-weight: 600;")
    lb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    return lb


class MoneyEdit(QLineEdit):
    """Whole-number input that keeps thousands separators while typing."""
    valueChanged = Signal(float)

    def __init__(self, value: float, country: str):
        super().__init__(); self.country = country
        self.setAlignment(Qt.AlignRight)
        self.textEdited.connect(self._reformat); self.set(value)

    def value(self) -> float:
        digits = "".join(c for c in self.text() if c.isdigit())
        return float(digits) if digits else 0.0

    def set(self, v: float) -> None:
        self.setText(money(v, self.country)[1:] if v else "")

    def _reformat(self, _):
        v = self.value(); self.set(v); self.valueChanged.emit(v)


def pct_box(value: float, lo: float = 0.0, hi: float = 40.0, step: float = 0.1) -> QDoubleSpinBox:
    b = QDoubleSpinBox(); b.setRange(lo, hi); b.setDecimals(2); b.setSingleStep(step); b.setValue(value)
    b.setAlignment(Qt.AlignRight); return b


class LineChart(QWidget):
    """Two lines over the years (rent vs buy)."""

    def __init__(self, series: list[tuple[str, str, list[float]]]):
        super().__init__(); self.series = series; self.setMinimumHeight(220)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h, pad = self.width(), self.height(), 28
        vals = [v for _, _, s in self.series for v in s]
        lo, hi = min(0, min(vals)), max(vals) or 1
        n = max(len(s) for _, _, s in self.series)
        p.setPen(QPen(QColor(LINE), 1)); p.drawLine(pad, h - pad, w - 8, h - pad)
        for i, (name, color, s) in enumerate(self.series):
            path = QPainterPath()
            for k, v in enumerate(s):
                pt = QPointF(pad + k * (w - pad - 8) / max(1, n - 1), h - pad - (v - lo) / (hi - lo) * (h - 2 * pad))
                path.moveTo(pt) if k == 0 else path.lineTo(pt)
            p.setPen(QPen(QColor(color), 3)); p.drawPath(path)
            p.drawText(pad + 6, 16 + i * 16, "— " + name)
        p.setPen(QColor(MUTED)); p.drawText(pad, h - 8, "1"); p.drawText(w - 24, h - 8, str(n))


class SplitBar(QWidget):
    """Principal vs interest share of everything paid."""

    def __init__(self, a: float, b: float):
        super().__init__(); self.a, self.b = a, b; self.setFixedHeight(26)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        tot = self.a + self.b or 1; wa = self.width() * self.a / tot
        p.setPen(Qt.NoPen); p.setBrush(QColor(BLUE)); p.drawRoundedRect(0, 0, self.width(), 26, 8, 8)
        p.setBrush(QColor(AMBER)); p.drawRoundedRect(int(wa), 0, self.width() - int(wa), 26, 8, 8)
        p.setPen(QColor("white"))
        p.drawText(8, 18, f"{self.a / tot:.0%}"); p.drawText(int(wa) + 8, 18, f"{self.b / tot:.0%}")


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_settings(); self.lang = self.cfg["lang"]
        self.country: str | None = None; self.inputs: dict = {}; self.result: F.Result | None = None
        self.view = "welcome"
        self.setWindowTitle("MortgageIQ"); self.resize(980, 820)
        if (ASSETS / "icon.png").exists():
            self.setWindowIcon(QIcon(str(ASSETS / "icon.png")))
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.setCentralWidget(self.scroll)
        m = self.menuBar().addMenu("MortgageIQ")
        a = QAction("Ajustes / Settings…", self); a.triggered.connect(self.open_settings); m.addAction(a)
        self.render()

    def t(self, k: str) -> str:
        return T[self.lang][k]

    def L(self, es: str, en: str) -> str:
        return es if self.lang == "es" else en

    # ----- page frame
    def page(self) -> QVBoxLayout:
        w = QWidget(); w.setObjectName("page")
        outer = QVBoxLayout(w); outer.setContentsMargins(28, 18, 28, 28); outer.setSpacing(14)
        top = QHBoxLayout()
        brand = QPushButton("⌂  MortgageIQ"); brand.setFlat(True)
        brand.setStyleSheet("font-weight: 800; font-size: 16px; border: none; background: transparent;")
        brand.clicked.connect(self.go_home); top.addWidget(brand)
        top.addWidget(label(self.t("tagline"), "muted")); top.addStretch()
        lang = QPushButton(self.t("lang")); lang.clicked.connect(self.toggle_lang); top.addWidget(lang)
        outer.addLayout(top)
        body = QWidget(); body.setMaximumWidth(860)
        lay = QVBoxLayout(body); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(body, 1); row.addStretch()
        outer.addLayout(row); outer.addStretch()
        self.scroll.setWidget(w)
        return lay

    def render(self):
        {"welcome": self.show_welcome, "form": self.show_form, "results": self.show_results}[self.view]()

    def toggle_lang(self):
        self.lang = "en" if self.lang == "es" else "es"; self.cfg["lang"] = self.lang; save_settings(self.cfg)
        if self.view == "form":
            self.read_form()
        self.render()

    def go_home(self):
        self.view = "welcome"; self.render()

    # ----- welcome
    def show_welcome(self):
        lay = self.page(); lay.addSpacing(20)
        for txt, name in ((self.t("welcome"), "hero"), (self.t("welcome_sub"), "muted"), (self.t("choose"), "h3")):
            lb = label(txt, name); lb.setAlignment(Qt.AlignCenter); lay.addWidget(lb)
        row = QHBoxLayout(); row.setSpacing(16)
        for code, flag, name, sub, cta, obj in (("CO", "🇨🇴", "Colombia", "co_sub", "go_co", "green"),
                                                ("US", "🇺🇸", "United States", "us_sub", "go_us", "primary")):
            f, c = card()
            c.addWidget(label(f"{flag}  {name}", "h2")); c.addWidget(label(self.t(sub), "muted"))
            b = QPushButton(self.t(cta)); b.setObjectName(obj); b.clicked.connect(lambda _=False, k=code: self.start(k))
            c.addWidget(b); row.addWidget(f)
        lay.addLayout(row)
        lay.addWidget(label(self.t("disclaimer"), "muted"))

    def start(self, country: str):
        v = self.cfg["values"]
        self.country = country
        if country == "CO":
            self.inputs = dict(price=300e6, down=90e6, years=20, rate=self.cfg["co_banks"]["Bancolombia"],
                               income=0.0, debts=0.0, kind="fixed", inflation=v["uvr_inflation"], reset=None)
        else:
            r = self.cfg["us_rates"]["30-Year Fixed"]
            self.inputs = dict(price=400_000.0, down=80_000.0, years=30, rate=r, income=0.0, debts=0.0,
                               kind="conventional", inflation=0.0, reset=round(r + 2, 2))
        self.view = "form"; self.render()

    # ----- form
    def show_form(self):
        co, i = self.country == "CO", self.inputs
        lay = self.page()
        back = QPushButton(self.t("back")); back.clicked.connect(self.go_home); lay.addWidget(back, 0, Qt.AlignLeft)
        f, c = card(); lay.addWidget(f)
        c.addWidget(label(("🇨🇴  " + self.t("calc_co")) if co else ("🇺🇸  " + self.t("calc_us")), "h2"))
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignLeft); form.setVerticalSpacing(12); c.addLayout(form)

        self.w_price = MoneyEdit(i["price"], self.country); form.addRow(self.t("price"), self.w_price)
        self.w_down = MoneyEdit(i["down"], self.country)
        self.w_down_info = label("", "muted")
        dn = QVBoxLayout(); dn.addWidget(self.w_down); dn.addWidget(self.w_down_info); form.addRow(self.t("down"), dn)

        self.w_years = QSlider(Qt.Horizontal); self.w_years.setRange(5 if co else 10, 30); self.w_years.setValue(i["years"])
        self.w_years_lb = label("", "h3", False)
        yr = QHBoxLayout(); yr.addWidget(self.w_years, 1); yr.addWidget(self.w_years_lb)
        form.addRow(self.t("term"), yr)

        types = (("fixed", "uvr") if co else ("conventional", "fha", "arm"))
        self.type_group = QButtonGroup(self); tr = QHBoxLayout()
        for k in types:
            b = QPushButton(self.t(k)); b.setCheckable(True); b.setChecked(i["kind"] == k)
            b.clicked.connect(lambda _=False, kk=k: self.set_kind(kk)); self.type_group.addButton(b); tr.addWidget(b)
        tr.addStretch(); form.addRow(self.t("loan_type"), tr)
        self.w_type_hint = label("", "muted"); form.addRow("", self.w_type_hint)

        self.w_rate = pct_box(i["rate"], 0.01, 60); self.w_rate_lb = QLabel(); form.addRow(self.w_rate_lb, self.w_rate)
        self.w_extra = pct_box(i["inflation"] if co else (i["reset"] or 0), 0, 30)
        self.w_extra_lb = QLabel(); form.addRow(self.w_extra_lb, self.w_extra)
        self.w_income = MoneyEdit(i["income"], self.country); form.addRow(self.t("income"), self.w_income)
        self.w_debts = MoneyEdit(i["debts"], self.country)
        self.w_debts_lb = QLabel(self.t("debts")); form.addRow(self.w_debts_lb, self.w_debts)

        self.w_err = label("", ""); self.w_err.setStyleSheet(f"color: {RED};"); c.addWidget(self.w_err)
        self.w_go = QPushButton(self.t("calculate")); self.w_go.setObjectName("primary"); self.w_go.clicked.connect(self.calculate)
        c.addWidget(self.w_go, 0, Qt.AlignRight)
        for w in (self.w_price, self.w_down):
            w.valueChanged.connect(lambda _: self.refresh_form())
        self.w_years.valueChanged.connect(lambda _: self.refresh_form())
        self.refresh_form()

    def set_kind(self, k: str):
        self.read_form(); old = self.inputs["kind"]; self.inputs["kind"] = k
        if self.country == "CO" and k != old:          # UVR loans quote a spread over inflation, not a full rate
            self.w_rate.setValue(7.5 if k == "uvr" else self.cfg["co_banks"]["Bancolombia"])
        if self.country == "US" and k == "fha":
            self.w_rate.setValue(self.cfg["us_rates"]["FHA 30-Year"])
        if self.country == "US" and k == "arm":
            self.w_rate.setValue(self.cfg["us_rates"]["5/1 ARM"]); self.w_extra.setValue(self.cfg["us_rates"]["5/1 ARM"] + 2)
        self.refresh_form()

    def refresh_form(self):
        co, kind = self.country == "CO", self.inputs["kind"]
        price, down = self.w_price.value(), self.w_down.value()
        self.w_years_lb.setText(f"{self.w_years.value()} {self.t('years')}")
        pct = down / price * 100 if price else 0
        if co:
            vis = price <= 150 * self.cfg["values"]["smmlv"]
            need = 20 if vis else 30
            ok = pct >= need
            note = self.L(f"{pct:.1f}% del valor · {'VIS' if vis else 'no VIS'}: los bancos prestan hasta el {100 - need}%",
                          f"{pct:.1f}% of value · {'VIS' if vis else 'non-VIS'}: banks lend up to {100 - need}%")
        else:
            ok = pct >= (3.5 if kind == "fha" else 20)
            note = self.L(f"{pct:.1f}% del valor", f"{pct:.1f}% of value") + (
                "" if pct >= 20 else (" · FHA: 3.5% min" if kind == "fha" else " · " + self.L("menos de 20%: paga PMI", "under 20%: PMI applies")))
        self.w_down_info.setText(("✓ " if ok else "⚠ ") + note)
        self.w_down_info.setStyleSheet(f"color: {GREEN if ok else AMBER};")
        hints = {"fixed": self.L("La cuota es igual todos los meses.", "The payment is the same every month."),
                 "uvr": self.L("La cuota empieza más baja pero sube cada mes con la inflación.",
                               "The payment starts lower but rises every month with inflation."),
                 "conventional": self.L("Préstamo normal. Con menos de 20% de inicial pagas PMI.",
                                        "Standard loan. With under 20% down you pay PMI."),
                 "fha": self.L("Inicial desde 3.5%. Paga MIP inicial (financiado) y anual.",
                               "From 3.5% down. Upfront MIP (financed) plus annual MIP."),
                 "arm": self.L("Tasa fija 5 años, luego cambia. Pon la tasa que esperas después.",
                               "Fixed for 5 years, then it resets. Enter the rate you expect after.")}
        self.w_type_hint.setText(hints[kind])
        self.w_rate_lb.setText(self.t("rate_uvr" if kind == "uvr" else ("rate_co" if co else "rate_us")))
        show_extra = kind in ("uvr", "arm")
        self.w_extra_lb.setText(self.t("inflation" if co else "arm_reset"))
        self.w_extra.setVisible(show_extra); self.w_extra_lb.setVisible(show_extra)
        self.w_debts.setVisible(not co); self.w_debts_lb.setVisible(not co)
        bad = down >= price and price > 0
        self.w_err.setText(self.t("down_over") if bad else "")
        self.w_go.setEnabled(price > 0 and not bad)

    def read_form(self):
        i = self.inputs
        i.update(price=self.w_price.value(), down=self.w_down.value(), years=self.w_years.value(),
                 rate=self.w_rate.value(), income=self.w_income.value(), debts=self.w_debts.value())
        if self.country == "CO":
            i["inflation"] = self.w_extra.value()
        else:
            i["reset"] = self.w_extra.value()

    def compute(self, rate: float | None = None, years: int | None = None, kind: str | None = None) -> F.Result:
        i, v = self.inputs, self.cfg["values"]
        rate, years, kind = rate or i["rate"], years or i["years"], kind or i["kind"]
        if self.country == "CO":
            return F.colombia(i["price"], i["down"], years, rate, uvr=kind == "uvr", inflation=i["inflation"],
                              closing_pct=v["co_closing"])
        return F.usa(i["price"], i["down"], years, rate, kind, arm_reset_apr=i["reset"] if kind == "arm" else None,
                     tax_pct=v["us_tax"], insurance_pct=v["us_insurance"], pmi_pct=v["pmi"],
                     fha_upfront=v["fha_upfront"], fha_annual=v["fha_annual"], closing_pct=v["us_closing"])

    def calculate(self):
        self.read_form()
        try:
            self.result = self.compute()
        except ValueError:
            self.w_err.setText(self.L("Revisa los valores.", "Check the values.")); return
        self.view = "results"; self.render()

    # ----- results
    def show_results(self):
        r, co = self.result, self.country == "CO"
        lay = self.page()
        top = QHBoxLayout()
        back = QPushButton(self.t("back")); back.clicked.connect(lambda: (setattr(self, "view", "form"), self.render()))
        new = QPushButton(self.t("new")); new.clicked.connect(self.go_home)
        pdf = QPushButton(self.t("pdf")); pdf.setObjectName("primary"); pdf.clicked.connect(self.save_pdf)
        top.addWidget(back); top.addStretch(); top.addWidget(new); top.addWidget(pdf); lay.addLayout(top)
        tabs = QTabWidget(); lay.addWidget(tabs)
        tabs.addTab(self.tab_summary(r, co), self.t("summary"))
        tabs.addTab(self.tab_amort(r), self.t("amort"))
        tabs.addTab(self.tab_compare(co), self.t("compare"))
        tabs.addTab(self.tab_rentbuy(r, co), self.t("rentbuy"))
        lay.addWidget(label(self.t("disclaimer"), "muted"))

    def kpis(self, items: list[tuple[str, str, str]]) -> QWidget:
        w = QWidget(); g = QGridLayout(w); g.setContentsMargins(0, 0, 0, 0); g.setSpacing(10)
        for k, (name, val, color) in enumerate(items):
            f, c = card(); c.addWidget(label(name, "muted"))
            v = label(val, "kpi"); v.setStyleSheet(f"color: {color};"); c.addWidget(v)
            g.addWidget(f, k // 4, k % 4)
        return w

    def tab_summary(self, r: F.Result, co: bool) -> QWidget:
        m = lambda x: money(x, self.country)
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(12); lay.setContentsMargins(0, 12, 0, 0)
        pay_name = self.t("payment_first") if r.loan_type in ("uvr", "arm") else self.t("payment")
        lay.addWidget(self.kpis([(pay_name, m(r.first_payment), BLUE), (self.t("total"), m(r.total_paid), TEXT),
                                 (self.t("interest"), m(r.total_interest), AMBER),
                                 (self.t("eff"), f"{r.effective_annual:.2f}%", TEXT)]))
        for note in self.insights(r, co):
            lay.addWidget(badge(*note))

        f, c = card(); lay.addWidget(f)
        c.addWidget(label(self.L("Detalle", "Breakdown"), "h3"))
        rows = [(self.t("loan"), m(r.loan)), (self.t("down"), f"{m(r.down)}  ({r.down_pct:.1f}%)"),
                (self.t("closing") + f" (~{self.cfg['values']['co_closing' if co else 'us_closing']:.0f}%)", m(r.closing)),
                (self.t("upfront"), m(r.upfront))]
        if not co:
            ins = self.t("mip") if r.loan_type == "fha" else self.t("pmi")
            rows += [(self.t("payment") + " (P&I)", m(r.first_payment)), (ins, m(r.first_extra)),
                     (self.t("tax"), m(r.tax_monthly)), (self.t("insurance"), m(r.insurance_monthly)),
                     (self.t("piti"), m(r.housing_payment))]
        g = QGridLayout(); c.addLayout(g)
        for k, (a, b) in enumerate(rows):
            g.addWidget(label(a, "muted"), k, 0); vb = label(b, "", False); vb.setAlignment(Qt.AlignRight); g.addWidget(vb, k, 1)
        c.addWidget(label(self.L("Capital vs intereses de todo lo pagado", "Principal vs interest of everything paid"), "h3"))
        c.addWidget(SplitBar(r.loan if r.loan_type != "uvr" else r.total_paid - r.total_interest, r.total_interest))
        lay.addStretch()
        return w

    def insights(self, r: F.Result, co: bool) -> list[tuple[str, str]]:
        i, m, out = self.inputs, (lambda x: money(x, self.country)), []
        if co:
            ch = F.colombia_checks(r, i["income"], self.cfg["values"]["smmlv"])
            if not ch.max_ltv_ok:
                out.append((self.L(f"Para esta vivienda los bancos suelen pedir mínimo {ch.min_down_pct:.0f}% de cuota inicial y tienes {r.down_pct:.1f}%.",
                                   f"For this home, banks usually require at least {ch.min_down_pct:.0f}% down and you have {r.down_pct:.1f}%."), RED))
            if ch.ratio is not None:
                col = GREEN if ch.ratio <= 25 else (AMBER if ch.ratio <= 30 else RED)
                out.append((self.L(f"La primera cuota es el {ch.ratio:.1f}% de tus ingresos. Por ley, en vivienda no puede pasar del 30%"
                                   + (" (te faltan ingresos de unos " + m(r.first_payment / 0.30) + " al mes)." if not ch.ratio_ok else "."),
                                   f"The first payment is {ch.ratio:.1f}% of your income. By law, a housing loan payment can't exceed 30%"
                                   + (f" (you'd need about {m(r.first_payment / 0.30)} a month)." if not ch.ratio_ok else ".")), col))
            if ch.is_vis:
                sub = "" if ch.income_ok_for_subsidy is None else (
                    self.L(" Tus ingresos están dentro del tope de 4 salarios mínimos para subsidios (Mi Casa Ya, cajas de compensación).",
                           " Your income is within the 4-minimum-wage cap for subsidies (Mi Casa Ya, family funds).")
                    if ch.income_ok_for_subsidy else
                    self.L(" Tus ingresos pasan de 4 salarios mínimos, así que no aplicarías a los subsidios.",
                           " Your income is above 4 minimum wages, so subsidies wouldn't apply."))
                out.append((self.L(f"Precio dentro del tope VIS ({m(ch.vis_cap)}, 150 SMMLV).", f"Price is within the VIS cap ({m(ch.vis_cap)}, 150 minimum wages).")
                            + sub + self.L(" Confirma la convocatoria vigente con Fonvivienda y tu banco.", " Confirm current calls with Fonvivienda and your bank."), GREEN))
            if r.loan_type == "uvr":
                last = r.schedule[-1].payment
                fx = self.compute(kind="fixed", rate=F.monthly_to_ea(F.ea_to_monthly(r.effective_annual)))
                out.append((self.L(f"UVR: la cuota arranca en {m(r.first_payment)} y, con {i['inflation']:.1f}% de inflación, termina cerca de {m(last)}. "
                                   f"En total pagarías {m(r.total_paid)}; un crédito en pesos a la tasa equivalente ({r.effective_annual:.2f}% E.A.) costaría {m(fx.total_paid)}.",
                                   f"UVR: the payment starts at {m(r.first_payment)} and, with {i['inflation']:.1f}% inflation, ends near {m(last)}. "
                                   f"Total paid {m(r.total_paid)}; a peso loan at the equivalent rate ({r.effective_annual:.2f}% E.A.) would cost {m(fx.total_paid)}."), AMBER))
        else:
            dti = F.us_dti(r, i["income"], i["debts"])
            if dti:
                front, back = dti
                col = GREEN if front <= 28 and back <= 36 else (AMBER if back <= 43 else RED)
                out.append((self.L(f"Vivienda (PITI) = {front:.1f}% de tus ingresos (guía: 28%). Con otras deudas = {back:.1f}% (guía: 36%, la mayoría de prestamistas llega a 43%).",
                                   f"Housing (PITI) = {front:.1f}% of income (guideline 28%). With other debts = {back:.1f}% (guideline 36%; most lenders cap near 43%)."), col))
            if "pmi" in r.notes:
                end = F.pmi_end_month(r)
                out.append((self.L(f"Pagas PMI de {m(r.first_extra)}/mes hasta que el saldo baje al 78% del valor original"
                                   + (f" (mes {end}, año {(end - 1) // 12 + 1})." if end else "."),
                                   f"You pay {m(r.first_extra)}/mo of PMI until the balance falls to 78% of the original value"
                                   + (f" (month {end}, year {(end - 1) // 12 + 1})." if end else ".")), AMBER))
            if r.loan_type == "fha":
                life = all(x.extra > 0 for x in r.schedule)
                out.append((self.L(f"FHA: el MIP inicial ({m(r.loan - (r.price - r.down))}) se suma al préstamo y el MIP anual dura "
                                   + ("toda la vida del crédito (inicial menor al 10%)." if life else "11 años."),
                                   f"FHA: upfront MIP ({m(r.loan - (r.price - r.down))}) is added to the loan and annual MIP lasts "
                                   + ("for the life of the loan (under 10% down)." if life else "11 years.")), AMBER))
                if "fha_min_down" in r.notes:
                    out.append((self.L("FHA pide mínimo 3.5% de inicial.", "FHA requires at least 3.5% down."), RED))
            if r.loan_type == "arm" and r.months > 60:
                after = r.schedule[60].payment
                out.append((self.L(f"ARM: {m(r.first_payment)} los primeros 5 años; si la tasa sube a {i['reset']:.2f}%, pasa a {m(after)} desde el mes 61.",
                                   f"ARM: {m(r.first_payment)} for the first 5 years; if the rate resets to {i['reset']:.2f}%, it becomes {m(after)} from month 61."),
                            RED if after > r.first_payment * 1.15 else AMBER))
        yrs = r.yearly(); cross = next((y.month for y in yrs if y.principal > y.interest), None)
        out.append((self.L(f"El primer año, el {yrs[0].interest / (yrs[0].principal + yrs[0].interest):.0%} de lo que pagas son intereses."
                           + (f" Desde el año {cross} abonas más a capital que a intereses." if cross else ""),
                           f"In year one, {yrs[0].interest / (yrs[0].principal + yrs[0].interest):.0%} of what you pay is interest."
                           + (f" From year {cross} on, more goes to principal than to interest." if cross else "")), BLUE))
        return out

    def table(self, headers: list[str], rows: list[list[str]], highlight: dict[int, str] | None = None) -> QTableWidget:
        tb = QTableWidget(len(rows), len(headers)); tb.setHorizontalHeaderLabels(headers)
        tb.verticalHeader().setVisible(False); tb.setEditTriggers(QTableWidget.NoEditTriggers)
        tb.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for a, row in enumerate(rows):
            for b, val in enumerate(row):
                it = QTableWidgetItem(val); it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if b else Qt.AlignLeft | Qt.AlignVCenter)
                if highlight and a in highlight:
                    it.setBackground(QColor(highlight[a]))
                tb.setItem(a, b, it)
        return tb

    def tab_amort(self, r: F.Result) -> QWidget:
        m = lambda x: money(x, self.country)
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 12, 0, 0)
        sw = QHBoxLayout(); grp = QButtonGroup(w)
        holder = QVBoxLayout()
        has_extra = r.total_insurance_fees > 0

        def build(monthly: bool):
            while holder.count():
                holder.takeAt(0).widget().deleteLater()
            data = r.schedule if monthly else r.yearly()
            hdr = [self.t("month" if monthly else "year"), self.t("payment"), self.t("principal"), self.t("interest")] \
                + ([self.t("extra")] if has_extra else []) + [self.t("balance")]
            rows = [[str(x.month), m(x.payment), m(x.principal), m(x.interest)] + ([m(x.extra)] if has_extra else []) + [m(x.balance)]
                    for x in data]
            tb = self.table(hdr, rows); tb.setMinimumHeight(460); holder.addWidget(tb)

        for k, (name, monthly) in enumerate(((self.t("annual"), False), (self.t("monthly"), True))):
            b = QPushButton(name); b.setCheckable(True); b.setChecked(k == 0); grp.addButton(b); sw.addWidget(b)
            b.clicked.connect(lambda _=False, mm=monthly: build(mm))
        sw.addStretch(); lay.addLayout(sw); lay.addLayout(holder); build(False)
        return w

    def tab_compare(self, co: bool) -> QWidget:
        m = lambda x: money(x, self.country)
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 12, 0, 0)
        rows = []
        if co:
            kind = "fixed"
            lay.addWidget(label(self.L(f"Mismo crédito en pesos a {self.inputs['years']} años, con la tasa de referencia de cada banco (E.A.).",
                                       f"Same peso loan over {self.inputs['years']} years at each bank's reference rate (E.A.)."), "muted"))
            for bank, rate in self.cfg["co_banks"].items():
                rows.append((bank, f"{rate:.2f}% E.A.", self.compute(rate=rate, kind=kind)))
            if self.inputs["kind"] == "fixed" and self.inputs["rate"] not in self.cfg["co_banks"].values():
                rows.append((self.t("yours"), f"{self.inputs['rate']:.2f}% E.A.", self.result))
        else:
            lay.addWidget(label(self.L("Cada producto con su propio plazo e incluye PMI/MIP. El ARM supone que la tasa sube 2 puntos en el año 6.",
                                       "Each product at its own term, including PMI/MIP. The ARM assumes the rate rises 2 points in year 6."), "muted"))
            saved = self.inputs["reset"]
            for name, (_, years, kind) in F.US_PRODUCTS.items():
                rate = self.cfg["us_rates"][name]; self.inputs["reset"] = rate + 2
                rows.append((name, f"{rate:.2f}% APR · {years}y", self.compute(rate=rate, years=years, kind=kind)))
            self.inputs["reset"] = saved
        totals = [x[2].total_paid + x[2].total_insurance_fees for x in rows]
        best, worst = totals.index(min(totals)), totals.index(max(totals))
        tb = self.table([self.t("lender"), self.t("rate"), self.t("payment_first") if not co else self.t("payment"),
                         self.t("total"), self.t("interest")],
                        [[n, rt, m(res.first_payment + res.first_extra), m(totals[k]), m(res.total_interest)]
                         for k, (n, rt, res) in enumerate(rows)], {best: "#def7ec", worst: "#fde2e2"})
        tb.setMinimumHeight(240); lay.addWidget(tb)
        lay.addWidget(badge(self.t("cheapest").format(x=m(max(totals) - min(totals))), GREEN))
        lay.addStretch()
        return w

    def tab_rentbuy(self, r: F.Result, co: bool) -> QWidget:
        m = lambda x: money(x, self.country)
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 12, 0, 0)
        f, c = card(); lay.addWidget(f)
        form = QFormLayout(); c.addLayout(form)
        rent = MoneyEdit(r.price * (0.005 if co else 0.0055), self.country)
        appr = pct_box(5.0 if co else 3.5, 0, 20); growth = pct_box(5.0 if co else 3.0, 0, 20)
        ret = pct_box(9.0 if co else 7.0, 0, 30)
        form.addRow(self.t("rent"), rent); form.addRow(self.t("appreciation"), appr)
        form.addRow(self.t("rent_growth"), growth); form.addRow(self.t("returns"), ret)
        c.addWidget(label(self.L("Compara a dos personas con el mismo dinero: quien compra paga inicial, gastos, cuota, seguros, impuestos y 1% de mantenimiento al año; "
                                 "quien arrienda invierte la inicial y lo que se ahorre cada mes. Al vender se descuenta un 5%.",
                                 "Compares two people with the same money: the buyer pays down payment, closing, mortgage, insurance, taxes and 1% a year of maintenance; "
                                 "the renter invests the down payment and whatever they save each month. Selling costs 5%."), "muted"))
        out = QVBoxLayout(); lay.addLayout(out)

        def update():
            while out.count():
                it = out.takeAt(0); it.widget().deleteLater()
            years, be = F.rent_vs_buy(r, rent.value(), appr.value(), growth.value(), ret.value())
            out.addWidget(badge(self.t("buy_wins").format(y=be) if be else self.t("rent_wins"), GREEN if be else AMBER))
            out.addWidget(LineChart([(self.t("buy_nw"), BLUE, [y.buy_net_worth for y in years]),
                                     (self.t("rent_nw"), AMBER, [y.rent_net_worth for y in years])]))
            pick = [y for y in years if y.year in (5, 10, 15, 20, 25, 30)]
            tb = self.table([self.t("year"), self.t("home_value"), self.t("buy_nw"), self.t("rent_nw")],
                            [[str(y.year), m(y.home_value), m(y.buy_net_worth), m(y.rent_net_worth)] for y in pick])
            tb.setMinimumHeight(220); out.addWidget(tb)

        rent.valueChanged.connect(lambda _: update())
        for b in (appr, growth, ret):
            b.valueChanged.connect(lambda _: update())
        update()
        return w

    # ----- PDF
    def save_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t("pdf"), str(Path.home() / "MortgageIQ.pdf"), "PDF (*.pdf)")
        if not path:
            return
        r, m = self.result, (lambda x: money(x, self.country))
        rows = [(self.t("price"), m(r.price)), (self.t("down"), f"{m(r.down)} ({r.down_pct:.1f}%)"), (self.t("loan"), m(r.loan)),
                (self.t("term"), f"{r.years} {self.t('years')}"), (self.t("rate"), f"{r.rate:.2f}%"),
                (self.t("loan_type"), self.t(r.loan_type)), (self.t("payment_first"), m(r.first_payment)),
                (self.t("total"), m(r.total_paid)), (self.t("interest"), m(r.total_interest)),
                (self.t("eff"), f"{r.effective_annual:.2f}%"), (self.t("upfront"), m(r.upfront))]
        if self.country == "US":
            rows.append((self.t("piti"), m(r.housing_payment)))
        tr = "".join(f"<tr><td style='color:#64748b;padding:4px 16px 4px 0'>{html.escape(a)}</td><td><b>{html.escape(b)}</b></td></tr>" for a, b in rows)
        notes = "".join(f"<li>{html.escape(n)}</li>" for n, _ in self.insights(r, self.country == "CO"))
        yr = "".join(f"<tr><td>{y.month}</td><td>{m(y.payment)}</td><td>{m(y.principal)}</td><td>{m(y.interest)}</td><td>{m(y.balance)}</td></tr>"
                     for y in r.yearly())
        doc = QTextDocument()
        doc.setHtml(f"<h1 style='color:{BLUE}'>MortgageIQ — {'Colombia' if self.country == 'CO' else 'USA'}</h1>"
                    f"<table>{tr}</table><h3>{self.L('Observaciones', 'Notes')}</h3><ul>{notes}</ul>"
                    f"<h3>{self.t('amort')}</h3><table cellpadding='3'><tr><th>{self.t('year')}</th><th>{self.t('payment')}</th>"
                    f"<th>{self.t('principal')}</th><th>{self.t('interest')}</th><th>{self.t('balance')}</th></tr>{yr}</table>"
                    f"<p style='color:#64748b'>{html.escape(self.t('disclaimer'))}</p>")
        pr = QPrinter(QPrinter.HighResolution); pr.setOutputFormat(QPrinter.PdfFormat); pr.setOutputFileName(path)
        doc.print_(pr)

    # ----- settings
    def open_settings(self):
        d = QDialog(self); d.setWindowTitle(self.t("settings")); lay = QVBoxLayout(d)
        form = QFormLayout(); lay.addLayout(form)
        v = self.cfg["values"]
        smmlv = MoneyEdit(v["smmlv"], "CO")
        form.addRow(self.L("Salario mínimo (SMMLV) — actualízalo cada enero", "Colombian minimum wage (SMMLV) — update each January"), smmlv)
        boxes = {}
        names = {"uvr_inflation": self.L("Inflación UVR por defecto %", "Default UVR inflation %"),
                 "co_closing": self.L("Gastos de cierre Colombia %", "Colombia closing costs %"),
                 "us_closing": self.L("Gastos de cierre EE. UU. %", "US closing costs %"),
                 "us_tax": self.L("Impuesto predial EE. UU. % al año", "US property tax % per year"),
                 "us_insurance": self.L("Seguro de vivienda EE. UU. % al año", "US homeowners insurance % per year"),
                 "pmi": "PMI % / year", "fha_upfront": "FHA upfront MIP %", "fha_annual": "FHA annual MIP %"}
        for k, n in names.items():
            boxes[k] = pct_box(v[k], 0, 30); form.addRow(n, boxes[k])
        banks = {}
        for b, rate in self.cfg["co_banks"].items():
            banks[b] = pct_box(rate, 0, 40); form.addRow(f"🇨🇴 {b} (E.A. %)", banks[b])
        us = {}
        for p, rate in self.cfg["us_rates"].items():
            us[p] = pct_box(rate, 0, 20); form.addRow(f"🇺🇸 {p} (APR %)", us[p])
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); lay.addWidget(bb)
        bb.rejected.connect(d.reject); bb.accepted.connect(d.accept)
        if d.exec():
            v["smmlv"] = smmlv.value() or F.DEFAULTS["smmlv"]
            for k, b in boxes.items():
                v[k] = b.value()
            for k, b in banks.items():
                self.cfg["co_banks"][k] = b.value()
            for k, b in us.items():
                self.cfg["us_rates"][k] = b.value()
            save_settings(self.cfg)
            if self.view == "results":
                self.result = self.compute()
            if self.view == "form":
                self.read_form()
            self.render()


def main():
    app = QApplication(sys.argv); app.setApplicationName("MortgageIQ"); app.setApplicationVersion(__version__)
    app.setStyleSheet(QSS)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
