# ARIS CLI

A lightweight, repo-local CLI that consolidates many production scripts (Python + Bash) behind a single command:

- `aris` lists scripts and shows usage
- `aris <script_name> [args...]` runs a script
- `aris search` opens an interactive real-time search UI
- `aris refresh` updates `config.yaml` and permissions

## Repository Layout

```
.
├── main.sh
├── config.yaml
├── scripts/           # drop your local scripts here
├── logs/              # per-script log folders created automatically
└── src/
    ├── refresh.py
    ├── run.py
    ├── search.py
    ├── completion.py
    └── utils.py
```

## Install / Use

### 1) Clone repository

```bash
git clone https://github.com/yourusername/aris-cli.git
cd aris-cli
```


### 2) Add `aris` as a command

Add an alias to your `~/.bashrc` and source the completion script:

```bash
alias aris='/path/to/aris-cli/main.sh'
source <(aris completion bash)
```

### 2) Add scripts

Put scripts in `scripts/` (supports `.py` and `.sh`). Nested paths are allowed.

**Script naming:**
- Scripts keep their original filenames (e.g., `2_rename_files.py`)
- Only when name collisions occur will parent directory names be prepended
- Example: If two scripts named `run.py` exist, they might become `helper_scripts_run.py` and `other_scripts_run.py`.
If the folder structure is:
```
scripts/
├── helper_scripts/
│   └── run.py
└── other_scripts/
    └── run.py
```

### 3) Configure external repositories (optional)

Edit `config.yaml`:

```yaml
repositories:
- name: Annotation
  path: /home/simon/Annotation
  python3: /home/simon/Annotation/.venv/bin/python3
  execution_path: /home/simon/Annotation  # optional: working directory for scripts
  scripts:
  - segment.py

scripts: []
```

On every run, `aris` refreshes and writes the bottom `scripts:` section with:
- `name`: Script name as invoked via CLI
- `python3`: Path to Python interpreter (or NAN for shell scripts)
- `execution_path`: Working directory where script executes
- `hash_id`: SHA256 hash for duplicate content detection

### 4) Autocomplete

Autocomplete now includes all scripts from both local and configured repositories.

**Usage examples:**
- Type `aris sync_an` and press TAB → completes to `aris sync_and_sort_images.sh`
- Type `aris sy` and press TAB → shows all scripts starting with "sy": `sync_and_sort_images.sh`, `sync_image_files.py`, `synthesize.py`
- After the script name, TAB provides file/directory completion for script arguments

## How execution works

- For Python scripts: `aris <name>` becomes:
  - `<python3_from_config> <absolute_path_to_script> [args...]`
- For Bash scripts: `aris <name>` becomes:
  - `bash <absolute_path_to_script> [args...]`

The script receives all remaining arguments unchanged and executes from its `execution_path` (or parent directory if not set).

## Refresh behavior

`src/refresh.py` runs automatically on every `aris` invocation:

- Discovers local scripts in `scripts/`.
- Merges with configured external repositories.
- Updates `config.yaml` `scripts:` section.
- Ensures `.sh` scripts are executable.
- Ensures `logs/<script_name>/` exists for each script.
- Detects script content collisions using SHA256 hashes.
- **Shows change summary**: When scripts are added or removed, displays:
  - Bold green success message
  - `+ script_name [source]` in green for added scripts
  - `- script_name [source]` in red for removed scripts

## Interactive Search

`aris search` provides a real-time, clean search experience using curses:

- **Real-time updates**: Results appear instantly as you type each character
- **Clean display**: Screen updates in-place without cascading text
- **Numbered results**: Up to 10 results shown, numbered for reference
- **Highlighted matches**: Search term highlighted in red/bold
- **Easy selection**: Press Enter or TAB to select the top match
- **Quick exit**: Press ESC or Ctrl+C to quit
- **Terminal-aware**: Adapts to your terminal size

The search uses Python's curses library for proper terminal handling, providing a smooth, flicker-free experience similar to tools like `fzf`.

## Features

### Smart Script Naming
- Scripts maintain their original filenames
- Collision resolution only when necessary
- Clear error messages for duplicate content

### Hash-based Collision Detection
- Detects when multiple scripts have identical content
- Warns about duplicate functionality
- Helps maintain clean script organization

### Execution Path Control
- Scripts can specify their working directory
- Supports relative path dependencies
- Per-repository and per-script configuration

## Notes / Extensions

- Add richer metadata by using Python module docstrings or leading shell comments.
- Extend completion support to zsh/fish by adding generators in `src/completion.py`.
- Add caching or incremental refresh if scripts folder becomes very large.
