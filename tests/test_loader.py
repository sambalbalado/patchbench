import json
from pathlib import Path

import pytest

from patchbench.loader import load_cases


def write_case(
    root: Path,
    *,
    expected_file: str = "module.py",
    expected_line: int = 2,
    patch: str | None = None,
) -> None:
    case_dir = root / "example"
    case_dir.mkdir()
    (case_dir / "expected.json").write_text(
        json.dumps(
            {
                "bug_present": True,
                "category": "incorrect_return",
                "file": expected_file,
                "line": expected_line,
                "explanation": "The return value changed.",
            }
        )
    )
    (case_dir / "patch.diff").write_text(
        patch
        or """diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -2 +2 @@
-    return True
+    return False
"""
    )


def test_rejects_expected_file_not_changed_by_patch(tmp_path: Path) -> None:
    write_case(tmp_path, expected_file="other.py")

    with pytest.raises(ValueError, match="expects file 'other.py'"):
        load_cases(tmp_path)


def test_rejects_expected_line_not_added_by_patch(tmp_path: Path) -> None:
    write_case(tmp_path, expected_line=3)

    with pytest.raises(ValueError, match="module.py:3"):
        load_cases(tmp_path)


def test_rejects_patch_without_unified_diff_hunks(tmp_path: Path) -> None:
    write_case(tmp_path, patch="diff --git a/module.py b/module.py\n")

    with pytest.raises(ValueError, match="has no unified diff hunks"):
        load_cases(tmp_path)


def test_rejects_hunk_with_incorrect_line_counts(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        patch="""diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -2,2 +2,2 @@
-    return True
+    return False
""",
    )

    with pytest.raises(ValueError, match="declared line counts"):
        load_cases(tmp_path)


def test_bundled_benchmark_is_balanced_and_diverse() -> None:
    root = Path(__file__).parents[1]
    cases = load_cases(root / "benchmark")
    bug_cases = [case for case in cases if case.expected.bug_present]
    safe_cases = [case for case in cases if not case.expected.bug_present]

    assert len(cases) == 24
    assert len(bug_cases) == len(safe_cases) == 12
    assert len({case.expected.category for case in bug_cases}) == 12
