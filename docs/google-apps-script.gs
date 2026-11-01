// Paste this into your Google Sheet: Extensions -> Apps Script. Change SECRET, then
// Deploy -> New deployment -> Web app -> Execute as: Me, Who has access: Anyone -> Deploy. Copy the link.
const SECRET = 'CHANGE_ME_TO_A_LONG_RANDOM_PASSWORD';
const TAB = 'Tracker';

function tab_(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  name = name || TAB;
  return ss.getSheetByName(name) || ss.insertSheet(name);
}
function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
function doGet(e) {
  if (e.parameter.secret !== SECRET) return out_({error: 'forbidden'});
  const v = tab_(e.parameter.tab).getDataRange().getDisplayValues();
  return out_({values: v});
}
function doPost(e) {
  const b = JSON.parse(e.postData.contents);
  if (b.secret !== SECRET) return out_({error: 'forbidden'});
  const sh = tab_(b.tab);
  sh.clearContents();
  if (b.values.length) {
    const r = sh.getRange(1, 1, b.values.length, b.values[0].length);
    r.setNumberFormat('@');          // keep dates/IDs as plain text
    r.setValues(b.values);
  }
  return out_({ok: true});
}
