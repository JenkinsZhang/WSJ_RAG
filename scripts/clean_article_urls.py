#!/usr/bin/env python
"""
Clean all crawled article URLs by removing query parameters.

Usage:
    python scripts/clean_article_urls.py              # Preview changes
    python scripts/clean_article_urls.py --apply      # Apply changes
"""

import argparse
import json
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.url import normalize_url


def clean_article_urls(articles_dir: Path, apply: bool = False) -> dict:
    """
    Clean URLs in all article JSON files.

    Args:
        articles_dir: Articles directory
        apply: Whether to apply changes

    Returns:
        dict: Statistics
    """
    stats = {
        "total": 0,
        "needs_update": 0,
        "updated": 0,
        "errors": 0,
        "files": [],
    }

    json_files = list(articles_dir.rglob("*.json"))
    stats["total"] = len(json_files)

    print(f"Scanning: {articles_dir}")
    print(f"Found {len(json_files)} JSON files")
    print("-" * 60)

    for filepath in sorted(json_files):
        try:
            # Read file
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check for url field
            if "url" not in data:
                continue

            original_url = data["url"]
            clean_url = normalize_url(original_url)

            # Check if update needed
            if original_url != clean_url:
                stats["needs_update"] += 1
                relative_path = filepath.relative_to(articles_dir)

                if apply:
                    # Update URL
                    data["url"] = clean_url

                    # Write back
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)

                    stats["updated"] += 1
                    print(f"[OK] Updated: {relative_path}")
                else:
                    print(f"  Needs update: {relative_path}")
                    print(f"    Original: {original_url}")
                    print(f"    Cleaned:  {clean_url}")
                    print()

                stats["files"].append({
                    "path": str(relative_path),
                    "original": original_url,
                    "cleaned": clean_url,
                })

        except json.JSONDecodeError as e:
            stats["errors"] += 1
            print(f"[ERROR] JSON error: {filepath} - {e}")
        except Exception as e:
            stats["errors"] += 1
            print(f"[ERROR] {filepath} - {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Clean all article URLs by removing query parameters"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: preview only)",
    )
    parser.add_argument(
        "--articles-dir",
        default="articles",
        help="Articles directory (default: articles)",
    )

    args = parser.parse_args()

    articles_dir = PROJECT_ROOT / args.articles_dir
    if not articles_dir.exists():
        print(f"Error: Directory not found - {articles_dir}")
        sys.exit(1)

    print("=" * 60)
    print("Clean Article URLs" + (" (PREVIEW)" if not args.apply else " (APPLY)"))
    print("=" * 60)
    print()

    stats = clean_article_urls(articles_dir, apply=args.apply)

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Total files:    {stats['total']}")
    print(f"  Needs update:   {stats['needs_update']}")
    if args.apply:
        print(f"  Updated:        {stats['updated']}")
    print(f"  Errors:         {stats['errors']}")
    print()

    if not args.apply and stats["needs_update"] > 0:
        print("Hint: Use --apply to apply changes")
        print("  python scripts/clean_article_urls.py --apply")


if __name__ == "__main__":
    main()
