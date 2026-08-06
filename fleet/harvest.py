#!/usr/bin/env python3
"""Fleet context harvester for the multi-agent sleep-tracker project.

Reads the on-disk transcripts of every AI coding agent working on this
project (Claude Code, Codex, Cline, Grok), normalizes them into a single
event stream, and writes a pasteable digest so a new agent can be briefed
instantly and so nothing learned in one terminal is lost to the others.

Design notes
------------
* stdlib only, Python 3.9+ -- no third-party imports anywhere.
* read-only with respect to every path except ``<project>/fleet/``.
* streams JSONL line-by-line; malformed lines are skipped and counted.
* every text field is redacted for passwords/tokens/API keys before it is
  stored in an event, so nothing secret can reach stdout or the digest.

Commands
--------
    harvest.py digest [--since 24h] [--out fleet/FLEET_CONTEXT.md]
    harvest.py brief --for "role name"
    harvest.py watch [--interval 60]
    harvest.py sessions [--since 24h]

Adding a new tool = adding one Adapter subclass; see fleet/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

__all__ = [
    "Config",
    "Event",
    "SessionRef",
    "HarvestResult",
    "ADAPTERS",
    "redact",
    "extract_paths",
    "parse_since",
    "harvest",
    "render_digest",
    "render_brief",
    "find_collisions",
    "safe_output_path",
    "main",
]

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

KINDS = (
    "user_prompt",
    "assistant_message",
    "tool_call",
    "tool_result",
    "error",
    "summary",
)

TEXT_CAP = 600  # per-item truncation in the rendered digest
MAX_JSON_BYTES = 128 * 1024 * 1024  # refuse to json.load() anything bigger
REDACTED = "[REDACTED]"

NOISE_PARTS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".pytest_cache",
    "node_modules",
    "site-packages",
    ".mypy_cache",
    ".ruff_cache",
    "dist-info",
    ".DS_Store",
}

CODE_EXTS = {
    "py", "js", "ts", "tsx", "jsx", "css", "html", "htm", "md", "json",
    "yml", "yaml", "toml", "ini", "cfg", "txt", "sh", "bash", "zsh", "sql",
    "swift", "plist", "entitlements", "csv", "xml", "lock", "env", "rst",
}
SPECIAL_NAMES = {
    "Dockerfile", "Makefile", ".gitignore", ".dockerignore", "Procfile",
    "requirements.txt", "requirements-dev.txt",
}

# Tool names that mean "this agent modified the file".
WRITE_TOOLS = {
    # Claude Code
    "write", "edit", "multiedit", "notebookedit",
    # Cline
    "editedexistingfile", "newfilecreated", "write_to_file", "replace_in_file",
    # Grok
    "search_replace", "create_file", "edit_file",
    # Codex
    "apply_patch", "patch",
}
READ_TOOLS = {
    "read", "grep", "glob", "ls", "readfile", "listfilestoplevel",
    "listfilesrecursive", "searchfiles", "read_file", "list_dir",
    "view_image", "todo_write", "update_plan",
}

# Shell fragments that indicate a write to a path.
SHELL_WRITE_RE = re.compile(
    r"(?:^|[;&|]\s*|\s)(?:apply_patch|sed\s+-i|tee\b|patch\b|touch\b|mv\b|cp\b|rm\b"
    r"|python[0-9.]*\s+-\s*<<|cat\s*>>?|dd\b)|>>?\s*(?!\s)",
    re.IGNORECASE,
)
# `*** Add File: path` / `*** Update File: path` inside codex apply_patch heredocs.
APPLY_PATCH_RE = re.compile(
    r"\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(\S+)", re.IGNORECASE
)

ERROR_HINT_RE = re.compile(
    r"(traceback \(most recent call last\)|\bexit(?:ed)? (?:with )?code [1-9]"
    r"|\berror:|\bexception\b|\bfailed\b|\bassertionerror\b|\bfatal\b"
    r"|\d+ failed\b|command not found|permission denied|no such file)",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

_SECRET_KEY = (
    r"(?:[A-Za-z0-9_.\-]*"
    r"(?:passwd|password|secret|token|api[_\-]?key|apikey|access[_\-]?key"
    r"|auth[_\-]?token|authorization|client[_\-]?secret|private[_\-]?key)"
    r"[A-Za-z0-9_.\-]*)"
)

_REDACTORS = (
    # "api_key": "value" / api_key=value / api-key: value
    (
        re.compile(
            r"(?i)(['\"]?" + _SECRET_KEY + r"['\"]?\s*[:=]\s*)(['\"]?)"
            r"([^\s'\",;)}\]]{1,})"
        ),
        lambda m: m.group(1) + m.group(2) + REDACTED,
    ),
    # Authorization: Bearer xxxx
    (re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._\-]{8,})"), lambda m: m.group(1) + REDACTED),
    # Well-known token shapes.
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b"),
     lambda m: REDACTED),
)


def redact(text):
    """Return *text* with anything password/token/api-key shaped removed."""
    if not text:
        return text
    if not isinstance(text, str):
        text = str(text)
    for pattern, repl in _REDACTORS:
        text = pattern.sub(repl, text)
    return text


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def clip(text, limit=TEXT_CAP):
    """Truncate long text so the digest stays pasteable."""
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " ... [+%d chars]" % (len(text) - limit)


def one_line(text, limit=160):
    return clip(" ".join(str(text or "").split()), limit)


def parse_since(spec, now=None):
    """Parse ``24h`` / ``90m`` / ``7d`` / ``all`` / ISO timestamp -> datetime (UTC)."""
    now = now or datetime.now(timezone.utc)
    if spec is None:
        spec = "24h"
    spec = str(spec).strip().lower()
    if spec in ("all", "0", "forever", "none"):
        return datetime.fromtimestamp(0, timezone.utc)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhdw])", spec)
    if m:
        n = float(m.group(1))
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[m.group(2)]
        return now - timedelta(**{unit: n})
    dt = parse_ts(spec)
    if dt is None:
        raise ValueError("cannot parse --since value: %r (try 24h, 7d, or an ISO date)" % spec)
    return dt


def parse_ts(value):
    """Best-effort timestamp parser -> aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e11:  # milliseconds
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            if re.fullmatch(r"\d+(\.\d+)?", value.strip()):
                return parse_ts(float(value))
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def iso(dt):
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local(dt):
    if dt is None:
        return ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def is_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


# --------------------------------------------------------------------------
# streaming readers (never blow up on malformed input)
# --------------------------------------------------------------------------


class ReadStats(object):
    """Counters for parse health -- surfaced at the bottom of the digest."""

    def __init__(self):
        self.files_read = 0
        self.lines_read = 0
        self.bad_lines = 0
        self.unreadable = []  # (path, reason)

    def note_unreadable(self, path, exc):
        self.unreadable.append((str(path), "%s: %s" % (type(exc).__name__, exc)))

    def as_dict(self):
        return {
            "files_read": self.files_read,
            "lines_read": self.lines_read,
            "bad_lines": self.bad_lines,
            "unreadable": list(self.unreadable),
        }


def iter_jsonl(path, stats):
    """Yield decoded objects from a JSONL file, streaming line by line.

    Malformed / truncated lines are skipped and counted; the file is never
    fully materialized, so hundreds-of-MB transcripts are fine.
    """
    try:
        handle = open(str(path), "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        stats.note_unreadable(path, exc)
        return
    stats.files_read += 1
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            stats.lines_read += 1
            try:
                obj = json.loads(line)
            except (ValueError, RecursionError):
                stats.bad_lines += 1
                continue
            if isinstance(obj, dict):
                yield obj
            else:
                stats.bad_lines += 1


def load_json(path, stats, default=None):
    """json.load() with size guard and total error tolerance."""
    try:
        size = os.path.getsize(str(path))
    except OSError as exc:
        stats.note_unreadable(path, exc)
        return default
    if size > MAX_JSON_BYTES:
        stats.note_unreadable(path, RuntimeError("file too large (%d bytes)" % size))
        return default
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            stats.files_read += 1
            return json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        stats.bad_lines += 1
        stats.note_unreadable(path, exc)
        return default


def newest_mtime(paths):
    best = 0.0
    for p in paths:
        try:
            best = max(best, os.path.getmtime(str(p)))
        except OSError:
            continue
    return best


# --------------------------------------------------------------------------
# path extraction
# --------------------------------------------------------------------------

_PATH_TOKEN_RE = re.compile(
    r"(?<![\w@])((?:~|\.{1,2})?(?:/)?(?:[\w.+\-]+/)*[\w.+\-]+\.[A-Za-z0-9]{1,12})"
)


def _clean_token(token):
    token = token.strip().strip("'\"`,;:()[]{}<>")
    token = token.rstrip(".")
    return token


def extract_paths(text, project_root, known_files=None, absolute_only=False):
    """Return project-relative paths mentioned in *text*.

    Only paths that resolve inside *project_root* are returned; noise
    directories (.venv, __pycache__, .git, ...) are dropped. When
    *absolute_only* is set, bare relative mentions are ignored -- used for
    sessions whose cwd is a different checkout, so their relative paths are
    not mis-attributed to this project.
    """
    if not text:
        return []
    if not isinstance(text, str):
        try:
            text = json.dumps(text, default=str)
        except (TypeError, ValueError):
            text = str(text)
    project_root = str(project_root).rstrip("/")
    found = []
    seen = set()

    def add(rel):
        if rel and rel not in seen:
            seen.add(rel)
            found.append(rel)

    for raw in _PATH_TOKEN_RE.findall(text):
        token = _clean_token(raw)
        if not token or len(token) > 240:
            continue
        base = os.path.basename(token)
        ext = base.rsplit(".", 1)[-1] if "." in base else ""
        if base not in SPECIAL_NAMES and ext.lower() not in CODE_EXTS:
            continue
        is_abs = token.startswith("/") or token.startswith("~")
        if token.startswith("~"):
            token = os.path.expanduser(token)
        if is_abs:
            if not (token == project_root or token.startswith(project_root + "/")):
                continue
            rel = token[len(project_root) + 1:]
        else:
            if absolute_only:
                continue
            rel = token.lstrip("./")
            if not rel:
                continue
            if "/" not in rel and known_files is not None and rel not in known_files:
                continue
            if known_files is None and "/" not in rel:
                continue
        if not rel or rel.startswith("../"):
            continue
        if any(part in NOISE_PARTS for part in rel.split("/")):
            continue
        add(rel)

    # Codex apply_patch heredocs name their targets explicitly.
    for raw in APPLY_PATCH_RE.findall(text):
        token = _clean_token(raw)
        if token.startswith(project_root + "/"):
            token = token[len(project_root) + 1:]
        token = token.lstrip("./")
        if token and not token.startswith("../") and not any(
            part in NOISE_PARTS for part in token.split("/")
        ):
            add(token)
    return found


def looks_like_write(tool_name, text):
    """True when the tool call / command appears to modify files."""
    name = (tool_name or "").strip().lower()
    if name in WRITE_TOOLS:
        return True
    if name in READ_TOOLS:
        return False
    if not text:
        return False
    if not isinstance(text, str):
        text = str(text)
    if APPLY_PATCH_RE.search(text):
        return True
    return bool(SHELL_WRITE_RE.search(text))


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------


class Event(object):
    """The single normalized record every adapter produces."""

    __slots__ = (
        "tool", "session_id", "timestamp", "role", "kind", "text",
        "files_touched", "files_written", "tool_name",
    )

    def __init__(self, tool, session_id, timestamp, role, kind, text,
                 files_touched=None, files_written=None, tool_name=None):
        if kind not in KINDS:
            raise ValueError("unknown kind: %r" % kind)
        self.tool = tool
        self.session_id = session_id
        self.timestamp = timestamp  # aware datetime (UTC) or None
        self.role = role
        self.kind = kind
        self.text = redact(text or "")
        self.files_touched = list(files_touched or [])
        self.files_written = list(files_written or [])
        self.tool_name = tool_name

    @property
    def ts(self):
        return iso(self.timestamp)

    def to_dict(self):
        return {
            "tool": self.tool,
            "session_id": self.session_id,
            "timestamp": iso(self.timestamp),
            "role": self.role,
            "kind": self.kind,
            "text": self.text,
            "files_touched": list(self.files_touched),
            "files_written": list(self.files_written),
        }

    def __repr__(self):  # pragma: no cover - debug helper
        return "<Event %s/%s %s %s>" % (self.tool, self.session_id[:8], self.kind, self.ts)


class SessionRef(object):
    """A discovered transcript, before (and after) parsing."""

    def __init__(self, tool, session_id, paths, cwd=None, label=None, meta=None):
        self.tool = tool
        self.session_id = session_id
        self.paths = [str(p) for p in paths]
        self.cwd = cwd
        self.label = label or ""
        self.meta = meta or {}
        self.events = []
        self.match = "unknown"  # cwd | mention | none

    @property
    def key(self):
        return "%s:%s" % (self.tool, self.session_id)

    @property
    def short(self):
        """A stable, human-sized id that stays unique across sibling sessions."""
        sid = self.session_id
        if len(sid) <= 16:
            return sid
        if "/" in sid:
            head, tail = sid.split("/", 1)
            return "%s/%s" % (head[:8], tail[:12])
        return sid[:13]

    @property
    def start(self):
        stamps = [e.timestamp for e in self.events if e.timestamp]
        return min(stamps) if stamps else None

    @property
    def end(self):
        stamps = [e.timestamp for e in self.events if e.timestamp]
        return max(stamps) if stamps else None

    def by_kind(self, kind):
        return [e for e in self.events if e.kind == kind]

    def file_counts(self):
        counter = Counter()
        for event in self.events:
            for path in event.files_touched:
                counter[path] += 1
        return counter

    def to_dict(self):
        return {
            "tool": self.tool,
            "session_id": self.session_id,
            "label": self.label,
            "cwd": self.cwd,
            "match": self.match,
            "paths": self.paths,
            "start": iso(self.start),
            "end": iso(self.end),
            "events": len(self.events),
            "files": [f for f, _ in self.file_counts().most_common()],
        }


class Config(object):
    """Everything the harvester needs to know about where things live."""

    def __init__(self, project_root=None, home=None, since=None, strict_cwd=False,
                 include_subagents=True, now=None):
        self.project_root = str(Path(project_root or Path(__file__).resolve().parent.parent).resolve())
        self.project_name = os.path.basename(self.project_root)
        self.home = str(Path(home).resolve()) if home else os.path.expanduser("~")
        self.now = now or datetime.now(timezone.utc)
        self.since = since if isinstance(since, datetime) else parse_since(since, self.now)
        self.strict_cwd = strict_cwd
        self.include_subagents = include_subagents
        self.fleet_dir = os.path.join(self.project_root, "fleet")
        self._known_files = None

    def home_path(self, *parts):
        return os.path.join(self.home, *parts)

    @property
    def known_files(self):
        """Shallow index of real project files, to validate bare filenames."""
        if self._known_files is None:
            found = set()
            root = self.project_root
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in NOISE_PARTS and not d.startswith(".git")]
                rel_dir = os.path.relpath(dirpath, root)
                for name in filenames:
                    rel = name if rel_dir == "." else os.path.join(rel_dir, name)
                    found.add(rel)
                    if len(found) > 20000:
                        break
                if len(found) > 20000:
                    break
            self._known_files = found
        return self._known_files


class HarvestResult(object):
    def __init__(self, config, sessions, stats, skipped):
        self.config = config
        self.sessions = sessions
        self.stats = stats
        self.skipped = skipped  # sessions discovered but outside window/project

    @property
    def events(self):
        out = []
        for session in self.sessions:
            out.extend(session.events)
        out.sort(key=lambda e: (e.timestamp or self.config.since))
        return out

    def by_tool(self):
        grouped = defaultdict(list)
        for session in self.sessions:
            grouped[session.tool].append(session)
        for sessions in grouped.values():
            sessions.sort(key=lambda s: (s.start or self.config.since))
        return grouped

    def to_dict(self):
        return {
            "generated_at": iso(datetime.now(timezone.utc)),
            "project_root": self.config.project_root,
            "since": iso(self.config.since),
            "sessions": [s.to_dict() for s in self.sessions],
            "collisions": [c.to_dict() for c in find_collisions(self)],
            "parse_stats": self.stats.as_dict(),
        }


# --------------------------------------------------------------------------
# adapters -- one per tool. Add a new tool by subclassing Adapter.
# --------------------------------------------------------------------------


class Adapter(object):
    tool = "unknown"

    def discover(self, config, stats):
        """Yield SessionRef objects (cheap: filenames/metadata only)."""
        raise NotImplementedError

    def parse(self, session, config, stats):
        """Yield Event objects for one SessionRef."""
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------
    def files_for(self, text, session, config, write=False):
        absolute_only = session.match == "mention"
        touched = extract_paths(
            text, config.project_root, config.known_files, absolute_only=absolute_only
        )
        return touched, (list(touched) if write else [])


class ClaudeCodeAdapter(Adapter):
    """~/.claude/projects/<slug>/<session>.jsonl (+ subagents/*.jsonl)."""

    tool = "claude_code"

    def project_dirs(self, config):
        root = Path(config.home_path(".claude", "projects"))
        if not root.is_dir():
            return []
        wanted = config.project_root.replace("/", "-")
        out = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.name == wanted or config.project_name in child.name:
                out.append(child)
        return out

    def discover(self, config, stats):
        for pdir in self.project_dirs(config):
            exact = pdir.name == config.project_root.replace("/", "-")
            for jsonl in sorted(pdir.glob("*.jsonl")):
                yield SessionRef(
                    self.tool,
                    jsonl.stem,
                    [jsonl],
                    cwd=config.project_root if exact else None,
                    label="main session",
                )
                sub = pdir / jsonl.stem / "subagents"
                if config.include_subagents and sub.is_dir():
                    for agent in sorted(sub.glob("*.jsonl")):
                        meta = {}
                        meta_path = agent.with_suffix(".meta.json")
                        if meta_path.exists():
                            meta = load_json(meta_path, stats, {}) or {}
                        label = meta.get("name") or meta.get("agentType") or meta.get("description") or "subagent"
                        yield SessionRef(
                            self.tool,
                            "%s/%s" % (jsonl.stem[:8], agent.stem.replace("agent-", "sub-")),
                            [agent],
                            cwd=config.project_root if exact else None,
                            label="subagent: %s" % one_line(label, 60),
                            meta=meta,
                        )

    def parse(self, session, config, stats):
        path = session.paths[0]
        for obj in iter_jsonl(path, stats):
            rtype = obj.get("type")
            ts = parse_ts(obj.get("timestamp"))
            cwd = obj.get("cwd")
            if cwd and not session.cwd:
                session.cwd = cwd
            if rtype == "file-history-delta":
                rel = obj.get("trackingPath") or ""
                parent = obj.get("backup", {}).get("realParentDir") or ""
                full = rel if rel.startswith("/") else os.path.join(parent or config.project_root, os.path.basename(rel))
                touched = extract_paths(full, config.project_root, config.known_files)
                if not touched:
                    touched = extract_paths(rel, config.project_root, config.known_files)
                yield Event(self.tool, session.session_id, ts, "assistant", "tool_call",
                            "file edit snapshot: %s" % rel, touched, touched, tool_name="Edit")
                continue
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role == "user":
                if isinstance(content, str):
                    text = content
                    if text.startswith("[Request interrupted"):
                        continue
                    touched, _ = self.files_for(text, session, config)
                    yield Event(self.tool, session.session_id, ts, "user", "user_prompt", text, touched)
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_result":
                            body = _flatten_content(block.get("content"))
                            kind = "error" if block.get("is_error") or ERROR_HINT_RE.search(body[:2000] or "") else "tool_result"
                            touched, _ = self.files_for(body, session, config)
                            yield Event(self.tool, session.session_id, ts, "tool", kind, body, touched)
                        elif block.get("type") == "text":
                            text = block.get("text") or ""
                            if text.startswith("[Request interrupted"):
                                continue
                            touched, _ = self.files_for(text, session, config)
                            yield Event(self.tool, session.session_id, ts, "user", "user_prompt", text, touched)
            elif role == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text = block.get("text") or ""
                        if not text.strip():
                            continue
                        touched, _ = self.files_for(text, session, config)
                        yield Event(self.tool, session.session_id, ts, "assistant",
                                    "assistant_message", text, touched)
                    elif btype == "tool_use":
                        name = block.get("name") or ""
                        payload = block.get("input") or {}
                        text = "%s %s" % (name, json.dumps(payload, default=str))
                        write = looks_like_write(name, json.dumps(payload, default=str))
                        target = " ".join(
                            str(payload.get(k, "")) for k in
                            ("file_path", "path", "notebook_path", "command", "pattern", "target_file")
                        )
                        touched, written = self.files_for(target or text, session, config, write=write)
                        yield Event(self.tool, session.session_id, ts, "assistant", "tool_call",
                                    text, touched, written, tool_name=name)


class CodexAdapter(Adapter):
    """~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl + ~/.codex/history.jsonl."""

    tool = "codex"

    def discover(self, config, stats):
        root = Path(config.home_path(".codex", "sessions"))
        if not root.is_dir():
            return
        prompts = self._history(config, stats)
        for jsonl in sorted(root.glob("*/*/*/rollout-*.jsonl")):
            sid = self._session_id(jsonl.name)
            yield SessionRef(self.tool, sid, [jsonl], label="rollout",
                             meta={"prompts": prompts.get(sid, [])})

    @staticmethod
    def _session_id(filename):
        m = re.match(r"rollout-\d{4}-\d{2}-\d{2}T[\d-]+-(.+)\.jsonl$", filename)
        return m.group(1) if m else filename

    def _history(self, config, stats):
        """~/.codex/history.jsonl maps session_id -> user prompts."""
        path = Path(config.home_path(".codex", "history.jsonl"))
        prompts = defaultdict(list)
        if not path.exists():
            return prompts
        for obj in iter_jsonl(path, stats):
            sid = obj.get("session_id")
            text = obj.get("text")
            if sid and text:
                prompts[sid].append((parse_ts(obj.get("ts")), text))
        return prompts

    def parse(self, session, config, stats):
        seen_prompts = set()
        for obj in iter_jsonl(session.paths[0], stats):
            ts = parse_ts(obj.get("timestamp"))
            otype = obj.get("type")
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            if not payload and isinstance(obj.get("item"), dict):
                payload = obj["item"]
            ptype = payload.get("type") or otype
            if otype == "session_meta" or ptype == "session_meta":
                if payload.get("cwd"):
                    session.cwd = payload["cwd"]
                session.meta.setdefault("model_provider", payload.get("model_provider"))
                session.meta.setdefault("cli_version", payload.get("cli_version"))
                continue
            if otype == "turn_context" and payload.get("cwd") and not session.cwd:
                session.cwd = payload["cwd"]
                continue
            if ptype == "user_message":
                text = payload.get("message") or ""
                if _is_boilerplate(text):
                    continue
                seen_prompts.add(text.strip()[:200])
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, ts, "user", "user_prompt", text, touched)
            elif ptype == "agent_message":
                text = payload.get("message") or ""
                if not text.strip():
                    continue
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, ts, "assistant", "assistant_message", text, touched)
            elif ptype == "message":
                role = payload.get("role")
                text = _flatten_content(payload.get("content"))
                if not text.strip() or _is_boilerplate(text):
                    continue
                if role == "user":
                    if text.strip()[:200] in seen_prompts:
                        continue
                    seen_prompts.add(text.strip()[:200])
                    touched, _ = self.files_for(text, session, config)
                    yield Event(self.tool, session.session_id, ts, "user", "user_prompt", text, touched)
                elif role == "assistant":
                    continue  # duplicated by agent_message
            elif ptype == "function_call":
                name = payload.get("name") or ""
                args = payload.get("arguments") or ""
                text = "%s %s" % (name, args)
                write = looks_like_write(name, args)
                touched, written = self.files_for(args, session, config, write=write)
                yield Event(self.tool, session.session_id, ts, "assistant", "tool_call",
                            text, touched, written, tool_name=name)
            elif ptype == "function_call_output":
                body = payload.get("output")
                if isinstance(body, dict):
                    body = body.get("content") or json.dumps(body, default=str)
                if not isinstance(body, str):
                    body = _flatten_content(body)
                body = body or ""
                kind = "error" if ERROR_HINT_RE.search(body[:4000]) else "tool_result"
                touched, _ = self.files_for(body, session, config)
                yield Event(self.tool, session.session_id, ts, "tool", kind, body, touched)
            elif ptype == "task_complete":
                text = payload.get("last_agent_message") or ""
                if text.strip():
                    touched, _ = self.files_for(text, session, config)
                    yield Event(self.tool, session.session_id, ts, "assistant", "summary", text, touched)
            elif ptype in ("error", "stream_error", "turn_aborted"):
                text = payload.get("message") or json.dumps(payload, default=str)
                yield Event(self.tool, session.session_id, ts, "system", "error", text)

        # history.jsonl prompts the rollout may not carry (compaction, resume).
        for ts, text in session.meta.get("prompts", []):
            if text.strip()[:200] in seen_prompts:
                continue
            seen_prompts.add(text.strip()[:200])
            touched, _ = self.files_for(text, session, config)
            yield Event(self.tool, session.session_id, ts, "user", "user_prompt", text, touched)


class ClineAdapter(Adapter):
    """VS Code globalStorage/saoudrizwan.claude-dev/tasks/<ms-timestamp>/."""

    tool = "cline"

    def tasks_root(self, config):
        return Path(config.home_path(
            "Library", "Application Support", "Code", "User", "globalStorage",
            "saoudrizwan.claude-dev", "tasks",
        ))

    def discover(self, config, stats):
        root = self.tasks_root(config)
        if not root.is_dir():
            return
        for task_dir in sorted(root.iterdir()):
            if not task_dir.is_dir():
                continue
            ui = task_dir / "ui_messages.json"
            api = task_dir / "api_conversation_history.json"
            paths = [p for p in (ui, api) if p.exists()]
            if not paths:
                continue
            yield SessionRef(self.tool, task_dir.name, paths, label="task")

    def parse(self, session, config, stats):
        task_dir = Path(session.paths[0]).parent
        ui = load_json(task_dir / "ui_messages.json", stats, []) or []
        if not isinstance(ui, list):
            ui = []
        # cwd shows up in the prompt text Cline sends to the model.
        for message in ui[:80]:
            text = message.get("text") if isinstance(message, dict) else None
            if not isinstance(text, str):
                continue
            m = re.search(r"Current Working Directory \(([^)]+)\)", text)
            if m:
                session.cwd = m.group(1)
                break

        for message in ui:
            if not isinstance(message, dict):
                continue
            ts = parse_ts(message.get("ts"))
            mtype = message.get("type")
            say = message.get("say")
            ask = message.get("ask")
            text = message.get("text") or ""
            if mtype == "say" and say in ("task", "user_feedback"):
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, ts, "user", "user_prompt", text, touched)
            elif mtype == "say" and say in ("text", "reasoning"):
                if not text.strip():
                    continue
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, ts, "assistant", "assistant_message", text, touched)
            elif mtype == "say" and say == "completion_result":
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, ts, "assistant", "summary", text, touched)
            elif mtype == "say" and say == "tool":
                payload = _maybe_json(text) or {}
                name = payload.get("tool") or "tool"
                target = payload.get("path") or ""
                write = looks_like_write(name, target)
                touched, written = self.files_for(target or text, session, config, write=write)
                yield Event(self.tool, session.session_id, ts, "assistant", "tool_call",
                            "%s %s" % (name, target or one_line(text, 200)),
                            touched, written, tool_name=name)
            elif mtype == "say" and say == "command":
                write = looks_like_write("bash", text)
                touched, written = self.files_for(text, session, config, write=write)
                yield Event(self.tool, session.session_id, ts, "assistant", "tool_call",
                            "$ %s" % text, touched, written, tool_name="command")
            elif mtype == "say" and say in ("error", "error_retry", "diff_error"):
                payload = _maybe_json(text)
                body = payload.get("errorMessage") if isinstance(payload, dict) else None
                yield Event(self.tool, session.session_id, ts, "system", "error", body or text)
            elif mtype == "ask" and ask in ("api_req_failed", "mistake_limit_reached", "auto_approval_max_req_reached"):
                yield Event(self.tool, session.session_id, ts, "system", "error", text)
            elif mtype == "ask" and ask in ("plan_mode_respond", "followup", "completion_result"):
                payload = _maybe_json(text)
                body = text
                if isinstance(payload, dict):
                    body = payload.get("response") or payload.get("question") or text
                if not str(body).strip():
                    continue
                kind = "summary" if ask == "completion_result" else "assistant_message"
                touched, _ = self.files_for(body, session, config)
                yield Event(self.tool, session.session_id, ts, "assistant", kind, body, touched)
            elif mtype == "ask" and ask == "command_output":
                kind = "error" if ERROR_HINT_RE.search(text[:2000]) else "tool_result"
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, ts, "tool", kind, text, touched)

        # task_metadata.json records authoritative read/edit timestamps.
        meta = load_json(task_dir / "task_metadata.json", stats, {}) or {}
        for entry in meta.get("files_in_context", []) or []:
            if not isinstance(entry, dict):
                continue
            rel = entry.get("path") or ""
            edited = parse_ts(entry.get("cline_edit_date"))
            read = parse_ts(entry.get("cline_read_date"))
            touched, _ = self.files_for(rel, session, config)
            if not touched:
                continue
            if edited:
                yield Event(self.tool, session.session_id, edited, "assistant", "tool_call",
                            "edited %s" % rel, touched, touched, tool_name="editedExistingFile")
            elif read:
                yield Event(self.tool, session.session_id, read, "assistant", "tool_call",
                            "read %s" % rel, touched, [], tool_name="readFile")


class GrokAdapter(Adapter):
    """~/.grok/sessions/<url-encoded-cwd>/<session-id>/*.

    chat_history.jsonl carries the content but no timestamps; events.jsonl
    carries timestamps in the same order, so the two are zipped together.
    hunk_records.jsonl is the authoritative (timestamped) edit log.
    """

    tool = "grok"

    def discover(self, config, stats):
        root = Path(config.home_path(".grok", "sessions"))
        if not root.is_dir():
            return
        for cwd_dir in sorted(root.iterdir()):
            if not cwd_dir.is_dir():
                continue
            cwd = unquote(cwd_dir.name)
            for session_dir in sorted(cwd_dir.iterdir()):
                if not session_dir.is_dir():
                    continue
                chat = session_dir / "chat_history.jsonl"
                if not chat.exists():
                    continue
                summary = load_json(session_dir / "summary.json", stats, {}) or {}
                info = summary.get("info") or {}
                paths = [p for p in (
                    chat,
                    session_dir / "events.jsonl",
                    session_dir / "hunk_records.jsonl",
                    cwd_dir / "prompt_history.jsonl",
                ) if p.exists()]
                yield SessionRef(
                    self.tool,
                    info.get("id") or session_dir.name,
                    paths,
                    cwd=info.get("cwd") or cwd,
                    label=one_line(summary.get("session_summary") or summary.get("generated_title") or "session", 70),
                    meta={"summary": summary, "dir": str(session_dir), "cwd_dir": str(cwd_dir)},
                )

    def parse(self, session, config, stats):
        session_dir = Path(session.meta.get("dir") or Path(session.paths[0]).parent)
        summary = session.meta.get("summary") or {}
        created = parse_ts(summary.get("created_at"))
        updated = parse_ts(summary.get("updated_at")) or created

        # 1. prompts (timestamped, in the per-cwd prompt_history.jsonl)
        prompt_history = Path(session.meta.get("cwd_dir") or session_dir.parent) / "prompt_history.jsonl"
        if prompt_history.exists():
            for obj in iter_jsonl(prompt_history, stats):
                if obj.get("session_id") != session.session_id:
                    continue
                text = obj.get("prompt") or ""
                if not text.strip():
                    continue
                touched, _ = self.files_for(text, session, config)
                yield Event(self.tool, session.session_id, parse_ts(obj.get("timestamp")),
                            "user", "user_prompt", text, touched)

        # 2. timestamps for model output / tool calls, from events.jsonl
        first_tokens, tool_started, tool_completed, failures = [], [], [], []
        events_path = session_dir / "events.jsonl"
        if events_path.exists():
            for obj in iter_jsonl(events_path, stats):
                ts = parse_ts(obj.get("ts"))
                etype = obj.get("type")
                if etype == "first_token":
                    first_tokens.append(ts)
                elif etype == "tool_started":
                    tool_started.append(ts)
                elif etype == "tool_completed":
                    tool_completed.append((ts, obj.get("tool_name"), obj.get("outcome")))
                    if obj.get("outcome") not in (None, "success"):
                        failures.append((ts, obj.get("tool_name"), obj.get("outcome")))
                elif etype == "turn_ended" and obj.get("outcome") not in (None, "completed"):
                    failures.append((ts, "turn", obj.get("outcome")))

        def stamp(bucket, index, fallback):
            if index < len(bucket):
                value = bucket[index]
                return value[0] if isinstance(value, tuple) else value
            return fallback

        # 3. content, from chat_history.jsonl (assistant text + tool calls)
        msg_index = 0
        call_index = 0
        result_index = 0
        last_assistant = None
        for obj in iter_jsonl(session_dir / "chat_history.jsonl", stats):
            otype = obj.get("type")
            if otype == "assistant":
                ts = stamp(first_tokens, msg_index, updated)
                msg_index += 1
                text = obj.get("content")
                if isinstance(text, list):
                    text = _flatten_content(text)
                if text and str(text).strip():
                    touched, _ = self.files_for(text, session, config)
                    last_assistant = (ts, str(text))
                    yield Event(self.tool, session.session_id, ts, "assistant",
                                "assistant_message", str(text), touched)
                for call in obj.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    cts = stamp(tool_started, call_index, ts)
                    call_index += 1
                    name = call.get("name") or "tool"
                    args = call.get("arguments") or ""
                    if isinstance(args, dict):
                        args = json.dumps(args, default=str)
                    parsed = _maybe_json(args) or {}
                    target = " ".join(str(parsed.get(k, "")) for k in
                                      ("target_file", "file_path", "path", "target_directory", "command"))
                    write = looks_like_write(name, target or args)
                    touched, written = self.files_for(target or args, session, config, write=write)
                    yield Event(self.tool, session.session_id, cts, "assistant", "tool_call",
                                "%s %s" % (name, one_line(target or args, 300)),
                                touched, written, tool_name=name)
            elif otype == "tool_result":
                ts = stamp(tool_completed, result_index, updated)
                result_index += 1
                body = obj.get("content")
                if isinstance(body, list):
                    body = _flatten_content(body)
                body = str(body or "")
                kind = "error" if ERROR_HINT_RE.search(body[:2000]) else "tool_result"
                touched, _ = self.files_for(body, session, config)
                yield Event(self.tool, session.session_id, ts, "tool", kind, body, touched)
            elif otype == "user":
                continue  # covered by prompt_history

        # 4. authoritative edits
        hunks = session_dir / "hunk_records.jsonl"
        if hunks.exists():
            for obj in iter_jsonl(hunks, stats):
                if obj.get("authorType") not in (None, "agent"):
                    continue
                rel = extract_paths(obj.get("filePath") or "", config.project_root, config.known_files)
                if not rel:
                    continue
                text = "edit %s (+%s/-%s)" % (
                    rel[0], obj.get("linesAdded", "?"), obj.get("linesRemoved", "?"))
                yield Event(self.tool, session.session_id, parse_ts(obj.get("timestamp")),
                            "assistant", "tool_call", text, rel, rel, tool_name="write")

        for ts, name, outcome in failures:
            yield Event(self.tool, session.session_id, ts, "system", "error",
                        "%s failed: %s" % (name, outcome))

        if last_assistant:
            ts, text = last_assistant
            yield Event(self.tool, session.session_id, ts, "assistant", "summary", text,
                        extract_paths(text, config.project_root, config.known_files))
        elif summary.get("session_summary"):
            yield Event(self.tool, session.session_id, updated, "assistant", "summary",
                        str(summary.get("session_summary")))


ADAPTERS = [ClaudeCodeAdapter(), CodexAdapter(), ClineAdapter(), GrokAdapter()]


# --------------------------------------------------------------------------
# shared parsing helpers
# --------------------------------------------------------------------------

_BOILERPLATE_PREFIXES = (
    "<environment_context>", "<permissions instructions>", "<user_instructions>",
    "<system-reminder>", "# instructions", "<plan_mode>", "<user_info>",
)


def _is_boilerplate(text):
    stripped = (text or "").lstrip()
    low = stripped.lower()
    return any(low.startswith(p) for p in _BOILERPLATE_PREFIXES)


def _flatten_content(content):
    """Collapse the many content shapes (str | list of blocks) into text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "content", "output", "message", "summary_text"):
            if key in content and isinstance(content[key], str):
                return content[key]
        return json.dumps(content, default=str)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                for key in ("text", "reasoning_text", "output_text", "content", "summary_text"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
        return "\n".join(p for p in parts if p)
    return str(content)


def _maybe_json(text):
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# harvest
# --------------------------------------------------------------------------


def _relevant(session, config):
    """Decide whether a session belongs to this project (and how strongly)."""
    cwd = session.cwd or ""
    root = config.project_root
    if cwd == root or cwd.startswith(root + "/"):
        return "cwd"
    if config.strict_cwd:
        return "none" if cwd else "unknown"
    if cwd:
        return "mention" if config.project_name in cwd else "none"
    return "unknown"


def harvest(config, stats=None):
    """Discover + parse every transcript touching this project."""
    stats = stats or ReadStats()
    sessions = []
    skipped = []
    for adapter in ADAPTERS:
        try:
            discovered = list(adapter.discover(config, stats))
        except OSError as exc:  # tool not installed / permissions
            stats.note_unreadable(adapter.tool, exc)
            continue
        for session in discovered:
            session.match = _relevant(session, config)
            if session.match == "none":
                skipped.append((session, "different project (%s)" % (session.cwd or "?")))
                continue
            mtime = newest_mtime(session.paths)
            if mtime and datetime.fromtimestamp(mtime, timezone.utc) < config.since:
                skipped.append((session, "older than window"))
                continue
            # Consume defensively: one weird record must not cost us the
            # events already collected from this transcript.
            events = []
            stream = adapter.parse(session, config, stats)
            while True:
                try:
                    events.append(next(stream))
                except StopIteration:
                    break
                except (OSError, ValueError, RecursionError, TypeError, KeyError, AttributeError) as exc:
                    stats.note_unreadable(session.paths[0], exc)
                    break
            # cwd may only become known after parsing.
            if session.match == "unknown":
                session.match = _relevant(session, config)
                if session.match == "unknown":
                    blob = " ".join(e.text[:400] for e in events[:60])
                    if config.project_root in blob or ("/%s/" % config.project_name) in blob:
                        session.match = "mention"
                    else:
                        session.match = "none"
                if session.match == "none":
                    skipped.append((session, "no mention of %s" % config.project_name))
                    continue
            events = [e for e in events if e.timestamp is None or e.timestamp >= config.since]
            if not events:
                skipped.append((session, "no events in window"))
                continue
            events.sort(key=lambda e: (e.timestamp or config.since))
            session.events = events
            sessions.append(session)
    sessions.sort(key=lambda s: (s.tool, s.start or config.since))
    return HarvestResult(config, sessions, stats, skipped)


# --------------------------------------------------------------------------
# collisions + timeline
# --------------------------------------------------------------------------


class Collision(object):
    def __init__(self, path, writers):
        self.path = path
        self.writers = writers  # list of (agent_key, first_dt, last_dt, count)

    @property
    def tools(self):
        return sorted({w[0].split(":")[0] for w in self.writers})

    @property
    def span_minutes(self):
        stamps = [w[1] for w in self.writers if w[1]] + [w[2] for w in self.writers if w[2]]
        if len(stamps) < 2:
            return None
        return (max(stamps) - min(stamps)).total_seconds() / 60.0

    @property
    def severity(self):
        span = self.span_minutes
        if span is None:
            return "unknown"
        if len(self.tools) > 1 and span <= 30:
            return "HIGH"
        if len(self.tools) > 1:
            return "MEDIUM"
        return "LOW"

    def to_dict(self):
        return {
            "path": self.path,
            "severity": self.severity,
            "tools": self.tools,
            "writers": [
                {"agent": a, "first": iso(f), "last": iso(l), "writes": c}
                for a, f, l, c in self.writers
            ],
            "span_minutes": self.span_minutes,
        }


def find_collisions(result):
    """Files written by 2+ distinct agents inside the window."""
    per_file = defaultdict(dict)
    for session in result.sessions:
        agent = "%s:%s" % (session.tool, session.short)
        for event in session.events:
            for path in event.files_written:
                bucket = per_file[path].setdefault(agent, [None, None, 0])
                if event.timestamp:
                    bucket[0] = event.timestamp if bucket[0] is None else min(bucket[0], event.timestamp)
                    bucket[1] = event.timestamp if bucket[1] is None else max(bucket[1], event.timestamp)
                bucket[2] += 1
    collisions = []
    for path, writers in per_file.items():
        if len(writers) < 2:
            continue
        rows = sorted(
            ((agent, v[0], v[1], v[2]) for agent, v in writers.items()),
            key=lambda r: (r[1] or datetime.max.replace(tzinfo=timezone.utc)),
        )
        collisions.append(Collision(path, rows))
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "unknown": 3}
    collisions.sort(key=lambda c: (order[c.severity], -len(c.writers), c.path))
    return collisions


def build_timeline(result, limit=80):
    """(when, agent, verb, files) rows -- who touched what, when."""
    rows = []
    for session in result.sessions:
        agent = "%s:%s" % (session.tool, session.short)
        for event in session.events:
            if not event.files_touched:
                continue
            verb = "WRITE" if event.files_written else "read"
            rows.append((event.timestamp, agent, verb, sorted(set(event.files_touched))[:4],
                         event.tool_name or event.kind))
    rows.sort(key=lambda r: (r[0] or datetime.min.replace(tzinfo=timezone.utc)))
    # Collapse consecutive identical (agent, verb, files) rows.
    collapsed = []
    for row in rows:
        if collapsed and collapsed[-1][1:4] == row[1:4]:
            continue
        collapsed.append(row)
    writes = [r for r in collapsed if r[2] == "WRITE"]
    if len(collapsed) > limit:
        keep = writes[-limit:] if len(writes) >= limit else writes + [
            r for r in collapsed if r[2] != "WRITE"][-(limit - len(writes)):]
        keep.sort(key=lambda r: (r[0] or datetime.min.replace(tzinfo=timezone.utc)))
        return keep, len(collapsed) - len(keep)
    return collapsed, 0


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

TOOL_LABEL = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "cline": "Cline",
    "grok": "Grok",
}


def render_digest(result, cap=TEXT_CAP):
    cfg = result.config
    out = []
    add = out.append
    grouped = result.by_tool()
    collisions = find_collisions(result)

    add("# FLEET CONTEXT — %s" % cfg.project_name)
    add("")
    add("Generated %s (local) by `fleet/harvest.py digest`." % local(datetime.now(timezone.utc)))
    add("Window: since **%s** (%s local). Project root: `%s`." % (
        iso(cfg.since), local(cfg.since), cfg.project_root))
    add("")
    add("Paste this into a new agent's context to catch it up on the whole fleet.")
    add("")

    # ---- summary table
    add("## 1. Fleet at a glance")
    add("")
    add("| tool | sessions | events | prompts | files touched | files written | errors |")
    add("|---|---|---|---|---|---|---|")
    for tool in sorted(grouped):
        sessions = grouped[tool]
        events = [e for s in sessions for e in s.events]
        touched = {f for e in events for f in e.files_touched}
        written = {f for e in events for f in e.files_written}
        add("| %s | %d | %d | %d | %d | %d | %d |" % (
            TOOL_LABEL.get(tool, tool), len(sessions), len(events),
            sum(1 for e in events if e.kind == "user_prompt"),
            len(touched), len(written),
            sum(1 for e in events if e.kind == "error"),
        ))
    if not grouped:
        add("| _(no transcripts found in this window)_ | 0 | 0 | 0 | 0 | 0 | 0 |")
    add("")
    missing = [a.tool for a in ADAPTERS if a.tool not in grouped]
    if missing:
        add("_No in-window activity for: %s (tool not installed, or idle)._" %
            ", ".join(TOOL_LABEL.get(t, t) for t in missing))
        add("")

    # ---- collisions first: highest-value output
    add("## 2. COLLISION REPORT — files edited by 2+ agents")
    add("")
    if not collisions:
        add("No file was written by more than one agent in this window. ✅")
    else:
        add("%d file(s) were written by multiple agents. Reconcile before editing:" % len(collisions))
        add("")
        add("| severity | file | agents | window |")
        add("|---|---|---|---|")
        for col in collisions:
            span = col.span_minutes
            span_txt = "%.0f min" % span if span is not None else "unknown"
            add("| **%s** | `%s` | %s | %s |" % (
                col.severity, col.path,
                ", ".join("%s (%d)" % (a, c) for a, _, _, c in col.writers), span_txt))
        add("")
        for col in collisions:
            add("- `%s`" % col.path)
            for agent, first, last, count in col.writers:
                add("  - %s — %d write(s), %s → %s" % (
                    agent, count, local(first) or "?", local(last) or "?"))
    add("")

    # ---- per tool / per session
    add("## 3. What each agent was told, and what it did")
    for tool in sorted(grouped):
        add("")
        add("### %s" % TOOL_LABEL.get(tool, tool))
        for session in grouped[tool]:
            add("")
            add("#### `%s` %s" % (session.short, ("— " + session.label) if session.label else ""))
            add("")
            add("- window: %s → %s | cwd: `%s` | match: %s | events: %d" % (
                local(session.start) or "?", local(session.end) or "?",
                session.cwd or "?", session.match, len(session.events)))
            prompts = session.by_kind("user_prompt")
            if prompts:
                add("- **assignments (verbatim user prompts):**")
                for event in prompts[:10]:
                    add("  - _%s_ — %s" % (local(event.timestamp) or "?",
                                           _md_escape(clip(event.text, cap))))
                if len(prompts) > 10:
                    add("  - _(+%d more prompts)_" % (len(prompts) - 10))
            summaries = session.by_kind("summary") or session.by_kind("assistant_message")[-2:]
            if summaries:
                add("- **final report / last words:**")
                for event in summaries[-2:]:
                    add("  - %s" % _md_escape(clip(event.text, cap)))
            counts = session.file_counts()
            if counts:
                written = Counter()
                for event in session.events:
                    for path in event.files_written:
                        written[path] += 1
                add("- **files touched (by frequency):** %s" % ", ".join(
                    "`%s`%s×%d" % (path, "*" if path in written else "", n)
                    for path, n in counts.most_common(12)))
                if written:
                    add("  - `*` = written/edited by this session")
            errors = session.by_kind("error")
            if errors:
                add("- **errors / failures (%d):**" % len(errors))
                for event in errors[:5]:
                    add("  - _%s_ %s" % (local(event.timestamp) or "?",
                                         _md_escape(one_line(event.text, 220))))
                if len(errors) > 5:
                    add("  - _(+%d more)_" % (len(errors) - 5))
    if not grouped:
        add("")
        add("_Nothing to report: no sessions matched this project inside the window._")
    add("")

    # ---- timeline
    add("## 4. Unified timeline — who touched what, when")
    add("")
    rows, dropped = build_timeline(result)
    if not rows:
        add("_No file activity recorded in this window._")
    else:
        add("| when (local) | agent | action | files |")
        add("|---|---|---|---|")
        for when, agent, verb, files, tool_name in rows:
            add("| %s | %s | %s (%s) | %s |" % (
                local(when) or "?", agent, verb, one_line(tool_name, 24),
                ", ".join("`%s`" % f for f in files)))
        if dropped:
            add("")
            add("_(%d earlier read-only rows omitted for brevity.)_" % dropped)
    add("")

    # ---- hot files
    add("## 5. Hot files (all agents, ranked)")
    add("")
    touched = Counter()
    writers = defaultdict(set)
    for session in result.sessions:
        agent = "%s:%s" % (session.tool, session.short)
        for event in session.events:
            for path in event.files_touched:
                touched[path] += 1
            for path in event.files_written:
                writers[path].add(agent)
    if not touched:
        add("_none_")
    else:
        for path, count in touched.most_common(25):
            owners = ", ".join(sorted(writers.get(path, ()))) or "(reads only)"
            add("- `%s` — %d mention(s); writers: %s" % (path, count, owners))
    add("")

    # ---- parse health
    stats = result.stats
    add("## 6. Harvest health")
    add("")
    add("- transcripts read: %d | lines parsed: %d | malformed lines skipped: %d" % (
        stats.files_read, stats.lines_read, stats.bad_lines))
    add("- sessions discovered but excluded: %d (%s)" % (
        len(result.skipped),
        ", ".join(sorted({reason.split("(")[0].strip() for _, reason in result.skipped})) or "none"))
    if stats.unreadable:
        add("- unreadable sources:")
        for path, reason in stats.unreadable[:8]:
            add("  - `%s` — %s" % (path, reason))
    add("")
    add("_Secrets matching password/token/api-key patterns are redacted as `%s`._" % REDACTED)
    add("")
    return "\n".join(out)


def _md_escape(text):
    return str(text).replace("|", "\\|").replace("\n", " ⏎ ")


# --------------------------------------------------------------------------
# briefing
# --------------------------------------------------------------------------


def _section(markdown, heading_prefix):
    """Return the body of the first '## <heading_prefix>...' section."""
    lines = (markdown or "").splitlines()
    out = []
    capturing = False
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            capturing = line[3:].strip().lower().startswith(heading_prefix.lower())
            continue
        if capturing:
            out.append(line)
    return "\n".join(out).strip("\n")


def _read_text(path):
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def render_brief(result, role, cap=TEXT_CAP):
    cfg = result.config
    agents_md = _read_text(os.path.join(cfg.project_root, "AGENTS.md"))
    product_md = _read_text(os.path.join(cfg.project_root, "PRODUCT.md"))
    collisions = find_collisions(result)

    out = []
    add = out.append
    add("# Onboarding brief — role: **%s**" % role)
    add("")
    add("You are joining a live multi-agent fleet on `%s`. Other agents are editing" % cfg.project_root)
    add("this repo right now. Read this whole brief before touching a file.")
    add("")

    add("## Product vision (PRODUCT.md)")
    add("")
    positioning = _section(product_md, "Positioning")
    roadmap = _section(product_md, "Feature roadmap")
    principles = _section(product_md, "Non-negotiable")
    if positioning:
        add(clip(positioning, 700))
        add("")
    if roadmap:
        add("**Roadmap (ranked):**")
        add("")
        add(clip(roadmap, 900))
        add("")
    if principles:
        add("**Non-negotiables:**")
        add("")
        add(clip(principles, 600))
        add("")
    if not (positioning or roadmap or principles):
        add("_PRODUCT.md not found or empty._")
        add("")

    add("## API contract (AGENTS.md — do not break)")
    add("")
    contract = _section(agents_md, "API contract")
    add(contract if contract else "_AGENTS.md has no API contract section._")
    add("")

    add("## Who owns what (fleet roles)")
    add("")
    roles = _section(agents_md, "Fleet roles")
    add(roles if roles else "_No fleet roles section found._")
    add("")

    add("## Live activity in the last window (%s → now)" % iso(cfg.since))
    add("")
    if not result.sessions:
        add("_No agent activity recorded in this window._")
    else:
        for session in result.sessions:
            prompts = session.by_kind("user_prompt")
            add("- **%s `%s`** — %s | last active %s" % (
                TOOL_LABEL.get(session.tool, session.tool), session.short,
                session.label or "session", local(session.end) or "?"))
            if prompts:
                add("  - assignment: %s" % _md_escape(one_line(prompts[0].text, 240)))
            counts = session.file_counts()
            if counts:
                add("  - files: %s" % ", ".join("`%s`" % f for f, _ in counts.most_common(6)))
    add("")

    add("## Recent decisions & findings")
    add("")
    decisions = []
    for session in result.sessions:
        for event in (session.by_kind("summary") or session.by_kind("assistant_message")[-1:]):
            decisions.append((event.timestamp, session.tool, session.short, event.text))
    decisions.sort(key=lambda d: (d[0] or cfg.since), reverse=True)
    if not decisions:
        add("_none captured_")
    for stamp, tool, sid, text in decisions[:8]:
        add("- **%s `%s`** (%s): %s" % (TOOL_LABEL.get(tool, tool), sid, local(stamp) or "?",
                                        _md_escape(clip(text, cap))))
    add("")

    add("## Open items (AGENTS.md task queue)")
    add("")
    open_items = [line.strip() for line in agents_md.splitlines()
                  if line.strip().startswith("- [ ]")]
    if open_items:
        for item in open_items:
            add(item)
    else:
        add("_no unchecked items_")
    add("")

    add("## YOUR FILE LANE — %s" % role)
    add("")
    lane = _role_lane(agents_md, role)
    if lane:
        add("From AGENTS.md:")
        add("")
        add(lane)
        add("")
    else:
        add("AGENTS.md has no explicit lane for `%s`. Ask the owner to add one before" % role)
        add("writing to any shared file, and default to creating NEW files only.")
        add("")
    add("**Hard rules (enforced by the fleet, not optional):**")
    add("")
    add("1. Announce your lane in AGENTS.md before your first write; never edit another")
    add("   agent's lane files.")
    add("2. Files another agent wrote in this window — treat as HOT, coordinate first:")
    hot = Counter()
    for session in result.sessions:
        for event in session.events:
            for path in event.files_written:
                hot[path] += 1
    if hot:
        for path, count in hot.most_common(15):
            owners = sorted({"%s:%s" % (s.tool, s.short) for s in result.sessions
                             for e in s.events if path in e.files_written})
            add("   - `%s` — %d write(s) by %s" % (path, count, ", ".join(owners)))
    else:
        add("   - _(none written in this window)_")
    if collisions:
        add("3. These files ALREADY collided (2+ agents wrote them). Do not touch without")
        add("   an explicit go-ahead: %s" % ", ".join("`%s`" % c.path for c in collisions[:10]))
    else:
        add("3. No collisions detected in this window — keep it that way.")
    add("4. Run `.venv/bin/python -m pytest tests -q` before and after your change;")
    add("   never commit or push unless the owner asks.")
    add("5. Re-run `fleet/harvest.py digest` before a long edit session to see who moved.")
    add("")
    return "\n".join(out)


def _role_lane(agents_md, role):
    """Pull the AGENTS.md bullet describing *role*'s file lane."""
    if not agents_md or not role:
        return ""
    needle = role.strip().lower()
    words = [w for w in re.split(r"[^a-z0-9]+", needle) if len(w) > 2]
    lines = agents_md.splitlines()
    best = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("- **"):
            continue
        header = stripped.lower()
        if needle in header or (words and all(w in header for w in words)) or \
                (words and words[0] in header):
            block = [line.rstrip()]
            for follow in lines[index + 1:]:
                if follow.strip().startswith("- **") or follow.startswith("## "):
                    break
                if not follow.strip():
                    if block and block[-1].strip() == "":
                        break
                    continue
                block.append(follow.rstrip())
            candidate = "\n".join(block)
            if not best or len(candidate) > len(best[0]):
                best = [candidate]
    return best[0] if best else ""


# --------------------------------------------------------------------------
# output safety
# --------------------------------------------------------------------------


class HarvestError(Exception):
    pass


def safe_output_path(config, out):
    """Resolve *out* and refuse anything outside <project>/fleet/.

    The harvester is read-only everywhere else on the machine; this is the
    single choke point every write goes through.
    """
    fleet_dir = Path(config.fleet_dir).resolve()
    candidate = Path(out)
    if not candidate.is_absolute():
        candidate = Path(config.project_root) / candidate
    candidate = candidate.resolve()
    if candidate != fleet_dir and not is_within(candidate, fleet_dir):
        raise HarvestError(
            "refusing to write outside %s (got %s)" % (fleet_dir, candidate))
    return candidate


def write_output(config, out, text):
    path = safe_output_path(config, out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _config_from_args(args):
    return Config(
        project_root=args.project,
        home=getattr(args, "home", None),
        since=getattr(args, "since", "24h"),
        strict_cwd=getattr(args, "strict_cwd", False),
        include_subagents=not getattr(args, "no_subagents", False),
    )


def cmd_digest(args):
    config = _config_from_args(args)
    result = harvest(config)
    text = render_digest(result, cap=args.cap)
    if args.stdout:
        sys.stdout.write(text)
    else:
        path = write_output(config, args.out, text)
        print("wrote %s (%d sessions, %d events, %d collisions)" % (
            path, len(result.sessions), len(result.events), len(find_collisions(result))))
    if args.json:
        json_path = write_output(config, args.json, json.dumps(result.to_dict(), indent=2))
        print("wrote %s" % json_path)
    return 0


def cmd_brief(args):
    config = _config_from_args(args)
    result = harvest(config)
    text = render_brief(result, args.role, cap=args.cap)
    if args.out:
        path = write_output(config, args.out, text)
        print("wrote %s" % path)
    else:
        sys.stdout.write(text)
    return 0


def cmd_sessions(args):
    config = _config_from_args(args)
    result = harvest(config)
    for session in result.sessions:
        print("%-12s %-22s %-19s %-19s events=%-5d files=%d  %s" % (
            session.tool, session.short, local(session.start) or "?",
            local(session.end) or "?", len(session.events),
            len(session.file_counts()), one_line(session.label, 48)))
    if not result.sessions:
        print("(no sessions in window)")
    return 0


def cmd_watch(args):
    config = _config_from_args(args)
    seen_sessions = {}
    seen_collisions = set()
    first = True
    print("watching %s every %ds — Ctrl-C to stop" % (config.project_root, args.interval))
    try:
        while True:
            config = _config_from_args(args)  # rolling window
            result = harvest(config)
            text = render_digest(result, cap=args.cap)
            path = write_output(config, args.out, text)
            changes = []
            for session in result.sessions:
                previous = seen_sessions.get(session.key)
                if previous is None:
                    changes.append("NEW SESSION  %s %s (%s) — %d events" % (
                        session.tool, session.short, one_line(session.label, 40),
                        len(session.events)))
                elif len(session.events) != previous:
                    changes.append("UPDATED      %s %s — %+d events" % (
                        session.tool, session.short, len(session.events) - previous))
                seen_sessions[session.key] = len(session.events)
            for collision in find_collisions(result):
                key = (collision.path, tuple(w[0] for w in collision.writers))
                if key not in seen_collisions:
                    seen_collisions.add(key)
                    changes.append("COLLISION    %s [%s] %s" % (
                        collision.severity, collision.path,
                        ", ".join(w[0] for w in collision.writers)))
            stamp = datetime.now().strftime("%H:%M:%S")
            if first:
                print("[%s] baseline: %d sessions, %d collisions -> %s" % (
                    stamp, len(result.sessions), len(seen_collisions), path))
                for line in changes:
                    print("    %s" % line)
                first = False
            elif changes:
                print("[%s] %d change(s) -> %s" % (stamp, len(changes), path))
                for line in changes:
                    print("    %s" % line)
            else:
                sys.stdout.write("[%s] no change\r" % stamp)
                sys.stdout.flush()
            slept = 0.0
            while slept < args.interval:
                time.sleep(min(0.5, args.interval - slept))
                slept += 0.5
    except KeyboardInterrupt:
        print("\nstopped (watched %d session(s), %d collision(s))" % (
            len(seen_sessions), len(seen_collisions)))
        return 0


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=str(Path(__file__).resolve().parent.parent),
                        help="project root (default: parent of fleet/)")
    common.add_argument("--home", default=None,
                        help="override HOME when locating transcripts (testing)")
    common.add_argument("--since", default="24h",
                        help="time window: 24h, 90m, 7d, all, or an ISO timestamp")
    common.add_argument("--strict-cwd", action="store_true",
                        help="only include sessions whose cwd is exactly this project")
    common.add_argument("--no-subagents", action="store_true",
                        help="skip Claude Code subagent transcripts")
    common.add_argument("--cap", type=int, default=TEXT_CAP,
                        help="truncate quoted text to N chars (default %d)" % TEXT_CAP)

    parser = argparse.ArgumentParser(
        prog="harvest.py",
        parents=[common],
        description="Consolidate every AI agent's transcript for this project.",
    )
    sub = parser.add_subparsers(dest="command")

    digest = sub.add_parser("digest", parents=[common], help="write fleet/FLEET_CONTEXT.md")
    digest.add_argument("--out", default="fleet/FLEET_CONTEXT.md")
    digest.add_argument("--json", default=None, help="also write a JSON dump (inside fleet/)")
    digest.add_argument("--stdout", action="store_true", help="print instead of writing")
    digest.set_defaults(func=cmd_digest)

    brief = sub.add_parser("brief", parents=[common],
                           help="print an onboarding brief for a new agent")
    brief.add_argument("--for", dest="role", required=True, help="role name, e.g. 'Cline'")
    brief.add_argument("--out", default=None, help="write to a file inside fleet/")
    brief.set_defaults(func=cmd_brief)

    watch = sub.add_parser("watch", parents=[common],
                           help="re-digest on an interval, print only changes")
    watch.add_argument("--interval", type=int, default=60)
    watch.add_argument("--out", default="fleet/FLEET_CONTEXT.md")
    watch.set_defaults(func=cmd_watch)

    sessions = sub.add_parser("sessions", parents=[common], help="list discovered sessions")
    sessions.set_defaults(func=cmd_sessions)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except HarvestError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 0


if __name__ == "__main__":
    sys.exit(main())
