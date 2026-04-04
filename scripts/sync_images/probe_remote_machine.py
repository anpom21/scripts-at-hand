#!/usr/bin/env python3

import argparse
import getpass
import sys
from pathlib import Path

import yaml

REMOTE_CMD = "cd images_backup && find ~+ -iwholename '*.png'"

ANSI_RESET = "\033[0m"
ANSI_BOLD_WHITE = "\033[1;97m"
ANSI_GREEN = "\033[92m"


def format_prompt(text: str) -> str:
    return f"{ANSI_BOLD_WHITE}{text}{ANSI_RESET}"


def format_message(text: str) -> str:
    return f"{ANSI_GREEN}{text}{ANSI_RESET}"


def print_message(text: str) -> None:
    print(format_message(text))

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe a remote machine and count PNG images in images_backup."
    )
    parser.add_argument(
        "--machine",
        required=True,
        help="Machine name defined in machine_config.yaml (for example: fierce-wolf).",
    )
    parser.add_argument(
        "--machine_config",
        default=str(Path(__file__).with_name("machine_config.yaml")),
        help="Path to machine config YAML file.",
    )
    parser.add_argument(
        "--remote-cmd",
        default=REMOTE_CMD,
        help="Command to execute on the remote machine to find PNG images.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output for debugging.",
    )
    return parser.parse_args()


def load_machine(machine_config: Path, machine_name: str) -> dict:
    if not machine_config.exists():
        raise FileNotFoundError(f"Config file not found: {machine_config}")

    with machine_config.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    machines = config.get("machines", [])
    if not isinstance(machines, list):
        raise ValueError("Invalid config format: 'machines' must be a list")

    for machine in machines:
        if machine.get("name") == machine_name:
            return machine

    names = sorted(
        m.get("name")
        for m in machines
        if isinstance(m, dict) and isinstance(m.get("name"), str)
    )
    raise ValueError(
        f"Machine '{machine_name}' not found. Available machines: {', '.join(names)}"
    )


def ensure_credentials(machine: dict) -> tuple[str, str, str]:
    ip = machine.get("ip")
    if ip is None or str(ip).strip() == "":
        raise ValueError("Machine is missing 'ip' in config")

    username = machine.get("username")
    if username is None or str(username).strip() == "":
        username = input(format_prompt("Enter username: ")).strip()
        if not username:
            raise ValueError("Username cannot be empty")

    password = machine.get("password")
    if password is None or str(password).strip() == "":
        password = getpass.getpass(format_prompt("Enter password: "))
        if not password:
            raise ValueError("Password cannot be empty")

    return str(ip).strip(), str(username).strip(), str(password)


def establish_client_connection(
    ip: str, username: str, password: str, timeout: int = 15
):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'paramiko'. Install project dependencies first."
        ) from exc

    print_message(f"Connecting to {username}@{ip}...")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for attempt in range(3):
        try:
            client.connect(hostname=ip, username=username, password=password, timeout=timeout)
            break
        except Exception as exc:
            print(f"Failed to connect to {username}@{ip} after {timeout} seconds.")# Error: {exc}
            user_input = input(format_prompt("Retry? (y/n): ")).strip().lower()
            if user_input != "y":
                print("Connection aborted by user")
                sys.exit(1)
            else:
                print_message("Retrying connection...")
                continue
    if client is None:
        raise RuntimeError(f"Failed to connect to {username}@{ip} after multiple attempts")
    return client


def execute_remote_command(client, remote_cmd: str = REMOTE_CMD) -> list[str]:
    _, stdout, stderr = client.exec_command(remote_cmd)

    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")

    if err.strip():
        print("Remote stderr:", file=sys.stderr)
        print(err.strip(), file=sys.stderr)

    return [line for line in out.splitlines() if line.strip()]


def extract_png_paths(ip: str, username: str, password: str, remote_cmd: str) -> list[str]:
    global REMOTE_CMD
    client = establish_client_connection(ip=ip, username=username, password=password)

    try:
        return execute_remote_command(client=client, remote_cmd=remote_cmd)
    finally:
        client.close()
    

def probe_machine(machine_config: str, machine: str, remote_cmd: str, verbose: bool = False):
    machine_config = Path(machine_config).expanduser().resolve()
    max_attempts = 3

    machine = load_machine(machine_config, machine)
    print_message(f"Machine: {machine.get('name', 'Unknown')}")
    for attempt in range(max_attempts):
        try:
            ip, username, password = ensure_credentials(machine)
            paths = extract_png_paths(ip=ip, username=username, password=password, remote_cmd=remote_cmd)
            break  # Success, exit the retry loop
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            if attempt < max_attempts - 1:
                print_message("Please try again.")
            else:
                print_message("Maximum attempts reached. Exiting.")
                return 1
            
    return paths




def main() -> int:
    args = parse_args()
    paths = probe_machine(machine_config=args.machine_config, machine=args.machine, remote_cmd=args.remote_cmd, verbose=args.verbose)
    if args.verbose:
        print(f"PNG images found: {paths}")
        print(f"Total PNG images found: {len(paths)}")
    return len(paths)    

if __name__ == "__main__":
    raise SystemExit(main())
