#!/usr/bin/env python3
"""Quick test to verify source tag search functionality."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils import load_config, build_script_index
from search import score_match

# Load config
root = Path(__file__).parent
config = load_config(root)
entries = build_script_index(root, config)

# Test 1: Find scripts from "Annotation" source
print("=" * 70)
print("Test 1: Searching for 'annotation' (should match Annotation source)")
print("=" * 70)

query = "annotation"
matches = []
for e in entries:
    tags = getattr(e, "tags", []) or []
    source = getattr(e, "source", "local")
    if query.lower() in e.name.lower() or \
       query.lower() in (e.description or "").lower() or \
       any(query.lower() in tag.lower() for tag in tags) or \
       (source != "local" and query.lower() in source.lower()):
        matches.append(e)

print(f"\nFound {len(matches)} matches:")
for e in matches:
    source = getattr(e, "source", "local")
    tags = getattr(e, "tags", []) or []
    print(f"  - {e.name}")
    print(f"    source: {source}")
    if tags:
        print(f"    tags: {tags}")
    score = score_match(e.name, e.description or "", tags, source, query)
    print(f"    score: {score}")

# Test 2: Find scripts from "Classification" source
print("\n" + "=" * 70)
print("Test 2: Searching for 'classification' (should match Classification source)")
print("=" * 70)

query = "classification"
matches = []
for e in entries:
    tags = getattr(e, "tags", []) or []
    source = getattr(e, "source", "local")
    if query.lower() in e.name.lower() or \
       query.lower() in (e.description or "").lower() or \
       any(query.lower() in tag.lower() for tag in tags) or \
       (source != "local" and query.lower() in source.lower()):
        matches.append(e)

print(f"\nFound {len(matches)} matches:")
for e in matches:
    source = getattr(e, "source", "local")
    tags = getattr(e, "tags", []) or []
    print(f"  - {e.name}")
    print(f"    source: {source}")
    if tags:
        print(f"    tags: {tags}")
    score = score_match(e.name, e.description or "", tags, source, query)
    print(f"    score: {score}")

print("\n✓ Tests completed!")
