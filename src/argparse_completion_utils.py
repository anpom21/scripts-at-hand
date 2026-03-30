import subprocess
import json
from pathlib import Path
from typing import Dict, List

def get_script_options(script_path: str, python3_path: str = None) -> List[str]:
    """
    Run the script with --help and parse the output for options.
    Returns a list of options (e.g., ['--csv', '-h']).
    """
    if python3_path is None:
        python3_path = 'python3'
    try:
        result = subprocess.run([python3_path, script_path, '--help'], capture_output=True, text=True, timeout=5)
        help_text = result.stdout + '\n' + result.stderr
        import re
        option_pattern = re.compile(r"(?<!\w)(--[\w-]+|-[\w])(?:[ =][^\s]*)?")
        options = set()
        for line in help_text.splitlines():
            for match in option_pattern.finditer(line):
                options.add(match.group(1))
        return sorted(options)
    except Exception:
        return []

def build_script_options_map(entries: List[Dict]) -> Dict[str, List[str]]:
    """
    For each script entry, extract its options and return a dict mapping script name to options.
    """
    options_map = {}
    for e in entries:
        name = e.get('name')
        path = e.get('execution_path', '.')
        python3_path = e.get('python3', 'python3')
        script_file = Path(path) / name
        if script_file.exists():
            opts = get_script_options(str(script_file), python3_path)
            options_map[name] = opts
    return options_map
