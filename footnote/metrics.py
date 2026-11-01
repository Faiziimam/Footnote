"""Numbers that matter (sales, visitors, spend, hours, anything). Free-form: any name works.

Two behaviours: "sum" metrics add up over time (revenue, orders, visitors); "latest" metrics are gauges
(cash balance, subscribers). Entries with a `ref` (an order id) are de-duplicated, so re-importing is safe.
"""
import csv
import datetime as dt
import json
import re
import urllib.parse
import uuid
from .mirrors.http import call
from .mirrors.base import MirrorError
from . import config
from . import profiles

FILE = "_metrics.jsonl"
SUM_WORDS = ("revenue", "income", "sales", "orders", "visitors", "visits", "views", "signups", "sign-ups", "leads",
             "refunds", "expenses", "spend", "cost", "hours", "downloads", "posts", "clicks", "invoiced", "churn")
BARS = "▁▂▃▄▅▆▇█"


def norm_name(n):
    return re.sub(r"[^a-z0-9]+", "_", str(n).strip().lower()).strip("_")


def default_kind(name):
    for p in profiles.PROFILES.values():
        for m in p["metrics"]:
            if m[0] == name:
                return m[2]
    return "sum" if any(w in name for w in SUM_WORDS) else "latest"


def parse_date(s):
    s = str(s or "").strip()
    if not s:
        return dt.date.today().isoformat()
    if re.fullmatch(r"\d{9,11}", s):
        return dt.datetime.fromtimestamp(int(s), dt.timezone.utc).date().isoformat()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S %z", "%m/%d/%Y", "%d/%m/%Y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s[:len(s) if "%z" in fmt else 25], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return dt.date.today().isoformat()


def to_number(s):
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"[^\d.,\-()]", "", str(s))
    neg = t.startswith("(") or t.startswith("-")
    t = t.strip("()-")
    if t.count(",") and t.count("."):
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif t.count(",") == 1 and len(t.split(",")[1]) != 3:
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        raise ValueError(f"not a number: {s!r}")
    return -v if neg else v


def read(vault, include_deleted=False):
    """Entries in order. Corrections are tombstones appended to the ledger, so history is never lost."""
    p = vault / FILE
    raw = []
    if p.exists():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            e.setdefault("id", f"L{n}")
            raw.append(e)
    dead = {e["target"] for e in raw if e.get("op") == "delete"}
    return [e for e in raw if e.get("op") != "delete" and (include_deleted or e["id"] not in dead)]


def delete(vault, mid):
    ids = {e["id"] for e in read(vault)}
    if mid not in ids:
        raise ValueError(f"There is no figure {mid}. List them with: footnote metrics")
    with open(vault / FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"op": "delete", "target": mid}) + "\n")


def fix(vault, mid, value):
    old = next((e for e in read(vault) if e["id"] == mid), None)
    if not old:
        raise ValueError(f"There is no figure {mid}. List them with: footnote metrics")
    delete(vault, mid)
    new = {**old, "value": to_number(value), "id": uuid.uuid4().hex[:8], "source": old.get("source", "") + " (corrected)"}
    with open(vault / FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(new) + "\n")
    return new["id"]


def add(vault, name, value, date=None, unit="", source="manual", ref="", kind=None, _seen=None, desc="", cat=""):
    name = norm_name(name)
    if not name:
        raise ValueError("a metric needs a name")
    value = to_number(value)
    vault.mkdir(parents=True, exist_ok=True)
    if ref:
        seen = _seen if _seen is not None else {(e["name"], e.get("ref")) for e in read(vault) if e.get("ref")}
        if (name, ref) in seen:
            return False
        seen.add((name, ref))
    e = {"id": uuid.uuid4().hex[:8], "name": name, "value": value, "date": parse_date(date), "unit": unit.upper() if unit else "",
         "source": source, "ref": ref, "kind": kind or default_kind(name), **({"desc": " ".join(str(desc).split())[:100]} if desc else {}),
         **({"cat": cat} if cat else {})}
    with open(vault / FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(e) + "\n")
    return True


def spark(vals):
    if not vals or max(vals) == min(vals):
        return BARS[0] * len(vals) if vals and max(vals) == 0 else (BARS[3] * len(vals))
    lo, hi = min(vals), max(vals)
    return "".join(BARS[int((v - lo) / (hi - lo) * 7)] for v in vals)


def settings(cfg):
    c = (cfg or {}).get("currency", {}) or {}
    return c.get("base", ""), {k.upper(): float(v) for k, v in (c.get("rates") or {}).items()}


def _usable(es, base, rates):
    """Pick the entries that can honestly be added together. -> (list of (entry, value), unit, excluded{unit: total})"""
    units = {}
    for e in es:
        u = (e.get("unit") or "").upper()
        if u:
            units[u] = units.get(u, 0) + abs(e["value"])
    if base and rates:
        out, excl = [], {}
        for e in es:
            u = (e.get("unit") or "").upper() or base
            if u == base:
                out.append((e, e["value"]))
            elif u in rates:
                out.append((e, e["value"] * rates[u]))
            else:
                excl[u] = excl.get(u, 0) + e["value"]
        return out, base, excl
    primary = base or (max(units, key=units.get) if units else "")
    out, excl = [], {}
    for e in es:
        u = (e.get("unit") or "").upper() or primary
        if u == primary:
            out.append((e, e["value"]))
        else:
            excl[u] = excl.get(u, 0) + e["value"]
    return out, primary, excl


def summarize(entries, today=None, base="", rates=None):
    today = today or dt.date.today()
    by = {}
    for e in entries:
        by.setdefault(e["name"], []).append(e)
    out = {}
    for name, es in by.items():
        kind = es[-1].get("kind") or default_kind(name)
        use, unit, excluded = _usable(es, base, rates or {})
        if not use:
            use, unit = [(e, e["value"]) for e in es], ""
        days = {}
        for e, v in use:
            days.setdefault(e["date"], []).append(v)
        def within(a, b):
            return sum(sum(v) for d, v in days.items() if a <= (today - dt.date.fromisoformat(d)).days < b)
        ordered = sorted(days)
        if kind == "sum":
            series = [sum(days.get((today - dt.timedelta(days=i)).isoformat(), [0])) for i in range(13, -1, -1)]
            latest = within(0, 30)
        else:
            series = [days[d][-1] for d in ordered[-14:]]
            latest = days[ordered[-1]][-1]
        out[name] = {"kind": kind, "unit": unit, "total": sum(v for _, v in use), "excluded": excluded,
                     "converted": bool(base and rates), "last7": within(0, 7), "prev7": within(7, 14),
                     "last30": within(0, 30), "latest": latest, "series": series, "first": ordered[0],
                     "last": ordered[-1], "count": len(es), "sources": sorted({e.get("source", "") for e in es})}
    return out


def derived(s):
    out = []
    for key, label, a, op, b, unit in profiles.DERIVED:
        if a in s and b in s:
            ua, ub = s[a]["unit"], s[b]["unit"]
            if op in ("-",) and ua and ub and ua != ub:
                continue                      # never subtract EUR from USD
            x = s[a]["last30"] if s[a]["kind"] == "sum" else s[a]["latest"]
            y = s[b]["last30"] if s[b]["kind"] == "sum" else s[b]["latest"]
            if op == "-":
                v = x - y
            elif y:
                v = x / y * (100 if unit == "%" else 1)
                if key == "runway_months":
                    v = x / y          # balance / monthly expenses
            else:
                continue
            out.append((label, round(v, 2), unit))
    return out


def fmt(v, unit=""):
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1e7 else f"{v:,.0f}"
    return f"{s}{unit}"


def render(vault, cfg=None):
    s = summarize(read(vault), None, *settings(cfg))
    out = ["# Metrics", "", "_Numbers added by you, your AI tools, imports and connected sources._", ""]
    if not s:
        out.append("_No numbers yet. Tell an agent “visitors this week were 340”, or run `footnote metrics-import file.csv`._")
    else:
        out += ["| Metric | Last 30 days / latest | Last 7d | Previous 7d | Trend (14 days) | Source |", "|---|---|---|---|---|---|"]
        for n, m in sorted(s.items()):
            out.append(f"| {n} | {fmt(m['latest'], ' ' + m['unit'] if m['unit'] else '')}{' ⚠ excludes ' + ', '.join(f'{fmt(v)} {u}' for u, v in m['excluded'].items()) if m['excluded'] else ''} | {fmt(m['last7'])} | {fmt(m['prev7'])} | "
                       f"{spark(m['series'])} | {', '.join(m['sources'])} |")
        d = derived(s)
        if d:
            out += ["", "## Calculated", ""] + [f"- {l}: **{fmt(v, u)}**" for l, v, u in d]
    (vault / "Metrics.md").write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- CSV import (any export)
ALIAS = {
    "date": ["date", "created at", "created", "order date", "paid at", "created (utc)", "day", "timestamp", "time", "posted"],
    "id": ["order id", "order number", "name", "id", "number", "transaction id", "reference"],
    "total": ["total", "order total", "gross", "amount received", "gross sales", "net sales", "sales", "revenue"],
    "amount": ["amount", "value", "debit/credit", "net amount"],
    "status": ["financial status", "status", "payment status"],
    "currency": ["currency", "currency code", "presentment currency"],
    "desc": ["description", "memo", "details", "payee", "narrative", "reference", "transaction description", "merchant", "note"],
    "metric": ["metric", "name_of_metric", "measure"], "value": ["value", "amount", "count"],
}


def _find(head, key):
    low = {h.lower().strip(): h for h in head}
    for a in ALIAS[key]:
        if a in low:
            return low[a]
    return None


def import_csv(vault, path, mode="auto", source=None, default_unit=""):
    """-> {"mode":..., "added": n, "skipped": n}. mode: auto | sales | bank | wide | long"""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("That file has no rows.")
    head = list(rows[0].keys())
    source = source or f"csv:{path.name if hasattr(path, 'name') else str(path).split('/')[-1]}"
    dcol, icol = _find(head, "date"), _find(head, "id")
    mcol = _find(head, "metric")
    vcol = _find(head, "value") if mcol else None
    tcol, acol, scol = _find(head, "total"), _find(head, "amount"), _find(head, "status")
    ccol, desc_col = _find(head, "currency"), _find(head, "desc")
    if mode == "auto":
        if mcol and vcol:
            mode = "long"
        elif tcol and dcol:
            mode = "sales"
        elif acol and dcol:
            vals = [to_number(r[acol]) for r in rows if str(r.get(acol, "")).strip()]
            mode = "bank" if any(v < 0 for v in vals) else "sales"
            tcol = tcol or acol
        elif dcol:
            mode = "wide"
        else:
            raise ValueError("I couldn't recognise this file. It needs a date column plus either totals/amounts, "
                             "numeric columns, or 'metric,value' columns.")
    cur, dsc = default_unit, ""
    added = skipped = 0
    seen = {(e["name"], e.get("ref")) for e in read(vault) if e.get("ref")}

    def put(*a, **k):
        nonlocal added, skipped
        ok = add(vault, *a, source=source, _seen=seen, unit=k.pop("unit", cur), desc=k.pop("desc", dsc), **k)
        added += ok
        skipped += (not ok)
    for i, r in enumerate(rows):
        date = r.get(dcol, "") if dcol else ""
        ref = str(r.get(icol, "")).strip() if icol else ""
        ref = ref or f"{source}:{i}:{date}"
        cur = (str(r.get(ccol, "")).strip().upper() if ccol else "") or default_unit
        dsc = str(r.get(desc_col, "")).strip() if desc_col else ""
        try:
            if mode == "long":
                put(r[mcol], r[vcol], date=date, ref=f"{ref}:{r[mcol]}")
            elif mode == "wide":
                for col, v in r.items():
                    if col == dcol or col == icol or not str(v).strip():
                        continue
                    try:
                        put(col, v, date=date, ref=f"{ref}:{col}")
                    except ValueError:
                        pass
            elif mode == "bank":
                v = to_number(r[acol or tcol])
                put("revenue" if v >= 0 else "expenses", abs(v), date=date, ref=ref)
            elif mode == "sales":
                v = to_number(r[tcol or acol])
                status = str(r.get(scol, "")).lower() if scol else ""
                if status in ("refunded", "voided", "cancelled", "canceled"):
                    put("refunds", abs(v), date=date, ref=ref)
                else:
                    put("revenue", v, date=date, ref=ref)
                    put("orders", 1, date=date, ref=ref)
        except (ValueError, KeyError):
            skipped += 1
    return {"mode": mode, "added": added, "skipped": skipped}


# ---------------------------------------------------------------- Stripe (read-only key)
def ping(item):
    key = config.secret(item, default_env="STRIPE_API_KEY")
    if not key:
        raise MirrorError("Stripe key missing: set STRIPE_API_KEY to a restricted key with read-only access")
    base = (item.get("base_url") or "https://api.stripe.com").rstrip("/")
    call("GET", f"{base}/v1/balance", {"Authorization": f"Bearer {key}"})
    return "connected (read-only check passed)"


def stripe_pull(vault, item, base=None):
    key = config.secret(item, default_env="STRIPE_API_KEY")
    if not key:
        raise MirrorError("Stripe: set STRIPE_API_KEY to a restricted key with read-only access")
    base = (item.get("base_url") or base or "https://api.stripe.com").rstrip("/")
    since = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=item.get("days", 90))).timestamp())
    seen = {(e["name"], e.get("ref")) for e in read(vault) if e.get("ref")}
    added = 0
    for path, field in (("/v1/payment_intents", "intents"), ("/v1/refunds", "refunds")):
        after = None
        while True:
            q = {"limit": 100, "created[gte]": since, **({"starting_after": after} if after else {})}
            res = call("GET", f"{base}{path}?{urllib.parse.urlencode(q)}", {"Authorization": f"Bearer {key}"})
            for o in res.get("data", []):
                date = dt.datetime.fromtimestamp(o["created"], dt.timezone.utc).date().isoformat()
                if field == "intents" and o.get("status") == "succeeded":
                    amt = (o.get("amount_received") or o.get("amount") or 0) / 100
                    added += add(vault, "revenue", amt, date, o.get("currency", "").upper(), "stripe", o["id"], _seen=seen)
                    added += add(vault, "orders", 1, date, "", "stripe", o["id"], _seen=seen)
                elif field == "refunds" and o.get("status") in ("succeeded", "pending"):
                    added += add(vault, "refunds", (o.get("amount") or 0) / 100, date, o.get("currency", "").upper(),
                                 "stripe", o["id"], _seen=seen)
            if not res.get("has_more") or not res.get("data"):
                break
            after = res["data"][-1]["id"]
    return added


# ---------------------------------------------------------------- Shopify / WooCommerce (read-only)
def _since_iso(item):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=item.get("days", 90))).strftime("%Y-%m-%dT%H:%M:%SZ")


def shopify_ping(item):
    tok = config.secret(item, default_env="SHOPIFY_TOKEN")
    if not tok or not item.get("shop"):
        raise MirrorError("Shopify: needs shop=your-store.myshopify.com and SHOPIFY_TOKEN (Admin API token with read_orders)")
    base = (item.get("base_url") or f"https://{item['shop'].replace('https://', '').rstrip('/')}").rstrip("/")
    call("GET", f"{base}/admin/api/{item.get('api_version', '2024-10')}/shop.json", {"X-Shopify-Access-Token": tok})
    return "connected (read-only: orders)"


def shopify_pull(vault, item):
    tok = config.secret(item, default_env="SHOPIFY_TOKEN")
    if not tok or not item.get("shop"):
        raise MirrorError("Shopify: needs shop=your-store.myshopify.com and SHOPIFY_TOKEN (Admin API token with read_orders)")
    base = (item.get("base_url") or f"https://{item['shop'].replace('https://', '').rstrip('/')}").rstrip("/")
    ver, since_id, added = item.get("api_version", "2024-10"), 0, 0
    seen = {(e["name"], e.get("ref")) for e in read(vault) if e.get("ref")}
    while True:
        q = urllib.parse.urlencode({"status": "any", "limit": 250, "since_id": since_id, "created_at_min": _since_iso(item),
                                    "fields": "id,created_at,total_price,currency,financial_status,cancelled_at,refunds"})
        batch = call("GET", f"{base}/admin/api/{ver}/orders.json?{q}", {"X-Shopify-Access-Token": tok}).get("orders", [])
        for o in batch:
            if o.get("cancelled_at") or o.get("financial_status") in ("voided", "pending"):
                continue
            date, cur = o["created_at"][:10], (o.get("currency") or "").upper()
            ref = f"shopify-{o['id']}"
            if o.get("financial_status") != "refunded":
                added += add(vault, "revenue", o["total_price"], date, cur, "shopify", ref, _seen=seen)
                added += add(vault, "orders", 1, date, "", "shopify", ref, _seen=seen)
            for r in o.get("refunds") or []:
                amt = sum(abs(to_number(t.get("amount", 0))) for t in r.get("transactions", []) if t.get("kind") == "refund") \
                    or (abs(to_number(o["total_price"])) if o.get("financial_status") == "refunded" else 0)
                if amt:
                    added += add(vault, "refunds", amt, (r.get("created_at") or o["created_at"])[:10], cur, "shopify",
                                 f"shopify-refund-{r.get('id', o['id'])}", _seen=seen)
        if len(batch) < 250:
            return added
        since_id = batch[-1]["id"]


def woo_ping(item):
    key = config.secret(item, key="key", env_key="key_env", default_env="WOO_KEY")
    sec = config.secret(item, key="secret", env_key="secret_env", default_env="WOO_SECRET")
    if not (item.get("site") or item.get("base_url")) or not key or not sec:
        raise MirrorError("WooCommerce: needs site=https://your-shop.com plus WOO_KEY and WOO_SECRET (read-only API keys)")
    base = (item.get("base_url") or item["site"]).rstrip("/")
    call("GET", f"{base}/wp-json/wc/v3/orders?per_page=1&" + urllib.parse.urlencode({"consumer_key": key, "consumer_secret": sec}))
    return "connected (read-only: orders)"


def woo_pull(vault, item):
    key = config.secret(item, key="key", env_key="key_env", default_env="WOO_KEY")
    sec = config.secret(item, key="secret", env_key="secret_env", default_env="WOO_SECRET")
    if not (item.get("site") or item.get("base_url")) or not key or not sec:
        raise MirrorError("WooCommerce: needs site=https://your-shop.com plus WOO_KEY and WOO_SECRET (read-only API keys)")
    base = (item.get("base_url") or item["site"]).rstrip("/")
    seen = {(e["name"], e.get("ref")) for e in read(vault) if e.get("ref")}
    added, page = 0, 1
    while True:
        q = urllib.parse.urlencode({"per_page": 100, "page": page, "after": _since_iso(item).replace("Z", ""),
                                    "consumer_key": key, "consumer_secret": sec})
        batch = call("GET", f"{base}/wp-json/wc/v3/orders?{q}")
        for o in batch:
            st, date, cur, ref = o.get("status"), (o.get("date_created") or "")[:10], (o.get("currency") or "").upper(), f"woo-{o['id']}"
            if st in ("completed", "processing", "on-hold"):
                added += add(vault, "revenue", o["total"], date, cur, "woocommerce", ref, _seen=seen)
                added += add(vault, "orders", 1, date, "", "woocommerce", ref, _seen=seen)
            for r in o.get("refunds") or []:
                added += add(vault, "refunds", abs(to_number(r.get("total", 0))), date, cur, "woocommerce", f"woo-refund-{r.get('id', o['id'])}", _seen=seen)
            if st == "refunded" and not o.get("refunds"):
                added += add(vault, "refunds", o["total"], date, cur, "woocommerce", f"woo-refund-{o['id']}", _seen=seen)
        if len(batch) < 100:
            return added
        page += 1


PULLS = {"stripe": stripe_pull, "shopify": shopify_pull, "woocommerce": woo_pull}
PINGS = {"stripe": ping, "shopify": shopify_ping, "woocommerce": woo_ping}
