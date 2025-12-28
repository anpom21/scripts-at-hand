#!/bin/bash

# Script to sync and sort images from a machine
# Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <suffix>]

set -e  # Exit on error

# Color codes
BOLD_GREEN='\033[1;32m'
DARK_GREY='\033[1;30m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'



# Default collection base path
COLLECTION_BASE="/home/simon/Data/Collections_wood"
SUFFIX=""

# Parse command line arguments
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
            shift 2
            ;;
        --suffix)
            SUFFIX="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <capture dir name suffix>]"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$MACHINE" ] || [ -z "$BEGIN_DATE" ] || [ -z "$END_DATE" ]; then
    echo "Error: Missing required arguments (--machine, --begin-date, --end-date)"
    echo "Usage: bash sync_and_sort_images.sh --machine <machine> --begin-date <date> --end-date <date> [--capture-dir <dir>] [--collection-base <path>] [--suffix <suffix>]"
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
python3 scripts/sync_image_files.py \
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
python3 scripts/sync_image_files.py \
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
python3 scripts/build_inference_records.py \
    --unit "$MACHINE" \
    --local-dir "$CAPTURE_DIR" \
    --csv-out "$CSV_OUT"
echo -e "${RESET}"

# Step 4: Sort images from insights (dry run)
echo ""
echo -e "${BOLD_GREEN}Step 4: Sorting images from insights (dry run)...${RESET}"
echo "----------------------------------------"
echo -e "${DARK_GREY}"
python3 sort_images_from_insights.py \
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
python3 sort_images_from_insights.py \
    --images-dir "$CAPTURE_DIR" \
    --run \
    --csv "$CSV_OUT"
echo -e "${RESET}"

# Step 6: Copy category template folders
echo ""
echo -e "${BOLD_GREEN}Step 6: Ensuring all category folders exist...${RESET}"
echo "----------------------------------------"
CATEGORY_TEMPLATE_PATH="/home/simon/Data/category_templates/wood"
if [ -d "$CATEGORY_TEMPLATE_PATH" ]; then
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

echo ""
echo "=========================================="
echo "All steps completed successfully!"
echo "=========================================="
echo ""
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
echo "=========================================="
