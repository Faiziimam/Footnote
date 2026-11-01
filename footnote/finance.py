"""Small-business money: categorise transactions, monthly profit & loss, invoices, runway.

Categories come from RULES (first match wins; yours first, then these defaults) and are applied when READ, so
teaching a new rule instantly re-categorises all history. Nothing here is tax or accounting advice.
"""
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from . import metrics
from .store import atomic_write

DEFAULT_RULES = {
    "rent": "Rent", "lease": "Rent", "payroll": "Salaries", "salary": "Salaries", "wages": "Salaries", "contractor": "Contractors",
    "upwork": "Contractors", "fiverr": "Contractors", "aws": "Hosting & software", "amazon web": "Hosting & software",
    "google cloud": "Hosting & software", "azure": "Hosting & software", "digitalocean": "Hosting & software", "github": "Hosting & software",
    "vercel": "Hosting & software", "netlify": "Hosting & software", "notion": "Software", "slack": "Software", "figma": "Software",
    "adobe": "Software", "zoom": "Software", "google workspace": "Software", "microsoft": "Software", "stripe fee": "Payment fees",
    "paypal fee": "Payment fees", "processing fee": "Payment fees", "bank fee": "Bank fees", "facebook ads": "Advertising",
    "meta ads": "Advertising", "google ads": "Advertising", "linkedin ads": "Advertising", "advert": "Advertising",
    "insurance": "Insurance", "irs": "Taxes", "hmrc": "Taxes", "vat": "Taxes", "tax": "Taxes", "uber": "Travel", "lyft": "Travel",
    "airline": "Travel", "hotel": "Travel", "airbnb": "Travel", "legal": "Professional services", "attorney": "Professional services",
    "accountant": "Professional services", "bookkeep": "Professional services", "restaurant": "Meals", "coffee": "Meals",
    "electric": "Utilities", "internet": "Utilities", "phone": "Utilities", "refund": "Refunds",
    "invoice": "Sales", "payment from": "Sales", "client": "Sales", "payout": "Sales", "shopify": "Sales", "subscription revenue": "Sales",
}


def rules(cfg):
    """Your rules first (dict order is priority), then the built-in ones you haven't overridden."""
    mine = {k.lower(): v for k, v in ((cfg or {}).get("finance", {}) or {}).get("rules", {}).items()}
    return {**mine, **{k: v for k, v in DEFAULT_RULES.items() if k not in mine}}


def categorize(entry, rl):
    if entry.get("cat"):
        return entry["cat"]
    d = (entry.get("desc") or "").lower()
    for k, v in rl.items():
        if k in d:
            return v
    return "Uncategorized income" if entry["name"] == "revenue" else "Uncategorized"


# ------------------------------------------------------------------ invoices
def _inv_path(vault):
    return Path(vault) / "_invoices.json"


def invoices(vault):
    try:
        return json.loads(_inv_path(vault).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def add_invoice(vault, client, amount, due, currency="", note=""):
    items = invoices(vault)
    iid = f"INV-{len(items) + 1:03d}"
    items.append({"id": iid, "client": client.strip(), "amount": metrics.to_number(amount), "currency": (currency or "").upper(),
                  "issued": dt.date.today().isoformat(), "due": due, "status": "sent", "paid_on": "", "note": note})
    atomic_write(_inv_path(vault), json.dumps(items, indent=1))
    return iid


def mark_paid(vault, iid, date=None):
    items = invoices(vault)
    for i in items:
        if i["id"].upper() == iid.upper():
            i["status"], i["paid_on"] = "paid", metrics.parse_date(date)
            atomic_write(_inv_path(vault), json.dumps(items, indent=1))
            return i
    raise ValueError(f"There is no invoice {iid}. List them with: footnote invoice list")


def aging(vault, today=None):
    today = today or dt.date.today()
    open_ = [i for i in invoices(vault) if i["status"] == "sent"]
    over = [i for i in open_ if i["due"] and i["due"] < today.isoformat()]
    return {"open": open_, "overdue": over, "total": sum(i["amount"] for i in open_), "overdue_total": sum(i["amount"] for i in over)}


# ------------------------------------------------------------------ P&L
def has_data(vault, entries):
    return bool(invoices(vault)) or any(e.get("desc") or e.get("cat") for e in entries)


def render(vault, cfg, today=None):
    today = today or dt.date.today()
    entries = [e for e in metrics.read(vault) if e["name"] in ("revenue", "expenses")]
    base, rates = metrics.settings(cfg)
    rl = rules(cfg)
    o = ["# Finance", "", "_Categories come from your rules (teach one: `footnote categorize \"aws\" \"Hosting\"`). Not tax or accounting advice._", ""]
    if entries:
        units = {}
        for e in entries:
            u = (e.get("unit") or "").upper()
            if u:
                units[u] = units.get(u, 0) + 1
        primary = base or (max(units, key=units.get) if units else "")
        use, skipped = [], 0
        for e in entries:
            u = (e.get("unit") or "").upper() or primary
            v = e["value"]
            if u != primary:
                if base and u in rates:
                    v = v * rates[u]
                else:
                    skipped += 1
                    continue
            use.append((e, v))
        months = [(today.replace(day=1) - dt.timedelta(days=31 * i)).strftime("%Y-%m") for i in range(5, -1, -1)]
        months = sorted(set((today.replace(day=15) - dt.timedelta(days=30 * i)).strftime("%Y-%m") for i in range(5, -1, -1)))
        grid = defaultdict(lambda: defaultdict(float))
        for e, v in use:
            grid[(e["name"], categorize(e, rl))][e["date"][:7]] += v
        o += [f"## Profit & loss by month{f' ({primary})' if primary else ''}", "", "| | " + " | ".join(months) + " | Total |", "|---|" + "---|" * (len(months) + 1)]
        tot = {"revenue": defaultdict(float), "expenses": defaultdict(float)}
        for kind, title in (("revenue", "Income"), ("expenses", "Expenses")):
            rows = sorted(((c, m) for (k, c), m in grid.items() if k == kind), key=lambda x: -sum(x[1].values()))
            o.append(f"| **{title}** |" + " |" * (len(months) + 1))
            for c, m in rows:
                for mo in months:
                    tot[kind][mo] += m.get(mo, 0)
                o.append(f"| {c} | " + " | ".join(metrics.fmt(m.get(mo, 0)) if m.get(mo) else "" for mo in months) + f" | {metrics.fmt(sum(m.get(mo, 0) for mo in months))} |")
            o.append(f"| **Total {title.lower()}** | " + " | ".join(f"**{metrics.fmt(tot[kind][mo])}**" for mo in months) + f" | **{metrics.fmt(sum(tot[kind].values()))}** |")
        prof = [tot["revenue"][mo] - tot["expenses"][mo] for mo in months]
        o += ["| **Profit** | " + " | ".join(f"**{metrics.fmt(p)}**" for p in prof) + f" | **{metrics.fmt(sum(prof))}** |", ""]
        if skipped:
            o += [f"⚠ {skipped} transaction(s) in other currencies are not included. Set exchange rates: `footnote currency {primary or 'USD'} --rate EUR=1.08`", ""]
        unc = defaultdict(float)
        for e, v in use:
            if categorize(e, rl).startswith("Uncategorized"):
                unc[(e.get("desc") or "(no description)")[:50]] += v
        if unc:
            o += ["## Needs a category", "", "_Teach me once and every past and future transaction like it is sorted._", ""] + [
                f"- {d} — {metrics.fmt(v)}  → `footnote categorize \"{d.split()[0].lower()}\" \"Category\"`" for d, v in sorted(unc.items(), key=lambda x: -abs(x[1]))[:10]] + [""]
        mets = metrics.summarize(metrics.read(vault), today, base, rates)
        cb = mets.get("cash_balance")
        exp3 = sum(v for (k, c), m in grid.items() if k == "expenses" for mo, v in m.items() if mo in months[-3:]) / 3
        if cb and exp3 > 0:
            o += ["## Runway", "", f"Cash {metrics.fmt(cb['latest'])} ÷ average monthly spend {metrics.fmt(exp3)} (last 3 months) = **{cb['latest'] / exp3:.1f} months**.", ""]
    ag = aging(vault, today)
    inv = invoices(vault)
    if inv:
        o += ["## Invoices", "", f"**Unpaid:** {len(ag['open'])} totalling {metrics.fmt(ag['total'])} · **Overdue:** {len(ag['overdue'])} totalling {metrics.fmt(ag['overdue_total'])}", "",
              "| Invoice | Client | Amount | Due | Status |", "|---|---|---|---|---|"]
        for i in sorted(inv, key=lambda x: (x["status"] == "paid", x["due"] or "")):
            late = i["status"] == "sent" and i["due"] and i["due"] < today.isoformat()
            o.append(f"| {i['id']} | {i['client']} | {metrics.fmt(i['amount'])} {i['currency']} | {i['due']} | "
                     f"{'⚠ overdue ' + str((today - dt.date.fromisoformat(i['due'])).days) + 'd' if late else i['status']} |")
        o.append("")
    if len(o) <= 4:
        o.append("_No transactions or invoices yet. Import a bank export (`footnote metrics-import bank.csv`) or add an invoice (`footnote invoice add --client Acme --amount 1200 --due 2026-12-01`)._")
    return "\n".join(o) + "\n"
