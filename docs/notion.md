# Connect Notion (about 3 minutes, once)

1. Go to notion.so/profile/integrations → **New integration** → name it "Tracker" → Save. Copy the **token**.
2. In Notion, make an empty page called "Tracker home". Click **•••** → **Connections** → add your "Tracker" integration.
3. Copy that page's link.
4. Run `footnote add-tracker notion` (or use **Connect another tracker** in `footnote ui`) and paste the token and link.

A database appears inside that page with columns: Name, ID, Status, Epic, Relations, Waiting on, dates…
Add your own columns in Notion if you like — new columns are not touched. Don't rename Name/ID/Status.
Tip: keep the token out of shared folders: `export NOTION_TOKEN=…` works instead of pasting it.
