#!/usr/bin/env node
"use strict";
// Footnote's npm launcher. It does ONE thing: find Python 3.9+ on this computer and run the bundled footnote.pyz with it.
// No install scripts, no dependencies, no shell (arguments are passed straight through, so nothing you type is ever interpreted).
const { spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const pkg = require("../package.json");
const PYZ = path.join(__dirname, "..", "vendor", "footnote.pyz");
const MIN = [3, 9];

function fail(message) {
  process.stderr.write(message.replace(/\s+$/, "") + "\n");
  process.exit(1);
}

const NEEDS_PYTHON = `Footnote needs Python 3.9 or newer, and could not find it on this computer.
It takes about a minute to install, then run this again:
  Windows:  winget install Python.Python.3.12     (or https://www.python.org/downloads/)
  macOS:    brew install python                    (or https://www.python.org/downloads/)
  Linux:    sudo apt install python3               (or your package manager)
Python is installed somewhere unusual? Set FOOTNOTE_PYTHON to its full path.
(There are no Python packages to install: Footnote only needs Python itself.)`;

function probe(cmd) {
  // Returns true when this command is a working Python >= MIN.
  const r = spawnSync(cmd[0], [...cmd.slice(1), "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
    { encoding: "utf8", timeout: 15000, windowsHide: true });
  if (r.error || r.status !== 0) return false;
  const m = /^(\d+)\.(\d+)/.exec((r.stdout || "").trim());
  if (!m) return false;
  const major = Number(m[1]), minor = Number(m[2]);
  return major > MIN[0] || (major === MIN[0] && minor >= MIN[1]);
}

function findPython() {
  if (process.env.FOOTNOTE_PYTHON) {            // an explicit choice is honoured or reported, never silently replaced
    const cmd = [process.env.FOOTNOTE_PYTHON];
    if (probe(cmd)) return cmd;
    fail(`FOOTNOTE_PYTHON is set to "${process.env.FOOTNOTE_PYTHON}", but that is not a working Python ${MIN.join(".")} or newer.`);
  }
  const options = process.platform === "win32"
    ? [["py", "-3"], ["python"], ["python3"]]     // 'py' is the official Windows launcher; plain 'python' may be a Store stub
    : [["python3"], ["python"]];
  return options.find(probe) || null;
}

function verifyBundle() {
  let data, expected;
  try {
    data = fs.readFileSync(PYZ);
    expected = fs.readFileSync(PYZ + ".sha256", "utf8").trim().split(/\s+/)[0];
  } catch (e) {
    fail("The bundled Footnote program is missing. Reinstall it with: npm install -g footnote-app");
  }
  const actual = crypto.createHash("sha256").update(data).digest("hex");
  if (actual !== expected) {
    fail("The bundled Footnote program does not match its checksum, so it was not run (the download may be damaged or altered).\nReinstall it with: npm install -g footnote-app");
  }
}

verifyBundle();
const python = findPython();
if (!python) fail(NEEDS_PYTHON);

const env = { ...process.env, FOOTNOTE_VIA_NPM: `${pkg.name}@${pkg.version}` };
if (process.env.npm_command === "exec") env.FOOTNOTE_VIA_NPX = "1";   // started with npx rather than installed

const result = spawnSync(python[0], [...python.slice(1), PYZ, ...process.argv.slice(2)], { stdio: "inherit", env });
if (result.error) fail(`Could not start Python: ${result.error.message}`);
if (result.signal) process.kill(process.pid, result.signal);
process.exit(result.status === null ? 1 : result.status);
