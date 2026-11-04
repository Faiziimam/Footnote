"""The npm package: a tiny, install-script-free launcher around footnote.pyz. It must be safe, honest and work on every OS."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from footnote import connect

ROOT = Path(__file__).resolve().parent.parent
NODE, NPM = shutil.which("node"), shutil.which("npm")
LIFECYCLE = {"preinstall", "install", "postinstall", "prepare", "prepublish", "prepublishOnly", "prepack", "postpack", "preuninstall", "uninstall", "postuninstall"}


class PackageFile(unittest.TestCase):
    def setUp(self):
        self.pkg = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))

    def test_nothing_runs_at_install_time_and_nothing_extra_is_pulled_in(self):
        self.assertEqual(LIFECYCLE & set(self.pkg.get("scripts", {})), set())          # npm supply-chain attacks live in install scripts
        for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies", "bundledDependencies"):
            self.assertNotIn(k, self.pkg)
        self.assertEqual(self.pkg["license"], "Apache-2.0")
        self.assertEqual(self.pkg["bin"], {"footnote": "bin/footnote.js"})
        self.assertEqual(sorted(self.pkg["files"]), sorted(["bin/footnote.js", "vendor/footnote.pyz", "vendor/footnote.pyz.sha256", "README.md", "LICENSE", "NOTICE"]))

    def test_version_matches_the_python_package(self):
        py = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
        self.assertEqual(self.pkg["version"], py)

    def test_launcher_has_no_shell_and_no_network(self):
        src = (ROOT / "npm" / "bin" / "footnote.js").read_text(encoding="utf-8")
        imports = re.findall(r'const \{([^}]*)\} = require\("node:child_process"\)', src)
        self.assertEqual([i.strip() for i in imports], ["spawnSync"])                    # the one call that never goes through a shell
        for bad in ("shell: true", "shell:true", "execSync", "execFile", "fork(", "eval(", "new Function", "node:http", "node:https", "node:net", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(bad, src)
        self.assertEqual(re.findall(r"require\(\"([^\"]+)\"\)", src), ["node:child_process", "node:crypto", "node:fs", "node:path", "../package.json"])   # Node built-ins only


class Via(unittest.TestCase):
    def test_only_a_plain_name_and_version_is_ever_put_into_setup_files(self):
        good = {"FOOTNOTE_VIA_NPX": "1", "FOOTNOTE_VIA_NPM": "footnote-app@0.2.0"}
        os.environ.update(good)
        try:
            self.assertEqual(connect.via_npx(), "footnote-app@0.2.0")
            for evil in ("footnote-app@0.2.0; rm -rf /", "$(touch x)@1.0.0", "a b@1.0.0", "footnote-app@latest", 'x"@1.0.0', "footnote-app@0.2.0\n", ""):
                os.environ["FOOTNOTE_VIA_NPM"] = evil
                self.assertIsNone(connect.via_npx(), evil)
            os.environ["FOOTNOTE_VIA_NPM"] = good["FOOTNOTE_VIA_NPM"]; os.environ.pop("FOOTNOTE_VIA_NPX")
            self.assertIsNone(connect.via_npx())                                      # installed (not npx): normal behaviour
        finally:
            for k in good:
                os.environ.pop(k, None)


@unittest.skipUnless(NODE and NPM, "needs node and npm")
class Launcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stage = Path(tempfile.mkdtemp()) / "pkg"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_npm.py"), str(cls.stage)], check=True, capture_output=True)
        cls.launcher = str(cls.stage / "bin" / "footnote.js")

    def run_it(self, *args, env=None, cwd=None, launcher=None):
        e = {**os.environ, **(env or {})}
        return subprocess.run([NODE, launcher or self.launcher, *args], capture_output=True, text=True, encoding="utf-8", env=e, cwd=cwd, timeout=60)

    def project(self):
        d = Path(tempfile.mkdtemp()); subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
        return d

    def test_runs_the_program_and_passes_the_exit_code_through(self):
        r = self.run_it("--help"); self.assertEqual(r.returncode, 0); self.assertIn("usage: footnote", r.stdout)
        r = self.run_it("--project", str(self.project()), "set", "T-999", "done")
        self.assertEqual(r.returncode, 1); self.assertIn("There is no task T-999", r.stderr)
        self.assertNotIn("at Object", r.stderr); self.assertNotIn("node:internal", r.stderr)       # never a JavaScript stack trace

    def test_a_real_workflow_works_end_to_end(self):
        d = self.project(); (d / "PLAN.md").write_text("- [ ] Design logo\n- [ ] Build site\n", encoding="utf-8")
        self.run_it("--project", str(d), "sync")
        r = self.run_it("--project", str(d), "say", "finished the logo")
        self.assertIn("Not started → Done", r.stdout)
        self.assertIn("Design logo", self.run_it("--project", str(d), "status").stdout)

    def test_what_you_type_is_never_interpreted_by_a_shell(self):
        d = self.project()
        self.run_it("--project", str(d), "say", "finished x; touch PWNED && touch PWNED2 $(touch PWNED3) `touch PWNED4`", cwd=str(d))
        self.assertEqual([p.name for p in d.iterdir() if p.name.startswith("PWNED")], [])
        r = self.run_it("--project", str(d), "add", 'quote " and \'single\' and spaces')
        self.assertEqual(r.returncode, 0)
        self.assertIn('quote " and \'single\' and spaces', self.run_it("--project", str(d), "status").stdout)   # arrives exactly as typed

    @unittest.skipIf(sys.platform.startswith("win"), "empty PATH is not meaningful on Windows")
    def test_missing_python_is_explained_plainly(self):
        r = self.run_it("--help", env={"PATH": "/nonexistent", "FOOTNOTE_PYTHON": ""})
        self.assertEqual(r.returncode, 1)
        for needle in ("needs Python 3.9 or newer", "winget install", "brew install python", "FOOTNOTE_PYTHON", "no Python packages to install"):
            self.assertIn(needle, r.stderr)
        self.assertNotIn("at Object", r.stderr)

    def test_an_explicit_python_choice_is_honoured_or_reported_never_silently_replaced(self):
        self.assertEqual(self.run_it("--help", env={"FOOTNOTE_PYTHON": sys.executable}).returncode, 0)
        r = self.run_it("--help", env={"FOOTNOTE_PYTHON": os.path.join(tempfile.gettempdir(), "no-such-python")})
        self.assertEqual(r.returncode, 1); self.assertIn("not a working Python 3.9", r.stderr)

    def test_a_modified_bundle_is_refused(self):
        copy = Path(tempfile.mkdtemp()) / "pkg"; shutil.copytree(self.stage, copy)
        with open(copy / "vendor" / "footnote.pyz", "ab") as f:
            f.write(b"tampered")
        r = self.run_it("--help", launcher=str(copy / "bin" / "footnote.js"))
        self.assertEqual(r.returncode, 1); self.assertIn("does not match its checksum", r.stderr); self.assertNotIn("usage:", r.stdout)

    def test_setup_files_use_npx_only_when_started_with_npx(self):
        d = self.project()
        self.run_it("--project", str(d), "connect", "claude", env={"npm_command": "exec"})
        srv = json.loads((d / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["footnote"]
        flat = " ".join([srv["command"], *srv["args"]])
        self.assertIn("npx", flat); self.assertIn("footnote-app@0.2.0", flat); self.assertTrue(flat.rstrip().endswith("mcp"))
        self.assertNotIn("_npx", flat)                                                   # no path into a temporary cache
        self.run_it("--project", str(d), "install-hook", env={"npm_command": "exec"})
        hook = json.loads((d / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(hook.startswith("npx -y footnote-app@0.2.0 --project "))
        d2 = self.project()                                                              # installed normally: points at the installed copy
        self.run_it("--project", str(d2), "connect", "claude", env={"npm_command": "install"})
        srv2 = json.loads((d2 / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["footnote"]
        self.assertNotIn("npx", srv2["command"]); self.assertIn("footnote.pyz", " ".join(srv2["args"]))

    def test_the_published_package_contains_exactly_what_it_should_and_installs_cleanly(self):
        out = subprocess.run([NPM, "pack", "--json", "--pack-destination", str(self.stage.parent)], cwd=self.stage, capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        info = json.loads(out.stdout)[0]
        self.assertEqual(sorted(f["path"] for f in info["files"]), sorted(["LICENSE", "NOTICE", "README.md", "bin/footnote.js", "package.json", "vendor/footnote.pyz", "vendor/footnote.pyz.sha256"]))
        self.assertLess(info["size"], 400_000)
        prefix = Path(tempfile.mkdtemp())
        inst = subprocess.run([NPM, "install", "--prefix", str(prefix), str(self.stage.parent / info["filename"]), "--no-audit", "--no-fund"],
                              capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assertEqual(inst.returncode, 0, inst.stderr)
        shim = prefix / "node_modules" / ".bin" / ("footnote.cmd" if sys.platform.startswith("win") else "footnote")
        self.assertTrue(shim.exists())
        r = subprocess.run([str(shim), "--help"], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0); self.assertIn("usage: footnote", r.stdout)
