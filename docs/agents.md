# Connecting any AI tool / agent

Pick whichever door your tool supports. All of them do the same thing.

| Door | For | How |
|---|---|---|
| **MCP server** | Claude Code, Cursor, Codex, Gemini CLI, Copilot (VS Code), Windsurf, most agent apps | `footnote connect <tool>` writes the config + instruction file |
| **Command** | any agent that can run shell | `footnote say "finished the logo"` |
| **Webhook** | Zapier, Make, n8n, custom GPTs, scripts | `footnote ui` prints the address + token; `POST /api/event` with `Authorization: Bearer <token>` and `{"text": "finished the logo"}` or `{"id":"T-004","status":"Done"}` or `{"add":"New task"}` |
| **File drop** | tools that can only write files | append a line to `.footnote/inbox.jsonl`, e.g. `{"text": "finished the logo"}`; picked up on the next sync |
| **Claude Code hook** | live updates | `footnote install-hook` |

MCP tools: `tracker_project`, `tracker_list`, `tracker_update` (plain English), `tracker_set_status`, `tracker_add_task`, `tracker_link`,
`tracker_set_field`, `tracker_add_field` (custom/calculated fields), `tracker_record` (decisions, risks, learnings), `tracker_metric`,
`tracker_metric_fix`, `tracker_metrics`, `tracker_invoice`, `tracker_assign`, `tracker_catchup`, `tracker_whois`, `tracker_report`,
`tracker_archive`, `tracker_undo`, `tracker_sync`. Unclear matches are never guessed — the agent gets a message back.
The web server only listens on your own computer and requires the token.
