"""Starting points for common project kinds. PURE DATA: add or edit freely. Unknown kinds still work,
because tasks, the journal and metrics are all free-form; a profile only suggests where to begin.

metric tuple: (name, label, kind, unit, how_to_connect)   kind: "sum" (adds up over time) | "latest" (a gauge)
"""
SALES_HOW = "import orders: footnote metrics-import orders.csv (Shopify/WooCommerce/Stripe export), or connect Stripe"
TRAFFIC_HOW = "footnote metrics-import analytics.csv, or tell the agent: 'visitors this week were 340'"

PROFILES = {
    "portfolio": {
        "aliases": ["portfolio website", "personal site", "personal website", "resume site", "cv site"],
        "tasks": [("Content", "Write bio and case-study copy"), ("Design", "Choose style, colours and fonts"),
                  ("Build", "Home page with hero"), ("Build", "Projects / work page"), ("Build", "Contact form or link"),
                  ("Quality", "Mobile responsive check"), ("Quality", "Accessibility and speed check"),
                  ("Launch", "Domain and hosting"), ("Launch", "Deploy and test live site")],
        "metrics": [("visitors", "Visitors", "sum", "", TRAFFIC_HOW),
                    ("contact_requests", "Contact requests", "sum", "", "tell the agent when someone gets in touch")]},
    "ecommerce": {
        "aliases": ["e-commerce", "online store", "online shop", "shop", "store", "webshop", "shopify"],
        "tasks": [("Catalogue", "Product data model and catalogue pages"), ("Catalogue", "Search and filters"),
                  ("Shopping", "Cart"), ("Shopping", "Checkout and payments"), ("Shopping", "Order confirmation emails"),
                  ("Operations", "Order management / admin"), ("Operations", "Inventory tracking"),
                  ("Operations", "Shipping and tax rules"), ("Trust", "Policies: returns, privacy, terms"),
                  ("Growth", "SEO and analytics"), ("Launch", "Test orders end to end"), ("Launch", "Go live")],
        "metrics": [("revenue", "Revenue", "sum", "", SALES_HOW), ("orders", "Orders", "sum", "", SALES_HOW),
                    ("refunds", "Refunds", "sum", "", SALES_HOW), ("visitors", "Visitors", "sum", "", TRAFFIC_HOW),
                    ("inventory_units", "Units in stock", "latest", "", "tell the agent or import a stock CSV")]},
    "saas": {
        "aliases": ["software as a service", "web app", "subscription product", "platform"],
        "tasks": [("Product", "Core feature set"), ("Accounts", "Sign-up, login and password reset"),
                  ("Billing", "Plans and subscription billing"), ("Product", "Onboarding flow"),
                  ("Operations", "Admin and support tooling"), ("Quality", "Automated tests and error monitoring"),
                  ("Growth", "Landing page and analytics"), ("Launch", "Security review"), ("Launch", "Deploy and backups")],
        "metrics": [("signups", "Sign-ups", "sum", "", TRAFFIC_HOW), ("mrr", "Monthly recurring revenue", "latest", "",
                    "connect Stripe or tell the agent"), ("active_users", "Active users", "latest", "", TRAFFIC_HOW),
                    ("churned", "Cancellations", "sum", "", "tell the agent or import a CSV")]},
    "mobile app": {
        "aliases": ["app", "ios app", "android app", "mobile application"],
        "tasks": [("Product", "Core screens and navigation"), ("Product", "Backend / data storage"),
                  ("Quality", "Testing on real devices"), ("Launch", "Store listing, icons and screenshots"),
                  ("Launch", "Privacy policy and review submission")],
        "metrics": [("downloads", "Downloads", "sum", "", TRAFFIC_HOW), ("active_users", "Active users", "latest", "", TRAFFIC_HOW)]},
    "marketing campaign": {
        "aliases": ["campaign", "marketing", "ad campaign", "launch campaign", "content marketing"],
        "tasks": [("Plan", "Goal, audience and budget"), ("Plan", "Channels and calendar"), ("Create", "Creative and copy"),
                  ("Run", "Launch the campaign"), ("Run", "Weekly review and adjustments"), ("Wrap-up", "Results report")],
        "metrics": [("spend", "Spend", "sum", "", "tell the agent or import an ads export"),
                    ("leads", "Leads", "sum", "", TRAFFIC_HOW), ("revenue", "Revenue attributed", "sum", "", SALES_HOW)]},
    "content": {
        "aliases": ["blog", "newsletter", "youtube", "podcast", "course", "content business"],
        "tasks": [("Plan", "Topics and publishing schedule"), ("Create", "Produce the first batch"),
                  ("Publish", "Set up the channel/site"), ("Growth", "Promotion and audience building")],
        "metrics": [("audience", "Audience / subscribers", "latest", "", TRAFFIC_HOW), ("revenue", "Revenue", "sum", "", SALES_HOW),
                    ("posts_published", "Posts published", "sum", "", "tell the agent")]},
    "finance business": {
        "aliases": ["finance", "bookkeeping", "accounting", "small business", "business finances", "freelance business"],
        "tasks": [("Setup", "Chart of accounts and categories"), ("Setup", "Connect bank / card statements"),
                  ("Routine", "Categorise transactions"), ("Routine", "Invoice clients and chase payments"),
                  ("Routine", "Monthly profit and loss review"), ("Compliance", "Tax and filing calendar")],
        "metrics": [("revenue", "Income", "sum", "", "footnote metrics-import bank.csv (positive amounts = income)"),
                    ("expenses", "Expenses", "sum", "", "footnote metrics-import bank.csv (negative amounts = expenses)"),
                    ("cash_balance", "Cash balance", "latest", "", "tell the agent or import a balance CSV"),
                    ("invoices_outstanding", "Unpaid invoices", "latest", "", "tell the agent")]},
    "client project": {
        "aliases": ["freelance", "client work", "agency project", "consulting"],
        "tasks": [("Scope", "Agree scope and deliverables"), ("Scope", "Timeline and milestones"),
                  ("Delivery", "Produce deliverables"), ("Delivery", "Client review and revisions"),
                  ("Wrap-up", "Final handover and invoice")],
        "metrics": [("hours", "Hours spent", "sum", "h", "tell the agent"), ("invoiced", "Invoiced", "sum", "", "tell the agent")]},
    "event": {
        "aliases": ["conference", "wedding", "meetup", "workshop", "launch event"],
        "tasks": [("Plan", "Budget and date"), ("Plan", "Venue and vendors"), ("Promote", "Invitations / ticketing"),
                  ("Run", "Run-of-show and staffing"), ("Wrap-up", "Thank-yous and reconciliation")],
        "metrics": [("rsvps", "RSVPs / tickets sold", "latest", "", "tell the agent"), ("spend", "Spend", "sum", "", "tell the agent")]},
    "research": {
        "aliases": ["study", "thesis", "analysis", "report", "investigation"],
        "tasks": [("Question", "Define the question and success criteria"), ("Gather", "Collect sources / data"),
                  ("Analyse", "Analysis"), ("Write", "Draft findings"), ("Write", "Review and finalise")],
        "metrics": [("sources_reviewed", "Sources reviewed", "sum", "", "tell the agent")]},
    "other": {"aliases": [], "tasks": [], "metrics": []},
}

# Figures computed from other figures, shown only when every input exists.
DERIVED = [
    ("profit", "Profit", "revenue", "-", "expenses", ""),
    ("aov", "Average order value", "revenue", "/", "orders", ""),
    ("conversion", "Visitor → order conversion", "orders", "/", "visitors", "%"),
    ("cost_per_lead", "Cost per lead", "spend", "/", "leads", ""),
    ("runway_months", "Cash runway (months)", "cash_balance", "/", "expenses", "mo"),
]

DETECT_DEPS = {"ecommerce": ["stripe", "@stripe/stripe-js", "shopify", "@shopify", "medusa", "snipcart", "woocommerce"],
               "saas": ["next-auth", "@clerk", "supabase", "firebase", "lemonsqueezy"]}


def match_kind(text):
    t = (text or "").strip().lower()
    for k, v in PROFILES.items():
        if t == k or t in v["aliases"]:
            return k
    for k, v in PROFILES.items():
        if k != "other" and (k in t or any(a in t for a in v["aliases"])):
            return k
    return None


def template_text(kind):
    k = match_kind(kind)
    if not k or k == "other":
        return ("No built-in template for “%s” — that is fine. Break the user's request into tasks yourself, "
                "and use tracker_metric for any number the user cares about (it is created automatically)." % kind)
    p = PROFILES[k]
    lines = [f"Typical work for a {k} (adapt it to this request; skip what doesn't apply):"]
    cur = None
    for epic, title in p["tasks"]:
        if epic != cur:
            lines.append(f"  {epic}:"); cur = epic
        lines.append(f"    - {title}")
    if p["metrics"]:
        lines.append("Numbers worth tracking: " + ", ".join(f"{m[0]} ({m[1]})" for m in p["metrics"]))
    return "\n".join(lines)
