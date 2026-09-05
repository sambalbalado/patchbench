import re
from collections import defaultdict

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _line_count(value: str | None) -> int:
    return int(value) if value is not None else 1


def added_lines_by_file(patch: str) -> dict[str, set[int]]:
    """Return the new-file line numbers added by a unified diff."""
    additions: defaultdict[str, set[int]] = defaultdict(set)
    current_file: str | None = None
    new_line: int | None = None
    old_remaining = new_remaining = 0

    for raw_line in patch.splitlines():
        if raw_line.startswith("+++ "):
            if old_remaining or new_remaining:
                raise ValueError("Unified diff hunk ended before its declared line counts")
            target = raw_line[4:].split("\t", 1)[0]
            current_file = target.removeprefix("b/")
            new_line = None
            continue

        header = HUNK_HEADER.match(raw_line)
        if header:
            if old_remaining or new_remaining:
                raise ValueError("Unified diff hunk ended before its declared line counts")
            if current_file is None:
                raise ValueError("Hunk found before a new-file header")
            old_remaining = _line_count(header.group(1))
            new_line = int(header.group(2))
            new_remaining = _line_count(header.group(3))
            additions.setdefault(current_file, set())
            continue

        if current_file is None or new_line is None:
            continue
        if raw_line.startswith("+"):
            additions[current_file].add(new_line)
            new_line += 1
            new_remaining -= 1
        elif raw_line.startswith("-"):
            old_remaining -= 1
        elif raw_line.startswith("\\"):
            continue
        elif raw_line.startswith(" "):
            new_line += 1
            old_remaining -= 1
            new_remaining -= 1
        else:
            raise ValueError("Unexpected line inside unified diff hunk")

        if old_remaining < 0 or new_remaining < 0:
            raise ValueError("Unified diff hunk exceeds its declared line counts")
        if old_remaining == new_remaining == 0:
            new_line = None

    if old_remaining or new_remaining:
        raise ValueError("Unified diff hunk ended before its declared line counts")
    return dict(additions)


def validate_patch_location(
    patch: str, *, case_id: str, expected_file: str, expected_line: int
) -> None:
    """Ensure a bug label points at an added line in the named file."""
    additions = added_lines_by_file(patch)
    if not additions:
        raise ValueError(f"Case {case_id} patch has no added lines")
    if expected_file not in additions:
        available = ", ".join(sorted(additions)) or "none"
        raise ValueError(
            f"Case {case_id} expects file {expected_file!r}, but added lines are in: {available}"
        )
    if expected_line not in additions[expected_file]:
        raise ValueError(
            f"Case {case_id} expects {expected_file}:{expected_line}, "
            "but that line is not added by the patch"
        )
