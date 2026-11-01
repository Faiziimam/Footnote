"""Alerts and digests to Slack and/or email. Opt-in (`footnote add-notify`).

Alerts: each condition (a blocked task, a stalled task, a new risk, a failing build, a PR waiting, a revenue drop)
is sent ONCE, and re-arms after it clears. The first run only records what already exists, so switching alerts on
never floods anyone. Digests: a short catch-up daily or weekly, sent when a sync happens (or via `footnote digest`).
"""
import datetime as dt
import json
import re
import smtplib
from email.message import EmailMessage
from . import config, journal, log, metrics
from .mirrors.http import call
from .store import parse_ts, atomic_write, iso, now


def _state_path(project):
    return config.dir_for(project) / "notified.json"


def _load(project):
    try:
        return json.loads(_state_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def to_slack(md):
    out = []
    for l in md.splitlines():
        l = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), l)
        m = re.match(r"^#{1,3}\s+(.*)", l)
        out.append(f"*{m.group(1)}*" if m else re.sub(r"^(\s*)[-*]\s", r"\1• ", l.replace("**", "*")))
    return "\n".join(out)


def send(n, subject, body, html=None, attachments=()):
    """-> list of error strings (empty = delivered everywhere that is configured).
    html: optional rich version of the email; attachments: [(filename, mimetype, bytes)] (email only)."""
    errors = []
    if n.get("slack_webhook"):
        try:
            text = to_slack(body)
            if len(text) > 3500:
                text = text[:3500] + "\n…(cut short here: the full report is in the email, or run `footnote report`)"
            call("POST", n["slack_webhook"], None, {"text": f"*{subject}*\n{text}"}, retries=2, timeout=10, raw=True)
        except Exception as e:
            errors.append(f"Slack: {e}")
    em = n.get("email")
    if em and em.get("to"):
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"] = subject, em.get("from") or em.get("user") or "footnote@localhost"
            msg["To"] = ", ".join(em["to"] if isinstance(em["to"], list) else [em["to"]])
            msg.set_content(body)
            if html:
                msg.add_alternative(html, subtype="html")
            for fname, mime, data in attachments:
                maintype, _, subtype = mime.partition("/")
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
            port = int(em.get("smtp_port", 587))
            cls = smtplib.SMTP_SSL if em.get("ssl") or port == 465 else smtplib.SMTP
            with cls(em["smtp_host"], port, timeout=15) as s:
                if cls is smtplib.SMTP and em.get("tls", True):
                    s.starttls()
                pw = config.secret(em, key="password", env_key="password_env", default_env="SMTP_PASSWORD")
                if em.get("user") and pw:
                    s.login(em["user"], pw)
                s.send_message(msg)
        except Exception as e:
            errors.append(f"Email: {e}")
    return errors


def conditions(tr, rep):
    out = {}
    for tid, (fm, _) in rep.tasks.items():
        if fm["status"] == "blocked":
            out[f"blocked:{tid}"] = f"🚧 {tid} “{fm['title']}” is blocked" + (f" ({fm['owner']})" if fm.get("owner") else "")
    for s in (rep.analysis or {}).get("stale", []):
        out[f"stalled:{s['id']}"] = f"⏳ {s['id']} “{s['title']}” has had no activity for {s['days']} days" + (f" ({s['owner']})" if s["owner"] else "")
    for e in journal.open_risks(journal.read(tr.vault)):
        out[f"risk:{e['id']}"] = f"⚠ New {e['kind']}: {e['text']}"
    gh = rep.gh
    if gh:
        ci = gh.get("ci", {})
        if ci.get("state") == "failing":
            out[f"ci:{ci['branch']}:{','.join(ci['failing'])}"] = f"🔴 Build failing on {ci['branch']}: {', '.join(ci['failing'][:4])}"
        from . import github
        for w in github.waiting_prs(gh, now(), 3):
            out[f"pr:{w['number']}:{w['state']}"] = f"👀 PR #{w['number']} “{w['title']}” — {w['state']} for {w['age']} days ({w['user']})"
    m = metrics.summarize(metrics.read(tr.vault), None, *metrics.settings(tr.cfg)).get("revenue")
    if m and m["prev7"] > 0 and m["last7"] < 0.7 * m["prev7"]:
        wk = dt.date.today().isocalendar()
        out[f"revenue:{wk[0]}-{wk[1]}"] = (f"📉 Revenue is down {round(100 * (1 - m['last7'] / m['prev7']))}% week on week "
                                           f"({metrics.fmt(m['last7'])} vs {metrics.fmt(m['prev7'])})")
    from . import finance
    for i in finance.aging(tr.vault)["overdue"]:
        out[f"invoice:{i['id']}"] = f"💸 Invoice {i['id']} to {i['client']} ({metrics.fmt(i['amount'])}) was due {i['due']}"
    for tid, (fm, _) in rep.tasks.items():                               # due dates (when set)
        d = fm.get("due")
        if d and fm["status"] != "done" and d < dt.date.today().isoformat():
            out[f"overdue:{tid}:{d}"] = f"📅 {tid} “{fm['title']}” was due {d}"
    return out


def digest_text(tr, since):
    s = tr.summary()
    head = (f"{tr.project_info()['name']}: {s['percent_done']}% done ({s['counts']['done']}/{s['total']}) — "
            f"{s['counts']['active']} in progress, {s['counts']['blocked']} blocked.\n\n")
    return head + tr.catchup(since, peek=True)


def run(tr, rep):
    n = tr.cfg.get("notify")
    if not n or not (n.get("slack_webhook") or (n.get("email") or {}).get("to")):
        return
    cond, st, t = conditions(tr, rep), _load(tr.project), now()
    first = st is None
    st = st or {"alerts": {}, "digest": iso(t)}
    new = {k: v for k, v in cond.items() if k not in st["alerts"]}
    st["alerts"] = {k: st["alerts"].get(k, iso(t)) for k in cond}         # cleared conditions can alert again later
    if first:
        log.write(tr.project, "info", f"alerts enabled; {len(cond)} existing item(s) noted without notifying")
    elif new and n.get("alerts", True):
        lines = list(new.values())
        body = "\n".join(f"• {l}" for l in lines[:8]) + (f"\n…and {len(lines) - 8} more" if len(lines) > 8 else "")
        for e in send(n, f"{tr.project_info()['name']}: {len(lines)} thing{'s' if len(lines) != 1 else ''} need attention", body):
            log.write(tr.project, "warn", e)
    period = {"daily": 1, "weekly": 7, "monthly": 30}.get(n.get("digest", "off"))
    if period and not first and t - parse_ts(st["digest"]) >= dt.timedelta(days=period):
        subject, body, html, files = tr.digest_payload(st["digest"])
        for e in send(n, subject.replace("catch-up", f"{n['digest']} catch-up") if n.get("content", "catchup") == "catchup" else subject, body, html, files):
            log.write(tr.project, "warn", e)
        st["digest"] = iso(t)
    atomic_write(_state_path(tr.project), json.dumps(st))
