#!/usr/bin/env python3
"""
Extract argparse options from a Python script by parsing its --help output.
Usage:
    python extract_argparse_options.py /path/to/script.py
Prints a JSON list of all options (e.g. ["--csv", "-h", ...])
"""
import sys
import subprocess
import re
import json
from pathlib import Path

def extract_options_from_help(help_text):
    # Regex to match options like --csv, -h, etc.
    option_pattern = re.compile(r"(?<!\w)(--[\w-]+|-[\w])(?:[ =][^\s]*)?")
    options = set()
    for line in help_text.splitlines():
        # Only look at lines that look like options
        for match in option_pattern.finditer(line):
            options.add(match.group(1))
    return sorted(options)

def main():
    if len(sys.argv) != 2:
        print("Usage: python extract_argparse_options.py /path/to/script.py", file=sys.stderr)
        sys.exit(1)
    script_path = sys.argv[1]
    if not Path(script_path).exists():
        print(f"Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)
    try:
        result = subprocess.run([sys.executable, script_path, "--help"], capture_output=True, text=True, timeout=5)
        help_text = result.stdout + "\n" + result.stderr
        options = extract_options_from_help(help_text)
        print(json.dumps(options))
    except Exception as e:
        print(f"Error running script: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
