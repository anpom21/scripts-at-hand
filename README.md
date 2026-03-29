# ARIS CLI

A lightweight, repo-local CLI that consolidates many production scripts (Python + Bash) behind a single command:

- `aris` shows how to use the CLI and lists some common commands
- `aris <script_name> [args...]` runs a script. eg `aris summarise_imgs_and_annots.py -h`
- `aris search` opens an interactive search interface to find scripts by name, tags, or source repository
- `aris --list` lists all available scripts with their sources and tags
- `aris --add <script_path>` adds a new script to the config
- `aris refresh` updates [config.yaml](config.yaml) with any new scripts found in the `scripts/` folder or configured repositories

## Install

Run the following commands in your terminal to install the ARIS CLI:

```bash
git clone https://github.com/yourusername/aris-cli.git
cd aris-cli
bash ./install.sh
```

The install script will install dependencies with `uv` and create a bash function which points to the `run.sh` script.

## Usage

### 1) Run scripts

To run any script configured in `config.yaml` or placed in the `scripts/` folder, simply use:

```bash
aris <script_name> [args...]
```

Example:

```bash
aris summarise_imgs_and_annots.py --help
```

### 2) Add scripts

The simplest way to add scripts is to place them in the `scripts/` folder. This supports both Python (`.py`) and Bash (`.sh`) scripts.
To add a script through the terminal, use:

```bash
aris --add /path/to/your/script.py
```

### 2.1) Add scripts from a repository

If a script or multiple scripts are within a git repository, use the repository folder path as the argument, and select the scripts you want to add interatively:

```bash
aris --add /path/to/your/repository
```

This will show:

```bash
$ aris --add .
Found Python environment: /home/ap/cloud/ARIS/aris-cli/.venv/bin/python3
Repository already exists in config: aris-cli. Extracting scripts...
Existing name: 5
[?] Select scripts to add from aris-cli (use space to select, enter to confirm):
   [ ] install.sh
   [ ] run.sh
   [X] scripts/analyze_synth_base_images.py
 > [X] scripts/extract_argparse_options.py
```

Now the user can navigate the list of scripts with the arrow keys, select multiple scripts with space, and confirm with enter. The selected scripts will be added to the config with the repository name as their source.

### 3) List a group of scripts

To list all scripts, use:

```bash
aris --list
```

Scripts can be organized into groups by moving them into subfolders within `scripts/`. The group name will be the subfolder name. For example:

```scripts/
├── data_processing/
│   ├── clean_data.py
│   └── transform_data.py
├── model_training/
│   ├── train_model.py
│   └── evaluate_model.py
└── utility_scripts/
    ├── summarize_results.py
    └── extract_features.py
```

In this structure, you can list scripts by group:

```bash
aris data_processing
```

This will show only the scripts in the `data_processing/` group. All scripts added from a repository will be associated with that repository as their source.

### 3) Autocomplete

Autocomplete now includes all scripts from both local and configured repositories.

**Usage examples:**

- Type `aris sync_an` and press TAB → completes to `aris sync_and_sort_images.sh`
- Type `aris sy` and press TAB → shows all scripts starting with "sy": `sync_and_sort_images.sh`, `sync_image_files.py`, `synthesize.py`
- After the script name, TAB provides file/directory completion for script arguments

## Refresh behavior

`aris --refresh` performs a comprehensive sync of your scripts:

- Discovers local scripts in `scripts/`.
- Merges with configured external repositories.
- Updates `config.yaml` `scripts:` section.
- Ensures `.sh` scripts are executable.
- Detects script content collisions using SHA256 hashes.
- **Shows change summary**: When scripts are added or removed, displays:
  - Bold green success message
  - `+ script_name [source]` in green for added scripts
  - `- script_name [source]` in red for removed scripts

## Command Reference

```bash
# Run a script
aris <script_name> [args...]
aris <shortcut> [args...]

# Add a new script
aris --add /path/to/script.py
aris --add /path/to/repository

# List all scripts
aris --list

# Interactive search
aris search

# Open config file
aris --config

# Refresh script index
aris --refresh

# Reset configuration (keeps shortcuts and tags)
aris --reset-config

# Show help
aris --help
aris -h
```

<!-- ------------------------------ For later ------------------------------ -->

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
