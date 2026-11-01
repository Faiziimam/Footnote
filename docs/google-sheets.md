# Connect Google Sheets

**Easiest (no developer setup):**
1. Make a new Google Sheet. **Extensions → Apps Script**.
2. Run `footnote show-script`, paste the output over the editor's contents, and change `SECRET` to any long password.
3. **Deploy → New deployment → Web app** → Execute as *Me*, access *Anyone* → Deploy → copy the link.
   (The link is useless without your password.)
4. `footnote add-tracker gsheets` and paste the link and the password.

**If you already have Google API access:** set `GOOGLE_SHEETS_TOKEN` (an OAuth access token) and run
`footnote add-tracker gsheets --opt spreadsheet_id=<sheet link>`; with no link it creates one.
