import ast
import os
import subprocess
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import time
from tqdm import tqdm


def _extract_option_strings_from_node(node: ast.AST) -> List[str]:
    """Collect string literals from an AST node used as add_argument args."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Str):
        return [node.s]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: List[str] = []
        for element in node.elts:
            values.extend(_extract_option_strings_from_node(element))
        return values
    return []


def _get_script_options_static(script_path: str) -> List[str]:
    """
    Parse a Python file and extract option flags from argparse add_argument calls.

    Returns a sorted list of flags like ["--source", "--source-dir", "-h"].
    """
    try:
        source = Path(script_path).read_text(encoding="utf-8")
    except Exception:
        return []

    try:
        tree = ast.parse(source, filename=script_path)
    except SyntaxError:
        return []

    options = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            for arg in node.args:
                for value in _extract_option_strings_from_node(arg):
                    if value.startswith("-"):
                        options.add(value)

    return sorted(options)


def get_script_options(script_path: str, python3_path: str = None) -> List[str]:
    """
    Extract options for a script.

    Primary path: statically parse Python files for add_argument flags.
    Fallback path: run script with --help and parse output.

    Returns a list of options (e.g., ['--csv', '-h']).
    """
    if python3_path is None:
        python3_path = 'python3'

    script_file = Path(script_path)

    # Primary fast path: static extraction for Python files.
    if script_file.suffix.lower() == '.py':
        static_options = _get_script_options_static(script_path)
        if static_options:
            return static_options

    # Fallback: execute script help text and regex-parse options.
    try:
        start_time = time.time()
        result = subprocess.run([python3_path, script_path, '--help'], capture_output=True, text=True, timeout=5)
        # print(f"{time.time() - start_time:.2f} seconds")
        help_text = result.stdout + '\n' + result.stderr
        import re
        option_pattern = re.compile(r"(?<!\w)(--[\w-]+|-[\w])(?:[ =][^\s]*)?")
        options = set()
        for line in help_text.splitlines():
            for match in option_pattern.finditer(line):
                options.add(match.group(1))
        return sorted(options)
    except Exception as e:
        print(f"Error occurred while processing {script_path}: {e}")
        return []


def _load_options_cache(cache_path: Path) -> Dict[str, Dict[str, Any]]:
    """Load script options cache from disk."""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    scripts = payload.get("scripts", {})
    if isinstance(scripts, dict):
        return scripts
    return {}


def _save_options_cache(cache_path: Path, scripts_cache: Dict[str, Dict[str, Any]]) -> None:
    """Persist script options cache to disk."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"scripts": scripts_cache}
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not save options cache {cache_path}: {e}")


def build_script_options_map(entries: List[Dict], cache_path: Optional[str | Path] = None) -> Dict[str, List[str]]:
    """
    For each script entry, extract its options and return a dict mapping script name to options.

    If cache_path is provided, options are reused for entries where hash_id did not change.
    """
    options_map = {}
    cache_file = Path(cache_path) if cache_path else None
    cached_scripts = _load_options_cache(cache_file) if cache_file else {}
    updated_cache: Dict[str, Dict[str, Any]] = {}

    for e in tqdm(entries):
        name = e.get('name')
        if not name:
            continue

        hash_id = e.get('hash_id', '')
        cached_entry = cached_scripts.get(name, {}) if cached_scripts else {}

        # Reuse options when hash_id is unchanged.
        if hash_id and cached_entry.get('hash_id') == hash_id:
            cached_options = cached_entry.get('options', [])
            if isinstance(cached_options, list):
                cached_options = [opt for opt in cached_options if isinstance(opt, str)]
                options_map[name] = sorted(set(cached_options))
                updated_cache[name] = {
                    'hash_id': hash_id,
                    'options': options_map[name],
                }
                continue

        path = e.get('execution_path', '.')
        python3_path = e.get('python3', 'python3')
        if e.get('source','local') != 'local':
            # Search for the script name at the execution path, search recursively
            # print(f"Searching for {name} in {path} recursively...")
            script_path = Path(path).rglob(f"*{name}")
            filter = ["lib", "venv", "site-packages", "dist-packages"]
            script_path = [p for p in script_path if not any(f in str(p) for f in filter)]
            if script_path:
                script_file = script_path[0]
            else:
                print(f"Warning: Could not find script {name} in {path} after filtering.")
                continue
            # print(f"Filtered script candidates: {[str(p) for p in script_path]}")

        else:
            script_file = Path(path) / name
        if script_file.suffix == '.sh':
            python3_path = 'bash'
            
        # Check if suffix is .py, if not, skip
        if script_file.exists():
            opts = get_script_options(str(script_file), python3_path)
        else:
            opts = []

        options_map[name] = opts
        updated_cache[name] = {
            'hash_id': hash_id,
            'options': opts,
        }

    if cache_file:
        _save_options_cache(cache_file, updated_cache)

    return options_map
