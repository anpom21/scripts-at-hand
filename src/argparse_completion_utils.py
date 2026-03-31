import os
import subprocess
import json
from pathlib import Path
from typing import Dict, List
import time
from tqdm import tqdm
def get_script_options(script_path: str, python3_path: str = None) -> List[str]:
    """
    Run the script with --help and parse the output for options.
    Returns a list of options (e.g., ['--csv', '-h']).
    """
    if python3_path is None:
        python3_path = 'python3'
    try:
        start_time = time.time()
        result = subprocess.run([python3_path, script_path, '--help'], capture_output=True, text=True, timeout=10)
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

def build_script_options_map(entries: List[Dict]) -> Dict[str, List[str]]:
    """
    For each script entry, extract its options and return a dict mapping script name to options.
    """
    options_map = {}
    for e in tqdm(entries):
        name = e.get('name')
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
            options_map[name] = opts
    return options_map
