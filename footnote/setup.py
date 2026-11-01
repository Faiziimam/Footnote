"""Connect external trackers. Used by the wizard, the web page and `footnote add-tracker`."""
from . import config, lock
from .api import TrackerError

TYPES = {
    "obsidian": "Obsidian (a folder of notes on your computer)",
    "github-issues": "GitHub Issues",
    "trello": "Trello board",
    "notion": "Notion",
    "gsheets": "Google Sheets",
    "csv": "Excel / Numbers (a spreadsheet file)",
    "sqlite": "A database file (SQLite)",
}
FIELDS = {   # what to ask for, in plain words
    "notion": [("token", "Notion integration token (starts with secret_ or ntn_)", True),
               ("parent_page", "Link to the Notion page that should hold the tracker", True)],
    "gsheets": [("webapp_url", "Apps Script web app link (see docs/google-sheets.md)", False),
                ("secret", "The password you put in the script", False),
                ("spreadsheet_id", "…or an existing spreadsheet link (API mode)", False)],
    "csv": [("path", "Where to save the file (blank = Tracker.csv in your project)", False)],
    "sqlite": [("path", "Where to save the database (blank = tracker.db in your project)", False)],
    "github-issues": [("repo", "Repository, like owner/name", True), ("token", "GitHub token with Issues read/write (or set GITHUB_TOKEN)", False)],
    "trello": [("board", "Board ID (from the board URL)", True), ("key", "Trello API key (or set TRELLO_KEY)", False),
               ("token", "Trello token (or set TRELLO_TOKEN)", False)],
    "obsidian": [("vault", "Folder name for the notes (blank = Tracker). Open it as a vault in Obsidian.", False)],
}


def add_tracker(project, ttype, **opts):
    with lock.locked(config.lock_path(project)):
        return _add_tracker(project, ttype, **opts)


def _add_tracker(project, ttype, **opts):
    ttype = {"excel": "csv", "sheets": "gsheets", "markdown": "obsidian", "github": "github-issues", "issues": "github-issues"}.get(ttype, ttype)
    if ttype not in TYPES:
        raise TrackerError(f"Unknown tracker “{ttype}”. Choose: {', '.join(TYPES)}")
    opts = {k: v for k, v in opts.items() if v not in (None, "")}
    cfg = config.load(project)
    if ttype == "obsidian":
        cfg["vault"] = opts.get("vault", cfg.get("vault", "Tracker"))
        config.save(project, cfg)
        return cfg
    if ttype == "notion" and not (opts.get("parent_page") or opts.get("database_id")):
        raise TrackerError("Notion needs the link to the page that should hold the tracker (parent_page).")
    if ttype == "github-issues" and not opts.get("repo"):
        raise TrackerError("GitHub Issues needs the repository, like owner/name.")
    if ttype == "trello" and not opts.get("board"):
        raise TrackerError("Trello needs the board ID (the short code in the board's web address).")
    if ttype == "gsheets" and not (opts.get("webapp_url") or opts.get("spreadsheet_id") or opts.get("token")):
        raise TrackerError("Google Sheets needs the Apps Script link (easiest) or a spreadsheet link.")
    if ttype == "gsheets" and opts.get("webapp_url") and not (opts.get("secret") or opts.get("secret_env")):
        raise TrackerError("Add the password (secret) you put in the Apps Script.")
    item = {"type": ttype, **opts}
    cfg["mirrors"] = [m for m in cfg.get("mirrors", []) if (m.get("name") or m["type"]) != (item.get("name") or ttype)]
    cfg["mirrors"].append(item)
    config.save(project, cfg)
    return cfg


def add_source(project, stype, **opts):
    """Read-only number sources (e.g. Stripe sales)."""
    if stype not in ("stripe", "github", "shopify", "woocommerce"):
        raise TrackerError("Supported sources: stripe, shopify, woocommerce, github")
    with lock.locked(config.lock_path(project)):
        cfg = config.load(project)
        item = {"type": stype, **{k: v for k, v in opts.items() if v}}
        if stype == "github":                       # signals, not numbers: lives under its own key
            cfg["github"] = {k: v for k, v in item.items() if k != "type"}
        else:
            cfg["sources"] = [s for s in cfg.get("sources", []) if s.get("type") != stype] + [item]
        config.save(project, cfg)


def add_relay(project, url, pull_token=None, pull_token_env=None):
    if not url.startswith(("http://", "https://")):
        raise TrackerError("The relay address should start with https://")
    with lock.locked(config.lock_path(project)):
        cfg = config.load(project)
        cfg["relay"] = {"url": url.rstrip("/"), **({"pull_token": pull_token} if pull_token else {}),
                        **({"pull_token_env": pull_token_env} if pull_token_env else {})}
        config.save(project, cfg)


def add_notify(project, slack=None, email_to=None, smtp_host=None, smtp_port=587, smtp_user=None, email_from=None,
               digest=None, tls=True, content=None, report_for=None, attach=None):
    if not slack and not email_to:
        raise TrackerError("Give a Slack webhook URL (--slack) and/or an email address (--email-to).")
    if slack and not slack.startswith("https://"):
        raise TrackerError("A Slack webhook URL starts with https://hooks.slack.com/…")
    if email_to and not smtp_host:
        raise TrackerError("For email I also need the mail server: --smtp-host smtp.gmail.com (password via SMTP_PASSWORD).")
    if digest and digest not in ("daily", "weekly", "monthly", "off"):
        raise TrackerError("Digest can be daily, weekly, monthly or off.")
    if content and content not in ("catchup", "report"):
        raise TrackerError("Content can be catchup (a short summary of what changed) or report (the full project report).")
    if report_for and report_for not in ("manager", "founder", "everyone", "developer", "all"):
        raise TrackerError("Report audience can be manager, everyone, developer or all.")
    if attach and any(a not in ("deck", "html") for a in attach):
        raise TrackerError("You can attach: deck (a PowerPoint) and/or html (a page you can print to PDF).")
    with lock.locked(config.lock_path(project)):
        cfg = config.load(project)
        n = cfg.get("notify", {})
        if slack:
            n["slack_webhook"] = slack
        if email_to:
            n["email"] = {"to": [x.strip() for x in email_to.split(",")], "smtp_host": smtp_host, "smtp_port": int(smtp_port),
                          "user": smtp_user or "", "from": email_from or smtp_user or "", "tls": bool(tls)}
        n["digest"] = digest or n.get("digest", "weekly")
        if content:
            n["content"] = content
        if report_for:
            n["report_for"] = report_for
        if attach is not None:
            n["attach"] = list(attach)
        n.setdefault("alerts", True)
        cfg["notify"] = n
        config.save(project, cfg)


def add_llm(project, command=None, narrative=True, fuzzy=True):
    with lock.locked(config.lock_path(project)):
        cfg = config.load(project)
        cfg["llm"] = {**({"command": command} if command else {}), "narrative": bool(narrative), "fuzzy": bool(fuzzy)}
        config.save(project, cfg)


def add_repo(project, path):
    from pathlib import Path
    cfg = config.load(project)
    p = Path(path).expanduser()
    if not (p if p.is_absolute() else Path(project) / p).exists():
        raise TrackerError(f"I can't find the folder {path}")
    if str(path) not in cfg.setdefault("repos", []):
        cfg["repos"].append(str(path))
    config.save(project, cfg)
