#!/bin/bash
# Syncs images from GCS by date range, builds inference records, and sorts them into category folders.
# Script to sync and sort images from a machine
# Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <suffix>]

set -e  # Exit on error

# Color codes
BOLD_GREEN='\033[1;32m'
DARK_GREY='\033[0;37m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

MACHINE_CONFIG_PATH="$(dirname "$0")/machine_config.yaml"
PYTHON="../../.venv/bin/python3"

# Collection base paths by fraction
declare -A COLLECTION_BASE_BY_FRACTION=(
    ["wood"]="/home/simon/Data/Collections_wood"
    ["dangerous_waste"]="/home/simon/Data/Dangerous_waste_jpg"
    ["mineral_wool"]="/home/simon/Data/Collections_mineral_wool"
    ["plastic"]="/home/simon/Data/Collections_plastic"
    ["unassigned"]="/home/simon/Data/Collections_unassigned"
)

declare -A CATEGORY_TEMPLATE_BY_FRACTION=(
    ["wood"]="/home/simon/Repositories/image-sorter/category_templates/wood"
    ["dangerous_waste"]="None"
    ["mineral_wool"]="/home/simon/Repositories/image-sorter/category_templates/mineral_wool"
    ["plastic"]="/home/simon/Repositories/image-sorter/category_templates/plastic"
    ["unassigned"]="None"
)

# Collection base is resolved after fraction is known (or via --collection-base).
COLLECTION_BASE=""
COLLECTION_BASE_OVERRIDDEN=0
SUFFIX=""
ORIGINAL_ARG_COUNT=$#

update_last_sync() {
    local machine_config_path="$1"
    local machine_name="$2"
    local end_date="$3"

    "$PYTHON" - "$machine_config_path" "$machine_name" "$end_date" <<'PY'
import sys
from datetime import datetime
from pathlib import Path

import yaml

config_path = Path(sys.argv[1]).expanduser().resolve()
machine_name = sys.argv[2]
end_date = sys.argv[3]

# Validate YYYY-MM-DD format strictly.
parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

with config_path.open("r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

machines = config.get("machines", [])
if not isinstance(machines, list):
    raise SystemExit("Invalid machine config: 'machines' must be a list")

updated = False
for machine in machines:
    if isinstance(machine, dict) and machine.get("name") == machine_name:
        machine["last_sync"] = parsed_end_date
        updated = True
        break

if not updated:
    raise SystemExit(f"Machine '{machine_name}' not found in machine config")

with config_path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(config, f, sort_keys=False)

print(f"Updated last_sync for {machine_name} to {end_date}")
PY
}

# Parse command line arguments
#Check that args were provided at all
while [[ $# -gt 0 ]]; do
    case $1 in
        --machine)
            MACHINE="$2"
            shift 2
            ;;
        --capture-dir)
            CAPTURE_DIR="$2"
            shift 2
            ;;
        --begin-date)
            BEGIN_DATE="$2"
            shift 2
            ;;
        --end-date)
            END_DATE="$2"
            shift 2
            ;;
        --collection-base)
            COLLECTION_BASE="$2"
            COLLECTION_BASE_OVERRIDDEN=1
            shift 2
            ;;
        --suffix)
            SUFFIX="$2"
            shift 2
            ;;
        --help)
            echo "Sync and sort images from a machine by date range."
            echo "Interactive mode (no args): bash sync_and_sort_images.sh"
            echo "Legacy Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <suffix>]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Interactive mode (no args): bash sync_and_sort_images.sh"
            echo "Legacy Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <suffix>]"
            exit 1
            ;;
    esac
done

# Interactive mode: if no args were provided, select fraction + machine from config.
if [ "$ORIGINAL_ARG_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}No arguments provided. Starting interactive selection...${RESET}"

    if [ ! -f "$MACHINE_CONFIG_PATH" ]; then
        echo "Error: Machine config not found: $MACHINE_CONFIG_PATH"
        exit 1
    fi

    SELECTED_MACHINE_FILE=$(mktemp)
    SELECTOR_SCRIPT=$(mktemp)
    cat > "$SELECTOR_SCRIPT" <<'PY'
import sys
from pathlib import Path

import yaml

try:
    import inquirer
except ImportError:
    print("Error: Missing Python dependency 'inquirer'. Install it with: pip install inquirer", file=sys.stderr)
    raise SystemExit(2)


def fraction_label(raw_fraction):
    if raw_fraction is None:
        return "unassigned"
    as_text = str(raw_fraction).strip()
    return as_text if as_text else "unassigned"


config_path = Path(sys.argv[1]).expanduser().resolve()
out_path = Path(sys.argv[2]).expanduser().resolve()

with config_path.open("r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

machines = config.get("machines", [])
if not isinstance(machines, list) or not machines:
    print("Error: No machines found in config", file=sys.stderr)
    raise SystemExit(1)

fraction_to_machines = {}
for machine in machines:
    if not isinstance(machine, dict):
        continue
    name = machine.get("name")
    if not isinstance(name, str) or not name.strip():
        continue
    label = fraction_label(machine.get("fraction"))
    fraction_to_machines.setdefault(label, []).append(name.strip())

if not fraction_to_machines:
    print("Error: No valid machine entries found in config", file=sys.stderr)
    raise SystemExit(1)

fraction_choices = sorted(fraction_to_machines.keys())
fraction_answer = inquirer.prompt(
    [
        inquirer.List(
            "fraction",
            message="Select fraction",
            choices=fraction_choices,
        )
    ]
)

if not fraction_answer:
    raise SystemExit(1)

selected_fraction = fraction_answer["fraction"]
machine_choices = sorted(fraction_to_machines[selected_fraction])
machine_answer = inquirer.prompt(
    [
        inquirer.List(
            "machine",
            message=f"Select machine for fraction '{selected_fraction}'",
            choices=machine_choices,
        )
    ]
)

if not machine_answer:
    raise SystemExit(1)

selected_machine = machine_answer["machine"]
selected_last_sync = ""
for machine in machines:
    if isinstance(machine, dict) and machine.get("name") == selected_machine:
        raw_last_sync = machine.get("last_sync")
        if raw_last_sync is not None:
            selected_last_sync = str(raw_last_sync).strip()
        break

if selected_last_sync and selected_last_sync.lower() != "null":
    out_path.write_text(
        f"{selected_machine}\x1f{selected_last_sync}\x1f{selected_fraction}\n",
        encoding="utf-8",
    )
else:
    out_path.write_text(f"{selected_machine}\x1f\x1f{selected_fraction}\n", encoding="utf-8")
PY

    if ! "$PYTHON" "$SELECTOR_SCRIPT" "$MACHINE_CONFIG_PATH" "$SELECTED_MACHINE_FILE"; then
        rm -f "$SELECTOR_SCRIPT"
        rm -f "$SELECTED_MACHINE_FILE"
        exit 1
    fi
    rm -f "$SELECTOR_SCRIPT"

    IFS=$'\x1f' read -r MACHINE LAST_SYNC SELECTED_FRACTION < "$SELECTED_MACHINE_FILE" || true
    rm -f "$SELECTED_MACHINE_FILE"
    echo "Selected fraction: $SELECTED_FRACTION"
    if [ "$SELECTED_FRACTION" = "dangerous_waste" ]; then
        echo "----------------------------------------"
        "$PYTHON" "$(dirname "$0")/dw_sync.py" --unit "$MACHINE"
        exit $?
    fi

    if [ "$COLLECTION_BASE_OVERRIDDEN" -eq 0 ] && [[ -n "$SELECTED_FRACTION" ]]; then
        if [[ -n "${COLLECTION_BASE_BY_FRACTION[$SELECTED_FRACTION]+x}" ]]; then
            COLLECTION_BASE="${COLLECTION_BASE_BY_FRACTION[$SELECTED_FRACTION]}"
        fi
    fi

    if [ -z "$MACHINE" ]; then
        echo "Error: No machine selected."
        exit 1
    fi

    if [[ -n "$LAST_SYNC" && "$LAST_SYNC" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then

        read -p "Use last sync date ${LAST_SYNC} as begin date? [Y/n]: " -r
        if [ -z "$REPLY" ]; then
            REPLY="y"
        fi
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            BEGIN_DATE="$LAST_SYNC"
            echo "Using begin date: $BEGIN_DATE"
        else
            read -p "Enter begin date (YYYY-MM-DD): " BEGIN_DATE
        fi
    else
        read -p "Enter begin date (YYYY-MM-DD): " BEGIN_DATE
    fi

    YESTERDAY_DATE=$(date -d "yesterday" +%Y-%m-%d)
    read -p "Use end date ${YESTERDAY_DATE}? [Y/n]: " -r
    if [ -z "$REPLY" ]; then
        REPLY="y"
    fi

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        END_DATE="$YESTERDAY_DATE"
        echo "Using end date: $END_DATE"
    else
        read -p "Enter end date (YYYY-MM-DD): " END_DATE
    fi
fi

# Validate required arguments
if [ -z "$MACHINE" ] || [ -z "$BEGIN_DATE" ] || [ -z "$END_DATE" ]; then
    echo "Error: Missing required arguments (--machine, --begin-date, --end-date)"
    echo "Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <suffix>]"
    exit 1
fi

# If collection base was not explicitly provided, derive it from machine fraction.
if [ "$COLLECTION_BASE_OVERRIDDEN" -eq 0 ] && [ -z "$SELECTED_FRACTION" ]; then
    SELECTED_FRACTION=$("$PYTHON" - "$MACHINE_CONFIG_PATH" "$MACHINE" <<'PY'
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1]).expanduser().resolve()
machine_name = sys.argv[2]

with config_path.open("r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

machines = config.get("machines", [])
if not isinstance(machines, list):
    raise SystemExit(1)

for machine in machines:
    if isinstance(machine, dict) and machine.get("name") == machine_name:
        raw_fraction = machine.get("fraction")
        if raw_fraction is None:
            print("unassigned")
        else:
            as_text = str(raw_fraction).strip()
            print(as_text if as_text else "unassigned")
        raise SystemExit(0)

raise SystemExit(1)
PY
)

    if [[ -n "$SELECTED_FRACTION" ]] && [[ -n "${COLLECTION_BASE_BY_FRACTION[$SELECTED_FRACTION]+x}" ]]; then
        COLLECTION_BASE="${COLLECTION_BASE_BY_FRACTION[$SELECTED_FRACTION]}"
    fi
fi

if [ "$COLLECTION_BASE_OVERRIDDEN" -eq 0 ] && [ -z "$COLLECTION_BASE" ]; then
    echo "Error: Could not resolve collection base for fraction '${SELECTED_FRACTION}'."
    echo "Provide --collection-base explicitly or add that fraction to COLLECTION_BASE_BY_FRACTION."
    exit 1
fi

# Auto-generate capture directory if not provided
if [ -z "$CAPTURE_DIR" ]; then
    # Build the proposed path
    PROPOSED_DIR="${COLLECTION_BASE}/${BEGIN_DATE}_${END_DATE}_prod-data_${MACHINE}"
    if [ -n "$SUFFIX" ]; then
        PROPOSED_DIR="${PROPOSED_DIR}_${SUFFIX}"
    fi
    
    echo -e "${YELLOW}No capture directory specified. Proposed path:${RESET}"
    echo -e "${BOLD}  $PROPOSED_DIR${RESET}"
    echo ""
    echo -n "Options: [y]es to use, [c]ustom to edit, [n]o to abort. "
    read -p "Use this path?: " -r
    echo ""
    
    # Default to 'y' if empty response
    if [ -z "$REPLY" ]; then
        REPLY="y"
    fi
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        CAPTURE_DIR="$PROPOSED_DIR"
        echo "Using proposed directory."
    elif [[ $REPLY =~ ^[Cc]$ ]] || [[ $REPLY == "custom" ]]; then
        read -e -i "$PROPOSED_DIR" -p "Edit capture directory path: " CAPTURE_DIR
        echo ""
        if [ -z "$CAPTURE_DIR" ]; then
            echo "Error: No path provided."
            exit 1
        fi
    else
        echo "Operation aborted by user."
        exit 0
    fi
fi
# Create capture directory if it doesn't exist
if [ ! -d "$CAPTURE_DIR" ]; then
    echo "Creating capture directory: $CAPTURE_DIR"
    mkdir -p "$CAPTURE_DIR"
fi

# Display configuration
echo "=========================================="
echo "Configuration:"
echo "  Machine: $MACHINE"
echo "  Capture Directory: $CAPTURE_DIR"
echo "  Begin Date: $BEGIN_DATE"
echo "  End Date: $END_DATE"
echo "=========================================="
echo ""

# Step 1: Dry run sync
echo -e "${BOLD_GREEN}Step 1: Running dry run sync...${RESET}"
echo "----------------------------------------"
echo -e "${DARK_GREY}"
"$PYTHON" sync_image_files.py \
    --machine "$MACHINE" \
    --local-dir "$CAPTURE_DIR" \
    --begin-date "$BEGIN_DATE" \
    --end-date "$END_DATE"
echo -e "${RESET}"

echo ""
echo "----------------------------------------"
echo "Dry run complete. Review the summary above."
read -p "Do you want to continue with the actual sync? (y/n) [y]: " -r
echo ""

# Default to 'y' if empty response
if [ -z "$REPLY" ]; then
    REPLY="y"
fi

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Operation aborted by user."
    exit 0
fi

# Step 2: Actual sync
echo ""
echo -e "${BOLD_GREEN}Step 2: Running actual sync...${RESET}"
echo "----------------------------------------"
echo -e "${DARK_GREY}"
"$PYTHON" sync_image_files.py \
    --machine "$MACHINE" \
    --local-dir "$CAPTURE_DIR" \
    --begin-date "$BEGIN_DATE" \
    --end-date "$END_DATE" \
    --run
echo -e "${RESET}"

# Step 3: Build inference records
echo ""
echo -e "${BOLD_GREEN}Step 3: Building inference records...${RESET}"
echo "----------------------------------------"
CSV_OUT="$CAPTURE_DIR/bulk_download.csv"
echo -e "${DARK_GREY}"
"$PYTHON" build_inference_records.py \
    --unit "$MACHINE" \
    --local-dir "$CAPTURE_DIR" \
    --csv-out "$CSV_OUT"
echo -e "${RESET}"

# Step 4: Sort images from insights (dry run)
echo ""
echo -e "${BOLD_GREEN}Step 4: Sorting images from insights (dry run)...${RESET}"
echo "----------------------------------------"
echo -e "${DARK_GREY}"
"$PYTHON" sort_images_from_insights.py \
    --images-dir "$CAPTURE_DIR" \
    --csv "$CSV_OUT"
echo -e "${RESET}"

echo ""
echo "----------------------------------------"
echo "Dry run complete. Review the summary above."
read -p "Do you want to continue with the actual image sorting? (y/n) [y]: " -r
echo ""

# Default to 'y' if empty response
if [ -z "$REPLY" ]; then
    REPLY="y"
fi

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Operation aborted by user."
    exit 0
fi

# Step 5: Sort images from insights (actual run)
echo ""
echo -e "${BOLD_GREEN}Step 5: Sorting images from insights (actual run)...${RESET}"
echo "----------------------------------------"
echo -e "${DARK_GREY}"
"$PYTHON" sort_images_from_insights.py \
    --images-dir "$CAPTURE_DIR" \
    --run \
    --csv "$CSV_OUT"
echo -e "${RESET}"

# Step 6: Copy category template folders
echo ""
echo -e "${BOLD_GREEN}Step 6: Ensuring all category folders exist...${RESET}"
echo "----------------------------------------"
CATEGORY_TEMPLATE_PATH=""
if [[ -n "$SELECTED_FRACTION" && -n "${CATEGORY_TEMPLATE_BY_FRACTION[$SELECTED_FRACTION]+x}" ]]; then
    CATEGORY_TEMPLATE_PATH="${CATEGORY_TEMPLATE_BY_FRACTION[$SELECTED_FRACTION]}"
fi
if [ "$CATEGORY_TEMPLATE_PATH" = "None" ]; then
    echo "No category template configured for fraction: $SELECTED_FRACTION"
elif [ -d "$CATEGORY_TEMPLATE_PATH" ]; then
    echo "Checking category folders against template..."
    
    # Get list of expected folders from template
    MISSING_COUNT=0
    CREATED_COUNT=0
    
    for template_dir in "$CATEGORY_TEMPLATE_PATH"/*/ ; do
        if [ -d "$template_dir" ]; then
            category_name=$(basename "$template_dir")
            target_dir="$CAPTURE_DIR/$category_name"
            
            if [ ! -d "$target_dir" ]; then
                echo "  Creating missing folder: $category_name"
                mkdir -p "$target_dir"
                CREATED_COUNT=$((CREATED_COUNT + 1))
            fi
        fi
    done
    
    # Also copy any non-directory files from template (if any)
    for template_file in "$CATEGORY_TEMPLATE_PATH"/* ; do
        if [ -f "$template_file" ]; then
            filename=$(basename "$template_file")
            if [ ! -f "$CAPTURE_DIR/$filename" ]; then
                echo "  Copying template file: $filename"
                cp "$template_file" "$CAPTURE_DIR/"
            fi
        fi
    done
    
    if [ $CREATED_COUNT -eq 0 ]; then
        echo "All expected category folders already exist."
    else
        echo "Created $CREATED_COUNT missing category folder(s)."
    fi
else
    echo "Warning: Category template path not found: $CATEGORY_TEMPLATE_PATH"
fi

# Run check_bulk_download_gaps.py
echo ""
echo -e "${BOLD_GREEN}Step 7: Checking for offline samples not in bulk download...${RESET}"
echo "----------------------------------------"
echo -e "Connecting to $MACHINE...${DARK_GREY}"
"$PYTHON" check_bulk_download_gaps.py \
    --bulk-download-csv "$CSV_OUT" \
    --machine "$MACHINE" \
    --machine-config "$(dirname "$0")/machine_config.yaml" \
    --begin-date "$BEGIN_DATE" \
    --end-date "$END_DATE"
echo -e "${RESET}"
echo ""


# Step 8: Update last_sync in machine config (only after all prior steps succeed)
echo ""
echo -e "${BOLD_GREEN}Step 8: Updating machine last_sync...${RESET}"
echo "----------------------------------------"
update_last_sync "$MACHINE_CONFIG_PATH" "$MACHINE" "$END_DATE"


echo "Categories with downloaded photos:"
echo "----------------------------------------"
# Find all directories in CAPTURE_DIR that contain image files
for category_dir in "$CAPTURE_DIR"/*/ ; do
    if [ -d "$category_dir" ]; then
        # Count image files in the directory
        image_count=$(find "$category_dir" -maxdepth 1 -type f \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) 2>/dev/null | wc -l)
        if [ "$image_count" -gt 0 ]; then
            category_name=$(basename "$category_dir")
            echo "  - $category_name: $image_count images"
        fi
    fi
done

echo ""
echo "=========================================="
echo "All steps completed successfully!"
echo "Capture folder: $CAPTURE_DIR"
if command -v wl-copy >/dev/null 2>&1; then
    printf "%s" "$CAPTURE_DIR" | wl-copy
    echo "Copied capture folder path to clipboard."
elif command -v xclip >/dev/null 2>&1; then
    printf "%s" "$CAPTURE_DIR" | xclip -selection clipboard
    echo "Copied capture folder path to clipboard."
elif command -v xsel >/dev/null 2>&1; then
    printf "%s" "$CAPTURE_DIR" | xsel --clipboard --input
    echo "Copied capture folder path to clipboard."
elif command -v pbcopy >/dev/null 2>&1; then
    printf "%s" "$CAPTURE_DIR" | pbcopy
    echo "Copied capture folder path to clipboard."
else
    echo "Could not copy to clipboard: no clipboard command found."
fi
echo "=========================================="
