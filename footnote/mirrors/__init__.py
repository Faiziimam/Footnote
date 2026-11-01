from .base import Mirror, MirrorError
from .csvm import CsvMirror
from .sqlitem import SqliteMirror
from .notion import NotionMirror
from .gsheets import SheetsMirror
from .issues import GitHubIssues, Trello

REGISTRY = {"csv": CsvMirror, "excel": CsvMirror, "sqlite": SqliteMirror,
            "notion": NotionMirror, "gsheets": SheetsMirror, "sheets": SheetsMirror,
            "github-issues": GitHubIssues, "trello": Trello}
# "obsidian" needs no mirror: the vault folder itself is the Obsidian vault.


def make(cfg, project, vault):
    t = cfg.get("type")
    if t not in REGISTRY:
        raise MirrorError(f"unknown tracker type {t!r}; choose one of {sorted(REGISTRY)} or obsidian")
    return REGISTRY[t](cfg, project, vault)
