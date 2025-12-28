# ARIS CLI (aris)

A lightweight, repo-local CLI that consolidates many production scripts (Python + Bash) behind a single command:

- `aris` lists scripts and shows usage
- `aris <script_name> [args...]` runs a script
- `aris search` opens an interactive real-time search UI
- `aris refresh` updates `config.yaml` and permissions
- `aris completion bash` prints a bash completion script

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

### 1) Put `aris` on PATH

Option A: symlink the entrypoint:

```bash
sudo ln -s /path/to/aris-cli/main.sh /usr/local/bin/aris
sudo chmod +x /path/to/aris-cli/main.sh
```

Option B: add an alias:

```bash
alias aris='/path/to/aris-cli/main.sh'
```

### 2) Add scripts

Put scripts in `scripts/` (supports `.py` and `.sh`). Nested paths are allowed.

**Script naming:**
- Scripts keep their original filenames (e.g., `2_rename_files.py`)
- Only when name collisions occur will parent directory names be prepended
- Example: If two scripts named `run.py` exist, they might become `scripts_run.py` and `other_scripts_run.py`

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

```bash
source <(aris completion bash)
```

Add the above line to `~/.bashrc`. Autocomplete now includes all scripts from both local and configured repositories.

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

## Interactive Search

`aris search` provides a simple, effective search experience:

- Type your search query and press Enter
- Results appear numbered 1-10 with highlighted matches
- Type a number (e.g., `3`) to select that result
- Or type a new search query to refine your search
- Type `exit`, `quit`, or press Ctrl+C to exit
- Searches in both script names and descriptions
- Selected commands are clearly displayed: `aris <script_name>`

This approach is reliable, works in all terminals, and provides clear selection feedback.

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
