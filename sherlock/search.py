"""Search channels that do not need GTK.

Apps come from .desktop files. Files use tracker3, then Fedora's tinysparql
(the Tracker rename), then plocate/locate, then a short walk of a few home
folders. The web channel is only a DuckDuckGo URL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

MAX_RESULTS = 40
WALK_MAX_ENTRIES = 6000
WALK_DEADLINE_S = 1.5
COMMAND_TIMEOUT_S = 3.0

SKIP_WALK_DIRS = {
    ".git",
    ".cache",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}


@dataclass
class AppEntry:
    desktop_id: str
    path: str
    name: str
    generic_name: str = ""
    comment: str = ""
    keywords: str = ""
    icon: str = ""


@dataclass
class Result:
    title: str
    subtitle: str
    kind: str  # app, file, web
    desktop_id: str = ""
    path: str = ""
    url: str = ""
    icon: str = ""
    rank: int = 0


@dataclass
class FileSearch:
    results: list[Result] = field(default_factory=list)
    backend: str = ""
    note: str = ""
    truncated: bool = False


def _unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    mapping = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            out.append(mapping.get(value[i + 1], value[i + 1]))
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _locale_keys(base: str) -> list[str]:
    """Prefer the user's locale, then the language, then the untranslated key."""
    lang = os.environ.get("LANG", "") or os.environ.get("LANGUAGE", "")
    lang = lang.split(":")[0].split(".")[0].strip()
    keys: list[str] = []
    if lang:
        keys.append(f"{base}[{lang}]")
        short = lang.split("_")[0]
        if short and short != lang:
            keys.append(f"{base}[{short}]")
    keys.append(base)
    return keys


def parse_desktop(path: Path) -> dict[str, str] | None:
    """Parse the Desktop Entry group. Returns None if the file cannot be read."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    group = None
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1].strip()
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = _unescape(value.strip())
    return data


def _pick(data: dict[str, str], base: str) -> str:
    for key in _locale_keys(base):
        value = data.get(key, "").strip()
        if value:
            return value
    return ""


def _is_true(value: str) -> bool:
    return value.strip().lower() == "true"


def _desktop_allowed(data: dict[str, str]) -> bool:
    if data.get("Type", "").strip() != "Application":
        return False
    if _is_true(data.get("Hidden", "")) or _is_true(data.get("NoDisplay", "")):
        return False
    current = {
        part.strip().casefold()
        for part in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
        if part.strip()
    }
    only = [p.strip().casefold() for p in data.get("OnlyShowIn", "").split(";") if p.strip()]
    if only and current and not current.intersection(only):
        return False
    not_in = [p.strip().casefold() for p in data.get("NotShowIn", "").split(";") if p.strip()]
    if not_in and current and current.intersection(not_in):
        return False
    return True


def application_dirs() -> list[Path]:
    """XDG application dirs, system first so the user dir overrides by id."""
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    raw_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    ordered: list[Path] = []
    for piece in raw_dirs.split(":"):
        if piece:
            ordered.append(Path(piece) / "applications")
    ordered.append(Path("/usr/share/applications"))
    ordered.append(home / ".local" / "share" / "applications")
    ordered.append(data_home / "applications")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in ordered:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _desktop_id(root: Path, file: Path) -> str:
    rel = file.relative_to(root).as_posix()
    if rel.endswith(".desktop"):
        rel = rel[: -len(".desktop")]
    return rel.replace("/", "-") + ".desktop"


def load_applications(dirs: list[Path] | None = None) -> list[AppEntry]:
    by_id: dict[str, AppEntry] = {}
    for root in dirs if dirs is not None else application_dirs():
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if not name.endswith(".desktop"):
                    continue
                file = Path(dirpath) / name
                data = parse_desktop(file)
                if not data or not _desktop_allowed(data):
                    continue
                desktop_id = _desktop_id(root, file)
                display = _pick(data, "Name") or file.stem
                by_id[desktop_id] = AppEntry(
                    desktop_id=desktop_id,
                    path=str(file),
                    name=display,
                    generic_name=_pick(data, "GenericName"),
                    comment=_pick(data, "Comment"),
                    keywords=_pick(data, "Keywords").replace(";", " "),
                    icon=data.get("Icon", "").strip(),
                )
    return list(by_id.values())


def _rank_text(query: str, text: str, base: int) -> int | None:
    folded = text.casefold()
    if not folded or query not in folded:
        return None
    if folded.startswith(query):
        return base
    return base + 1


def search_apps(apps: list[AppEntry], query: str, limit: int = MAX_RESULTS) -> list[Result]:
    needle = query.strip().casefold()
    if not needle:
        return []
    ranked: list[Result] = []
    for app in apps:
        score = None
        for text, base in (
            (app.name, 0),
            (app.generic_name, 10),
            (app.keywords, 20),
            (app.comment, 30),
        ):
            hit = _rank_text(needle, text, base)
            if hit is not None and (score is None or hit < score):
                score = hit
        if score is None:
            continue
        subtitle = app.generic_name or app.comment or app.desktop_id
        ranked.append(
            Result(
                title=app.name,
                subtitle=subtitle,
                kind="app",
                desktop_id=app.desktop_id,
                path=app.path,
                icon=app.icon or "application-x-executable-symbolic",
                rank=score,
            )
        )
    ranked.sort(key=lambda item: (item.rank, item.title.casefold()))
    return ranked[:limit]


def web_result(query: str) -> Result | None:
    text = query.strip()
    if not text:
        return None
    return Result(
        title=f"Search the web for “{text}”",
        subtitle="Opens DuckDuckGo in your browser",
        kind="web",
        url="https://duckduckgo.com/?q=" + quote_plus(text),
        icon="web-browser-symbolic",
    )


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(argv: list[str], timeout: float = COMMAND_TIMEOUT_S) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _strip_ansi(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\x1b" and i + 1 < len(text) and text[i + 1] == "[":
            i += 2
            while i < len(text) and text[i] not in "mK":
                i += 1
            i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _paths_from_output(text: str, limit: int) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw in _strip_ansi(text).splitlines():
        line = raw.strip().strip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if line.startswith("file://"):
            from urllib.parse import unquote, urlparse

            parsed = urlparse(line)
            if parsed.scheme != "file":
                continue
            line = unquote(parsed.path)
        if not line.startswith("/"):
            continue
        if line in seen:
            continue
        seen.add(line)
        paths.append(line)
        if len(paths) >= limit:
            break
    return paths


def _command_failed(proc: subprocess.CompletedProcess[str] | None) -> bool:
    if proc is None:
        return True
    err = (proc.stderr or "").casefold()
    if any(token in err for token in (
        "unknown command",
        "unrecognized",
        "invalid option",
        "database file not found",
        "no such file",
    )):
        return True
    if proc.returncode not in (0, 1):
        return True
    return False


def _file_results(paths: list[str]) -> list[Result]:
    results: list[Result] = []
    for path in paths:
        name = Path(path).name or path
        results.append(
            Result(
                title=name,
                subtitle=path,
                kind="file",
                path=path,
                icon="text-x-generic-symbolic",
            )
        )
    return results


def _indexed_search(argv: list[str], limit: int) -> list[str] | None:
    proc = _run(argv)
    if _command_failed(proc) or proc is None:
        return None
    return _paths_from_output(proc.stdout or "", limit)


def search_files(query: str, limit: int = MAX_RESULTS, home: Path | None = None) -> FileSearch:
    text = query.strip()
    if not text:
        return FileSearch(note="Type to search files")
    if "\x00" in text:
        return FileSearch(note="Ignored an empty search")

    if _which("tracker3"):
        found = _indexed_search(
            ["tracker3", "search", "--limit", str(limit), "--", text],
            limit,
        )
        if found is not None:
            return FileSearch(
                results=_file_results(found),
                backend="tracker3",
                note=f"{len(found)} files · tracker3",
            )

    if _which("tinysparql"):
        found = _indexed_search(
            ["tinysparql", "search", "--limit", str(limit), "--", text],
            limit,
        )
        if found is not None:
            return FileSearch(
                results=_file_results(found),
                backend="tinysparql",
                note=f"{len(found)} files · tinysparql",
            )

    for binary, label in (("plocate", "plocate"), ("locate", "locate")):
        if not _which(binary):
            continue
        # plocate/locate: -i case insensitive, -l cap, -e only files that exist.
        # locate from mlocate supports the same flags; if a binary rejects them,
        # _indexed_search returns None and we try the next backend.
        found = _indexed_search(
            [binary, "-i", "-e", "-l", str(limit), "--", text],
            limit,
        )
        if found is None:
            found = _indexed_search([binary, "-i", "-l", str(limit), "--", text], limit)
        if found is not None:
            return FileSearch(
                results=_file_results(found),
                backend=label,
                note=f"{len(found)} files · {label}",
            )

    return _walk_files(text, limit, home or Path.home())


def _walk_roots(home: Path) -> list[Path]:
    return [home / "Documents", home / "Downloads", home / "Desktop"]


def _walk_files(query: str, limit: int, home: Path) -> FileSearch:
    needle = query.casefold()
    roots = [path for path in _walk_roots(home) if path.is_dir()]
    if not roots:
        return FileSearch(
            backend="walk",
            note="No tracker3, tinysparql, plocate, or locate, and no Documents, Downloads, or Desktop folder",
        )
    hits: list[str] = []
    seen_entries = 0
    deadline = time.monotonic() + WALK_DEADLINE_S
    truncated = False
    for root in roots:
        if truncated:
            break
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".") and name not in SKIP_WALK_DIRS
            ]
            if time.monotonic() > deadline or seen_entries >= WALK_MAX_ENTRIES:
                truncated = True
                break
            for name in filenames:
                seen_entries += 1
                if name.startswith("."):
                    continue
                full = str(Path(dirpath) / name)
                if needle in name.casefold() or needle in full.casefold():
                    hits.append(full)
                    if len(hits) >= limit:
                        truncated = True
                        break
                if seen_entries >= WALK_MAX_ENTRIES:
                    truncated = True
                    break
            if truncated:
                break
    note = f"{len(hits)} files · folder scan"
    if truncated:
        note += " (capped)"
    return FileSearch(
        results=_file_results(hits),
        backend="walk",
        note=note,
        truncated=truncated,
    )
