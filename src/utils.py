"""Shared helpers for ARIS CLI.

This module centralizes:
- YAML config load/save
- script discovery & normalization
- description extraction
- coloring utilities

All functions include headers describing behavior, args, and returns.
"""

from __future__ import annotations

import os
import re
import sys
import stat
import yaml
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CONFIG_BASENAME = "config.yaml"
SCRIPTS_DIRNAME = "scripts"
LOGS_DIRNAME = "logs"


@dataclass
class ScriptEntry:
    """A normalized script entry.

    Attributes:
        name: Script name as referenced by `aris <name>`.
        python3: Absolute path to python3 to execute for .py scripts, or 'NAN' for shell scripts.
        source: Where the script comes from: 'local' or repository name.
        relpath: Script path relative to its repository root (or scripts/ for local).
        abspath: Absolute filesystem path to script.
        description: Best-effort extracted description.
        execution_path: Directory to execute the script from.
        hash_id: SHA256 hash of script content for collision detection.
    """

    name: str
    python3: str
    source: str
    relpath: str
    abspath: str
    description: str = ""
    execution_path: str = ""
    hash_id: str = ""


# ----------------------------- YAML CONFIG ---------------------------------

def config_path(root: Path) -> Path:
    """Return the absolute path to the config.yaml.

    Args:
        root: Repository root.

    Returns:
        Path to config.yaml.
    """

    return root / CONFIG_BASENAME


def load_config(root: Path) -> Dict[str, Any]:
    """Load config.yaml as a dictionary.

    Args:
        root: Repository root.

    Returns:
        Parsed YAML dict with keys 'repositories' and 'scripts'.
    """

    p = config_path(root)
    if not p.exists():
        return {"repositories": [], "scripts": []}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("repositories", [])
    data.setdefault("scripts", [])
    return data


def save_config(root: Path, data: Dict[str, Any]) -> None:
    """Persist config.yaml.

    Args:
        root: Repository root.
        data: YAML structure.

    Returns:
        None
    """

    p = config_path(root)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


# ----------------------------- DISCOVERY -----------------------------------

def _default_system_python3() -> str:
    """Resolve default python3 path (non-venv).

    Uses `which python3` semantics.

    Args:
        None

    Returns:
        Absolute path to python3 (or 'python3' if not found).
    """

    import shutil

    path = shutil.which("python3")
    return path or "python3"


def _is_python_script(path: Path) -> bool:
    """Check if a path is a Python script.

    Args:
        path: File path.

    Returns:
        True if endswith .py
    """

    return path.suffix.lower() == ".py"


def _is_shell_script(path: Path) -> bool:
    """Check if a path is a shell script.

    Args:
        path: File path.

    Returns:
        True if endswith .sh
    """

    return path.suffix.lower() == ".sh"


def _safe_read_head(path: Path, max_bytes: int = 8192) -> str:
    """Read up to max_bytes from the beginning of a file.

    Args:
        path: File to read.
        max_bytes: Maximum bytes.

    Returns:
        Decoded text (best effort).
    """

    try:
        with path.open("rb") as f:
            blob = f.read(max_bytes)
        return blob.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_description(path: Path) -> str:
    """Extract a short description from a script.

    Priority:
      1) Module docstring for Python
      2) Leading comment block for shell
      3) First non-empty line

    Args:
        path: Script file.

    Returns:
        Short, single-line description.
    """

    head = _safe_read_head(path)
    if not head:
        return ""

    if _is_python_script(path):
        # Attempt docstring parse using a regex on first triple quote block.
        m = re.search(r"\A\s*(?:#.*\n)*\s*([\"\']{3})(.*?)(\1)", head, re.S)
        if m:
            doc = m.group(2).strip().splitlines()
            if doc:
                return doc[0].strip()

    # Shell or fallback: collect leading comment lines
    lines = head.splitlines()
    comment_lines: List[str] = []
    for ln in lines[:40]:
        s = ln.strip()
        if not s:
            if comment_lines:
                break
            continue
        if s.startswith("#!"):
            continue
        if s.startswith("#"):
            comment_lines.append(s.lstrip("#").strip())
        else:
            break

    if comment_lines:
        return " ".join(comment_lines)[:160]

    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#!"):
            return s[:160]

    return ""


def normalize_script_name(relpath: str) -> str:
    """Normalize a relative path into a CLI-friendly script name.

    Now preserves original filename unless there's a collision.
    Examples:
        organize_data/2_rename_files.py -> 2_rename_files.py (if no collision)
        synth/synthesize.py -> synthesize.py (if no collision)

    Args:
        relpath: Script relative path.

    Returns:
        Base filename (or full normalized path if needed for collision resolution).
    """

    # Return just the filename (basename)
    return Path(relpath).name


def resolve_name_collisions(entries: List[Tuple[str, Path, str, str, str, str]]) -> List[Tuple[str, Path, str, str, str, str]]:
    """Resolve naming collisions by progressively adding parent directory names.

    Args:
        entries: List of tuples (proposed_name, path, python3, source, relpath, description)

    Returns:
        List of tuples with resolved unique names.
    """

    from collections import defaultdict

    # Track which names have collisions
    name_counts: Dict[str, List[int]] = defaultdict(list)
    for idx, (name, _, _, _, _, _) in enumerate(entries):
        name_counts[name].append(idx)

    result = list(entries)

    # For each collision, add parent directories until unique
    for name, indices in name_counts.items():
        if len(indices) <= 1:
            continue

        # We have a collision, need to resolve
        for idx in indices:
            _, path, python3, source, relpath, description = result[idx]
            parts = Path(relpath).parts

            # Try adding parent directories progressively
            unique_name = name
            for depth in range(1, len(parts)):
                # Build name from last 'depth+1' parts
                unique_name = "_".join(parts[-(depth + 1):])
                # Check if this resolves the collision
                is_unique = True
                for check_idx, (check_name, _, _, _, _, _) in enumerate(result):
                    if check_idx != idx and check_name == unique_name:
                        is_unique = False
                        break
                if is_unique:
                    break

            result[idx] = (unique_name, path, python3, source, relpath, description)

    return result


def list_local_scripts(root: Path) -> List[Path]:
    """List scripts in scripts/ folder.

    Args:
        root: Repository root.

    Returns:
        List of file paths.
    """

    scripts_dir = root / SCRIPTS_DIRNAME
    if not scripts_dir.exists():
        return []

    out: List[Path] = []
    for p in scripts_dir.rglob("*"):
        if p.is_file() and (p.suffix.lower() in {".py", ".sh"}):
            out.append(p)
    return sorted(out)


def list_repo_scripts(repo_path: Path, scripts: List[str]) -> List[Path]:
    """List scripts in an external repository as configured.

    Args:
        repo_path: Repository root.
        scripts: List of script relative paths (strings).

    Returns:
        List of absolute script paths that exist.
    """

    out: List[Path] = []
    for rel in scripts:
        p = repo_path / rel
        if p.exists() and p.is_file():
            out.append(p)
    return out


def ensure_logs_structure(root: Path, entries: List[ScriptEntry]) -> None:
    """Ensure logs/ and per-script folders exist.

    Args:
        root: ARIS CLI repository root.
        entries: Script entries.

    Returns:
        None
    """

    logs_root = root / LOGS_DIRNAME
    logs_root.mkdir(parents=True, exist_ok=True)
    for e in entries:
        # Use script name as folder.
        (logs_root / e.name).mkdir(parents=True, exist_ok=True)


def set_executable(path: Path) -> None:
    """Add executable bit to a file.

    Args:
        path: File path.

    Returns:
        None
    """

    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass


def compute_script_hash(path: Path) -> str:
    """Compute SHA256 hash of script content.

    Args:
        path: Script file path.

    Returns:
        Hex digest of file content hash.
    """

    try:
        with path.open("rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


# ----------------------------- INDEX BUILD ---------------------------------

def build_script_index(root: Path, cfg: Dict[str, Any]) -> List[ScriptEntry]:
    """Build a unified list of scripts from local scripts/ plus configured repositories.

    Args:
        root: ARIS CLI repository root.
        cfg: Loaded config.

    Returns:
        List of ScriptEntry.
    """

    # Collect all scripts first with proposed names
    proposed_entries = []

    # 1) Local scripts
    default_py = _default_system_python3()
    for p in list_local_scripts(root):
        rel = str(p.relative_to(root / SCRIPTS_DIRNAME))
        name = normalize_script_name(rel)
        python3 = default_py if _is_python_script(p) else "NAN"
        exec_path = str(p.parent)
        proposed_entries.append((name, p, python3, "local", rel, extract_description(p), exec_path))

    # 2) Repository scripts
    for repo in cfg.get("repositories", []) or []:
        rname = repo.get("name", "repo")
        rpath = Path(repo.get("path", ""))
        rpy = repo.get("python3", default_py)
        rexec = repo.get("execution_path", str(rpath))
        rscripts = repo.get("scripts", []) or []
        for p in list_repo_scripts(rpath, rscripts):
            rel = str(p.relative_to(rpath))
            name = normalize_script_name(rel)
            python3 = rpy if _is_python_script(p) else "NAN"
            # execution_path can be overridden per-repository
            exec_path = rexec
            proposed_entries.append((name, p, python3, rname, rel, extract_description(p), exec_path))

    # Resolve name collisions
    resolved = []
    for name, p, python3, source, rel, desc, exec_path in proposed_entries:
        resolved.append((name, p, python3, source, rel, desc, exec_path))

    # Group by name to detect collisions
    from collections import defaultdict
    name_groups: Dict[str, List[int]] = defaultdict(list)
    for idx, (name, _, _, _, _, _, _) in enumerate(resolved):
        name_groups[name].append(idx)

    # Resolve collisions
    for name, indices in name_groups.items():
        if len(indices) > 1:
            # Collision detected - need to make names unique
            for idx in indices:
                _, p, python3, source, relpath, desc, exec_path = resolved[idx]
                parts = Path(relpath).parts
                unique_name = name
                
                # Try adding parent directories until unique
                for depth in range(1, len(parts)):
                    candidate = "_".join(parts[-(depth + 1):])
                    # Check if candidate is unique among all current names
                    is_unique = True
                    for check_idx, (check_name, _, _, _, _, _, _) in enumerate(resolved):
                        if check_idx != idx and check_name == candidate:
                            is_unique = False
                            break
                    if is_unique:
                        unique_name = candidate
                        break
                
                resolved[idx] = (unique_name, p, python3, source, relpath, desc, exec_path)

    # Build ScriptEntry objects with hash detection
    entries: List[ScriptEntry] = []
    hash_map: Dict[str, ScriptEntry] = {}
    
    for name, p, python3, source, relpath, desc, exec_path in resolved:
        hash_id = compute_script_hash(p)
        
        # Check for hash collision (duplicate content)
        if hash_id and hash_id in hash_map:
            existing = hash_map[hash_id]
            print(
                f"WARNING: Script content collision detected!\n"
                f"  Script 1: {existing.name} ({existing.source})\n"
                f"  Script 2: {name} ({source})\n"
                f"  Both scripts have identical content (hash: {hash_id[:16]}...)\n",
                file=sys.stderr,
            )
        
        entry = ScriptEntry(
            name=name,
            python3=python3,
            source=source,
            relpath=str(Path(SCRIPTS_DIRNAME) / relpath) if source == "local" else relpath,
            abspath=str(p),
            description=desc,
            execution_path=exec_path,
            hash_id=hash_id,
        )
        entries.append(entry)
        
        if hash_id:
            hash_map[hash_id] = entry

    return sorted(entries, key=lambda x: x.name.lower())


def update_scripts_section(cfg: Dict[str, Any], entries: List[ScriptEntry]) -> Dict[str, Any]:
    """Update cfg['scripts'] to contain local scripts plus any repo-derived overrides.

    This keeps per-script python3 mappings in a single section.

    Args:
        cfg: Existing config.
        entries: Unified script index.

    Returns:
        Updated config dict.
    """

    scripts_out = []
    for e in entries:
        scripts_out.append({
            "name": e.name,
            "python3": e.python3,
            "execution_path": e.execution_path,
            "hash_id": e.hash_id,
            "source": e.source,
        })
    cfg["scripts"] = scripts_out
    return cfg


def find_entry(entries: List[ScriptEntry], script_name: str) -> Optional[ScriptEntry]:
    """Find a script entry by CLI name.

    Args:
        entries: Script index.
        script_name: Name passed to `aris`.

    Returns:
        ScriptEntry or None.
    """

    script_name = script_name.strip()
    for e in entries:
        if e.name == script_name:
            return e
    return None


# ----------------------------- COLORING ------------------------------------

def red_bold(text: str) -> str:
    """ANSI red + bold wrapper.

    Args:
        text: Input string.

    Returns:
        Colored string.
    """

    return f"\033[1;31m{text}\033[0m"


def bold(text: str) -> str:
    """ANSI bold wrapper.

    Args:
        text: Input string.

    Returns:
        Colored string.
    """

    return f"\033[1m{text}\033[0m"


def highlight_token(haystack: str, token: str) -> str:
    """Highlight occurrences of token in haystack using red bold.

    Args:
        haystack: Text to search.
        token: Search token.

    Returns:
        Modified string with highlights.
    """

    if not token:
        return haystack

    pattern = re.compile(re.escape(token), re.IGNORECASE)

    def _repl(m: re.Match) -> str:
        return red_bold(m.group(0))

    return pattern.sub(_repl, haystack)


def snippet_around(text: str, token: str, radius: int = 40) -> str:
    """Return a snippet around the first occurrence of token.

    Args:
        text: Full text.
        token: Token to find.
        radius: Characters around match.

    Returns:
        Snippet string.
    """

    if not token:
        return text[:2 * radius]
    m = re.search(re.escape(token), text, re.IGNORECASE)
    if not m:
        return text[:2 * radius]
    a = max(0, m.start() - radius)
    b = min(len(text), m.end() + radius)
    prefix = "…" if a > 0 else ""
    suffix = "…" if b < len(text) else ""
    return f"{prefix}{text[a:b]}{suffix}"
