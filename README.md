# ARIS CLI

A lightweight, repo-local CLI that consolidates many production scripts (Python + Bash) behind a single command:

- `aris` lists scripts and shows usage
- `aris <script_name> [args...]` runs a script
- `aris search` opens an interactive real-time search UI with tag-based filtering
- `aris refresh` updates `config.yaml` and permissions
- `aris --config` opens config file in your default editor

## Recent Features

✨ **Shortcuts** - Create short aliases for scripts: `aris summarise` instead of `aris 0_summarise_imgs_and_annots.py`

🏷️ **Tags** - Organize scripts with tags for powerful search filtering and categorization

🎨 **Smart Search** - Tags and source repositories are searchable with color-coded results (cyan for tags, yellow for sources)

💾 **Format Preservation** - Config file maintains your comments, blank lines, and custom formatting

🔧 **Quick Config Access** - `aris -c` opens config.yaml instantly

🔄 **Smart Reset** - `aris --reset-config` refreshes paths while preserving shortcuts and tags

## Repository Layout

```
└── src/
    ├── refresh.py
    ├── run.py
    ├── search.py
    ├── completion.py
    └── utils.py
```

## Install / Use

### Easy install:

```bash
bash ./install.sh
```

### Manual install:

### 1) Clone repository

```bash
git clone https://github.com/yourusername/aris-cli.git
cd aris-cli
```

### 2) Install dependencies

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

To use some GUI scripts (e.g., `collection_sorter.py`), a workaround is needed to ensure tkinter works correctly in uv virtual environments. Run the following commands to copy the system's tkinter library into the uv venv:

```bash
uv venv --python /usr/bin/python3.12 .venv
```

Then source and sync the libraries:

```bash
source .venv/bin/activate
uv sync --active
```

### 2) Add `aris` as a command

Add an alias to your `~/.bashrc` or `~/.zshrc` and source the completion script:

**For Bash:**

```bash
echo "#>>> aris-cli initialize >>>" >> ~/.bashrc
echo "alias aris='$(pwd)/main.sh'" >> ~/.bashrc
echo "source <(aris completion bash)" >> ~/.bashrc
echo "#<<< aris-cli initialize <<<" >> ~/.bashrc
source ~/.bashrc
```

**For Zsh:**

```bash
echo "#>>> aris-cli initialize >>>" >> ~/.zshrc
echo "alias aris='$(pwd)/main.sh'" >> ~/.zshrc
echo "source <(aris completion zsh)" >> ~/.zshrc
echo "#<<< aris-cli initialize <<<" >> ~/.zshrc
source ~/.zshrc
```

## Usage

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

# ARIS CLI

Edit `config.yaml`:

```yaml
repositories:
  - name: Annotation
    path: /home/simon/Annotation
    python3: /home/simon/Annotation/.venv/bin/python3
    execution_path: /home/simon/Annotation # optional: working directory for scripts
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

## Advanced Features

Create short aliases for frequently-used scripts by adding a `shortcut` field in `config.yaml`:

```yaml
scripts:
  - name: 0_summarise_imgs_and_annots.py
    python3: /home/simon/.pyenv/versions/3.8.10/bin/python3
    execution_path: /home/simon/aris-cli/scripts/the_training_bible/organize_data
    hash_id: 392807cfb50f39822e08a6c9efb39986cd83f5c0de13ef3148ba42e091575acf
    source: local
    shortcut: summarise
    tags: [training_bible, organize_data]
```

**Usage:**

```bash
aris 0_summarise_imgs_and_annots.py --help

# Use the shortcut:
aris summarise --help
```

**Collision Detection:**

**Autocompletion:**

- Shortcuts are included in shell completion (bash and zsh)
- Type `aris sum` + TAB → completes to `aris summarise`

**Display:**

- Example: `0_summarise_imgs_and_annots.py (summarise)`

### Tags and Categorization

Organize scripts with tags for better search and discovery:

```yaml
scripts:
  - name: 0_summarise_imgs_and_annots.py
    shortcut: summarise
    tags: [training_bible, organize_data, move]
```

**Search Priority:**

- Tags have the highest search priority (even higher than script names)
- Searching for a tag instantly brings up all tagged scripts
- Matching tags are displayed in **bold cyan** in search results

**Source as Special Tag:**

- Displayed in **bold yellow** when they match your search
- Search for "annotation" to find all scripts from the Annotation repository
- Search for "classification" to find all Classification scripts

**Tag Display in Search:**

```
1. segment.py [Annotation]
   tags: Annotation  (in bold yellow)

2. 0_summarise_imgs_and_annots.py
   tags: training_bible, organize_data, move  (matching tags in bold cyan)
```

### Configuration Management

#### Quick Config Access

Open the config file quickly without remembering the path:

```bash
aris --config    # Opens config.yaml in default editor
aris -c          # Short form
```

Prints: `Opening config: /home/simon/aris-cli/config.yaml`

Uses the best available editor:

1. `$EDITOR` environment variable (if set)
2. `xdg-open` (Linux GUI applications)
3. `open` (macOS)
4. Fallbacks: `vim`, `nano`, `vi`

#### Reset Configuration

Reset per-script overrides while preserving shortcuts and tags:

````
This resets:
- `python3` path
- `execution_path`
- `name` (script name)
- `hash_id`
- `source`

But **preserves**:

- `shortcut`
- `tags`
- Python environment changes

#### YAML Formatting Preservation

The config file now preserves your custom formatting:

- **Comments** are maintained (including header comments)
- **Blank lines** between entries are preserved
- **Indentation** and structure remain unchanged
- **Tags** stay in inline format: `tags: [tag1, tag2, tag3]`
You can safely add comments and organize your config:

```yaml
# ---------------------------------------------------------------------------- #
#                                 Repositories                                 #
# ---------------------------------------------------------------------------- #
repositories:
  - name: Annotation
    path: /home/simon/Annotation
    python3: /home/simon/Annotation/.venv/bin/python3
    scripts:
      - segment.py
      - review_annotations.py

  - name: Synthetics
    path: /home/simon/Documents/Synthetics
    python3: /home/simon/Documents/Synthetics/.venv/bin/python3
    scripts:
      - run.sh
      - synthesize.py
# ---------------------------------------------------------------------------- #
#                                    Scripts                                   #
# ---------------------------------------------------------------------------- #
scripts:
  - name: segment.py
    source: Annotation
    shortcut: segment
    tags: [ml, annotation]

  - name: synthesize.py
    source: Synthetics
    shortcut: synth
    tags: [data_generation, training]
````

Running `aris --refresh` will **not** remove your comments or blank lines!

### Enhanced Search Features

The interactive search (`aris search`) includes several powerful features:

**Search Priority (highest to lowest):**

1. **Tags and Source** - Scripts with matching tags or source repositories appear first
2. **Script Name** - Scripts with matches in their name
3. **Description** - Scripts with matches in their description
4. **Shortcuts** - Scripts with shortcuts always rank higher within their priority group

**Color Coding:**

- **Red**: Matching text in script names
- **Cyan**: Matching tags
- **Yellow**: Matching source (repository name)
- **Dim Gray**: Non-matching metadata (descriptions, tags, sources)

**Example Search Results:**

```
Search: training

Found 5 result(s):

  1. 0_summarise_imgs_and_annots.py [local]
     tags: training_bible, organize_data, move

  2. train.py [Classification]
     tags: Classification

  3. generate_training_data.py [local]
     Generates synthetic training data for model...
```

### Error Handling

**Friendly YAML Errors:**
If there's a syntax error in `config.yaml`, you'll see a helpful colored error message instead of a Python traceback:

```
[ERROR] Config syntax is incorrect
  mapping values are not allowed here

   12:   python3: /home/simon/Annotation/.venv/bin/python3
   13:   scripts:
   14:   - segment.py
-> 15:   - review_annotations.py: invalid
   16: scripts:
   17: - name: segment.py
```

**Debug Mode:**
Set `ARIS_DEBUG=1` to see full Python tracebacks for troubleshooting:

```bash
ARIS_DEBUG=1 aris --refresh
```

## Command Reference

```bash
# Run a script
aris <script_name> [args...]
aris <shortcut> [args...]

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

## Core Features Summary

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
- Shell completion is supported for both bash and zsh with lazy-loading architecture (zero Python overhead).
- Add caching or incremental refresh if scripts folder becomes very large.
