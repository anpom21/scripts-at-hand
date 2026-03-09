"""ARIS CLI — Click-based entry point with native shell completion.

Architecture:
  1. A custom Click Group resolves both built-in commands (search) and
     dynamic script names from config.yaml.
  2. Shell completion (bash/zsh/fish) is handled natively by Click.
     Activate with:  eval "$(_ARIS_COMPLETE=bash_source aris)"
  3. Script names and shortcuts appear as completable commands via
     list_commands() / get_command().
  4. File arguments for scripts complete from both the script's configured
     execution_path and the current working directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure sibling modules (utils, run, etc.) are importable with bare names.
# They use `from utils import ...` internally and we preserve that.
_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import click
from click.shell_completion import CompletionItem

from utils import load_config, build_script_index, find_entry


# ---------------------------------------------------------------------------
# Repo root resolution
# ---------------------------------------------------------------------------

def _get_root() -> Path:
    """Return the ARIS CLI repository root.

    Uses ARIS_ROOT env var if set, otherwise derives from this file's
    location: src/cli.py -> src/ -> aris-cli/
    """
    env_root = os.environ.get("ARIS_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Custom parameter type: file completion from execution_path + cwd
# ---------------------------------------------------------------------------

class ScriptPathType(click.ParamType):
    """Completes file paths from a script's execution_path and cwd."""

    name = "path"

    def __init__(self, execution_path: str = ""):
        self.execution_path = execution_path

    def shell_complete(self, ctx, param, incomplete):
        completions = []
        seen: set[str] = set()

        dirs = []
        if self.execution_path:
            ep = Path(self.execution_path)
            if ep.is_dir():
                dirs.append(ep)
        dirs.append(Path.cwd())

        for base_dir in dirs:
            try:
                if "/" in incomplete:
                    parent_part, prefix = incomplete.rsplit("/", 1)
                    search_dir = base_dir / parent_part
                else:
                    prefix = incomplete
                    search_dir = base_dir
                    parent_part = ""

                if not search_dir.is_dir():
                    continue

                for item in search_dir.iterdir():
                    if item.name.startswith(prefix):
                        rel = f"{parent_part}/{item.name}" if parent_part else item.name
                        if rel not in seen:
                            seen.add(rel)
                            completions.append(CompletionItem(
                                rel, type="dir" if item.is_dir() else "file"
                            ))
            except OSError:
                continue

        return completions


# ---------------------------------------------------------------------------
# Custom Click Group: resolves script names as dynamic commands
# ---------------------------------------------------------------------------

class ArisCLI(click.Group):
    """Click group that resolves config.yaml script names as sub-commands."""

    def list_commands(self, ctx):
        """Static commands + all script names/shortcuts/groups from config."""
        commands = set(super().list_commands(ctx))

        try:
            root = _get_root()
            cfg = load_config(root)
            for e in cfg.get("scripts", []):
                if e.get("ignore"):
                    continue
                name = e.get("name", "")
                if name:
                    commands.add(name)
                shortcut = e.get("shortcut", "")
                if shortcut:
                    commands.add(shortcut)
            # Add group names for group-based listing
            entries = build_script_index(root, cfg)
            for entry in entries:
                if not entry.ignore and entry.group:
                    commands.add(entry.group)
        except Exception:
            pass  # Don't break completion if config is unreadable

        return sorted(commands, key=str.lower)

    def get_command(self, ctx, cmd_name):
        """Static commands first, then try as script name/shortcut/group."""
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        try:
            root = _get_root()
            cfg = load_config(root)
            entries = build_script_index(root, cfg)
            active = [e for e in entries if not e.ignore]
            entry = find_entry(active, cmd_name)
            if entry is not None:
                return _make_script_command(entry)

            # Try as group name
            group_entries = [e for e in active if e.group == cmd_name]
            if group_entries:
                return _make_group_command(cmd_name, group_entries)
        except Exception:
            pass

        return None

    def resolve_command(self, ctx, args):
        """Disable Click's fuzzy/prefix command matching."""
        cmd_name = args[0] if args else None
        if cmd_name:
            cmd = self.get_command(ctx, cmd_name)
            if cmd:
                return cmd_name, cmd, args[1:]
        return super().resolve_command(ctx, args)


def _make_script_command(entry):
    """Create a Click command that runs a configured script."""
    from run import run_script

    @click.command(
        name=entry.name,
        context_settings=dict(
            ignore_unknown_options=True,
            allow_extra_args=True,
            allow_interspersed_args=False,
            help_option_names=[],  # Pass --help through to the script
        ),
        help=entry.description or f"Run {entry.name}",
    )
    @click.argument("args", nargs=-1, type=ScriptPathType(entry.execution_path))
    @click.pass_context
    def cmd(ctx, args):
        root = _get_root()
        all_args = list(args) + ctx.args
        raise SystemExit(run_script(root, entry.name, all_args))

    return cmd


def _make_group_command(group_name, entries):
    """Create a Click command that lists scripts in a group."""

    @click.command(
        name=group_name,
        help=f"List scripts in group '{group_name}'",
    )
    def cmd():
        GREEN = "\033[0;32m"
        DIM = "\033[2m"
        RED = "\033[0;31m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        click.echo(f"\n  {BOLD}[{group_name}]{RESET}")
        for e in sorted(entries, key=lambda x: x.name.lower()):
            name_colored = f"{GREEN}{e.name}{RESET}"
            shortcut_colored = f" {DIM}({e.shortcut}){RESET}" if e.shortcut else ""
            src_colored = f" {RED}[{e.source}]{RESET}" if e.source != "local" else ""
            desc_colored = f" {DIM}- {e.description}{RESET}" if e.description else ""
            click.echo(f"    {name_colored}{shortcut_colored}{src_colored}{desc_colored}")
        click.echo()

    return cmd


# ---------------------------------------------------------------------------
# Main CLI group
# ---------------------------------------------------------------------------

@click.group(
    cls=ArisCLI,
    name="aris",
    invoke_without_command=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
)
@click.option("--add", "-a", "add_path", type=click.Path(), default=None,
              help="Add a script (.py/.sh) or git repository.")
@click.option("--open", "-o", "open_target", is_flag=False, flag_value=".",
              default=None, help="Open repository or script in editor.")
@click.option("--config", "-c", "open_config", is_flag=True,
              help="Open config.yaml in default editor.")
@click.option("--list", "list_scripts_flag", is_flag=True,
              help="List all available scripts.")
@click.option("--refresh", is_flag=True,
              help="Refresh script index and show changes.")
@click.option("--revert", is_flag=True,
              help="Revert config.yaml to previous backup.")
@click.option("--reset-config", is_flag=True,
              help="Reset per-script config but keep shortcuts.")
@click.pass_context
def cli(ctx, add_path, open_target, open_config, list_scripts_flag,
        refresh, revert, reset_config):
    """Unified runner for ARIS production scripts.

    \b
    Run scripts:  aris <script> [args...]
    Search:       aris search
    List:         aris --list

    \b
    Examples:
      aris collection_annots_overview.py <collection_dir>
      aris 2_rename_files.py --help
      aris review_annotations.py -d ./my_collection
    """
    ctx.ensure_object(dict)
    root = _get_root()
    ctx.obj["root"] = root

    # Ensure config exists
    cfg_file = root / "config.yaml"
    if not cfg_file.exists():
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        cfg_file.write_text("repositories: []\n\n\nscripts: []\n")

    # Handle flag-based actions (mutually exclusive by convention)
    if add_path:
        _do_add(root, add_path)
        return

    if open_target:
        _do_open(root, open_target)
        return

    if open_config:
        _do_config(root)
        return

    if list_scripts_flag:
        from run import list_scripts
        raise SystemExit(list_scripts(root))

    if revert:
        _do_revert(root)
        return

    if reset_config:
        _do_refresh(root, verbose=True, reset=True)
        return

    if refresh:
        _do_refresh(root, verbose=True)
        return

    # No flag and no subcommand → show help
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# Flag action handlers
# ---------------------------------------------------------------------------

def _do_add(root: Path, path_str: str):
    from utils import add_script_to_config, add_repository_to_config

    target = Path(path_str)
    if not target.is_absolute():
        target = Path.cwd() / target

    if target.is_file():
        if target.suffix.lower() in {".py", ".sh"}:
            success = add_script_to_config(root, target)
        else:
            click.echo("Error: File must be a .py or .sh script", err=True)
            raise SystemExit(1)
    elif target.is_dir() and (target / ".git").exists():
        success = add_repository_to_config(root, target)
    else:
        cfg = load_config(root)
        success = False
        for repo in cfg.get("repositories") or []:
            if repo.get("name") == target.name:
                repo_path = Path(repo["path"])
                click.echo(f"Defaulting to existing repository: {repo['name']}")
                success = add_repository_to_config(root, repo_path)
                break

        if not success:
            if target.is_dir():
                click.echo("Error: Directory is not a git repo (no .git folder)", err=True)
            else:
                click.echo(f"Error: Not a file or directory: {target}", err=True)
            raise SystemExit(1)

    raise SystemExit(0 if success else 1)


def _do_open(root: Path, target: str = "."):
    import shutil

    if target and target != ".":
        # Open a specific script by name or shortcut
        cfg = load_config(root)
        entries = build_script_index(root, cfg)
        active = [e for e in entries if not e.ignore]
        entry = find_entry(active, target)
        if entry is None:
            click.echo(f"Error: Script not found: {target}", err=True)
            raise SystemExit(1)

        script_path = entry.abspath
        click.echo(f"Opening script: {script_path}")
        if shutil.which("code"):
            os.execvp("code", ["code", script_path])
        elif os.environ.get("EDITOR"):
            editor = os.environ["EDITOR"]
            os.execvp(editor, [editor, script_path])
        elif shutil.which("xdg-open"):
            os.execlp("xdg-open", "xdg-open", script_path)
        elif shutil.which("vim"):
            os.execvp("vim", ["vim", script_path])
        elif shutil.which("nano"):
            os.execvp("nano", ["nano", script_path])
        else:
            os.execvp("vi", ["vi", script_path])
    else:
        # Open whole repository
        click.echo(f"Repository location: {root}")
        if shutil.which("code"):
            click.echo("Opening in VS Code...")
            os.execvp("code", ["code", str(root)])
        else:
            click.echo("VS Code (code) not found in PATH")


def _do_config(root: Path):
    import shutil

    cfg_path = root / "config.yaml"
    click.echo(f"Opening config: {cfg_path}")

    editor = os.environ.get("EDITOR")
    if editor:
        os.execvp(editor, [editor, str(cfg_path)])
    elif shutil.which("xdg-open"):
        os.execlp("xdg-open", "xdg-open", str(cfg_path))
    elif shutil.which("open"):
        os.execlp("open", "open", str(cfg_path))
    elif shutil.which("vim"):
        os.execvp("vim", ["vim", str(cfg_path)])
    elif shutil.which("nano"):
        os.execvp("nano", ["nano", str(cfg_path)])
    else:
        os.execvp("vi", ["vi", str(cfg_path)])


def _do_refresh(root: Path, verbose: bool = False, reset: bool = False):
    from refresh import refresh as do_refresh

    if reset:
        setattr(do_refresh, "reset_config", True)

    result = do_refresh(root, verbose=verbose)

    if reset:
        click.echo("Resetting configuration completed.")
    else:
        click.echo("Refresh completed.")

    raise SystemExit(result)


def _do_revert(root: Path):
    from utils import revert_config

    success = revert_config(root)
    if success:
        click.echo("\nRefreshing script index...")
        from refresh import refresh as do_refresh
        do_refresh(root, verbose=False)

    raise SystemExit(0 if success else 1)


# ---------------------------------------------------------------------------
# Built-in subcommands
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def search(ctx):
    """Interactive search for scripts."""
    from search import interactive_search

    root = ctx.obj["root"]
    raise SystemExit(interactive_search(root))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Console-scripts entry point. Sets prog_name for consistent completion."""
    cli(prog_name="aris")


if __name__ == "__main__":
    main()
