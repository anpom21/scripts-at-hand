#!/usr/bin/env bash
# Helper function for aris search that puts the result in readline buffer
# Add this to your ~/.bashrc:
#   source /path/to/aris_scripts/src/search_helper.sh

aris-search() {
    local result
    # Run search and capture output to temp file
    local tmp_file="/tmp/.aris_search_$$"
    aris search 2>&1 | tee "$tmp_file"
    
    # Extract the command from output (look for "aris <script>")
    local cmd=$(grep "^aris " "$tmp_file" | tail -1)
    
    # Clean up
    rm -f "$tmp_file"
    
    # If we found a command, put it in readline buffer
    if [[ -n "$cmd" ]]; then
        # Use readline to pre-populate the command line
        bind '"\e[0n": "'"$cmd"'"'
        bind '"\e[0n"'
        echo ""
        echo "Command ready: $cmd"
        echo "Press UP arrow or type it manually"
    fi
}
