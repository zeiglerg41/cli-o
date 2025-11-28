"""Custom autocomplete for @ file mentions."""
from pathlib import Path
from textual_autocomplete import DropdownItem


def get_file_candidates(working_dir: Path, search_text: str) -> list[DropdownItem]:
    """Get file suggestions for autocomplete.

    Args:
        working_dir: Directory to search for files
        search_text: Current input text

    Returns:
        List of DropdownItem for files matching the search
    """
    # Check if we're in @ mention mode
    if '@' not in search_text:
        return []

    # Find the last @ and get text after it
    last_at = search_text.rfind('@')
    after_at = search_text[last_at + 1:]

    # Get the file prefix (text after @ up to first space or end)
    prefix = after_at.split()[0] if ' ' in after_at else after_at

    try:
        # List files in working directory
        items = []
        for item in sorted(working_dir.iterdir()):
            name = item.name

            # Skip hidden files
            if name.startswith('.'):
                continue

            # Filter by prefix (case-insensitive)
            if prefix and not name.lower().startswith(prefix.lower()):
                continue

            # Create dropdown item
            if item.is_dir():
                items.append(DropdownItem(main=f"{name}/", prefix="📁"))
            else:
                items.append(DropdownItem(main=name, prefix="📄"))

        return items[:15]  # Limit to 15 suggestions
    except Exception as e:
        # Return empty list on error
        return []
