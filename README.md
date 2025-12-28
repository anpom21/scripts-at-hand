# ARIS CLI (aris)

A lightweight, repo-local CLI that consolidates many production scripts (Python + Bash) behind a single command:

- `aris` lists scripts and shows usage
- `aris <script_name> [args...]` runs a script
- `aris search` opens an interactive search UI
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

Script names are normalized for CLI access:

- `scripts/synth/synthesize.py` → `aris synth_synthesize.py`

### 3) Configure external repositories (optional)

Edit `config.yaml`:

```yaml
repositories:
- name: Annotation
  path: /home/simon/Annotation
  python3: /home/simon/Annotation/.venv/bin/python3
  scripts:
  - segment.py

scripts: []
```

On every run, `aris` refreshes and writes the bottom `scripts:` section with resolved `python3` mappings.

### 4) Autocomplete

```bash
source <(aris completion bash)
```

Add the above line to `~/.bashrc`.

## How execution works

- For Python scripts: `aris <name>` becomes:
  - `<python3_from_config> <absolute_path_to_script> [args...]`
- For Bash scripts: `aris <name>` becomes:
  - `bash <absolute_path_to_script> [args...]`

The script receives all remaining arguments unchanged.

## Refresh behavior

`src/refresh.py` runs automatically on every `aris` invocation:

- Discovers local scripts in `scripts/`.
- Merges with configured external repositories.
- Updates `config.yaml` `scripts:` section.
- Ensures `.sh` scripts are executable.
- Ensures `logs/<script_name>/` exists for each script.

## Notes / Extensions

- Add richer metadata by using Python module docstrings or leading shell comments.
- Extend completion support to zsh/fish by adding generators in `src/completion.py`.
- Add caching or incremental refresh if scripts folder becomes very large.
