"""A plain log file (.footnote/log.txt) so 'why did it do that / why did it stop' has an answer."""
import datetime as dt
import threading
from . import config
from .security import redact

_lock = threading.Lock()
LIMIT = 200_000


def write(project, level, msg):
    try:
        d = config.dir_for(project)
        d.mkdir(exist_ok=True)
        p = d / "log.txt"
        with _lock:
            if p.exists() and p.stat().st_size > LIMIT:
                p.replace(d / "log.1.txt")
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {level.upper():<5} {redact(msg)}\n")
    except OSError:
        pass


def tail(project, n=15):
    p = config.dir_for(project) / "log.txt"
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
