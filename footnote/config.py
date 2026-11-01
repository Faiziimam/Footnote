"""Settings live in <project>/.footnote/config.json (chmod 600: it may hold API tokens)."""
import json
import os
import secrets
from pathlib import Path

DEFAULTS = {"vault": "Tracker", "mirrors": [], "use_agent": False}


def migrate_legacy(project):
    """Footnote was first called 'autotracker': move its private settings folder over, once, without losing anything."""
    old, new = Path(project) / ".autotracker", Path(project) / ".footnote"
    if old.is_dir() and not new.exists():
        try:
            old.rename(new)
            return True
        except OSError:
            return False
    return False


def dir_for(project):
    return Path(project) / ".footnote"


def lock_path(project):
    return dir_for(project) / "lock"


def path_for(project):
    return dir_for(project) / "config.json"


def exists(project):
    return path_for(project).exists()


def load(project):
    cfg = dict(DEFAULTS)
    p = path_for(project)
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def save(project, cfg):
    d = dir_for(project)
    d.mkdir(exist_ok=True)
    p = path_for(project)
    from .store import atomic_write
    atomic_write(p, json.dumps(cfg, indent=2) + "\n")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    gi = d / ".gitignore"
    if not gi.exists():  # never commit tokens
        gi.write_text("config.json\ntoken\ninbox*.jsonl\nlock\nlog*.txt\nhistory/\nfiles.json\nrelay_last\nlast_seen.json\nrun.py\n", encoding="utf-8")


def server_token(project):
    d = dir_for(project)
    d.mkdir(exist_ok=True)
    p = d / "token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(18), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p.read_text(encoding="utf-8").strip()


def secret(cfg_item, key="token", env_key="token_env", default_env=""):
    """Token from the config item itself, or from the environment variable it names."""
    return cfg_item.get(key) or os.environ.get(cfg_item.get(env_key) or default_env, "")
