import json
from pathlib import Path

from patchbench.diffs import added_lines_by_file, validate_patch_location
from patchbench.schemas import BenchmarkCase, ExpectedFinding


def load_cases(benchmark_dir: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for expected_path in sorted(benchmark_dir.glob("*/expected.json")):
        case_dir = expected_path.parent
        patch_path = case_dir / "patch.diff"
        if not patch_path.exists():
            raise FileNotFoundError(f"Missing patch for {case_dir.name}: {patch_path}")
        expected = ExpectedFinding.model_validate_json(expected_path.read_text())
        patch = patch_path.read_text()
        additions = added_lines_by_file(patch)
        if not additions:
            raise ValueError(f"Case {case_dir.name} patch has no unified diff hunks")
        if expected.bug_present:
            # ExpectedFinding guarantees these values for positive cases.
            validate_patch_location(
                patch,
                case_id=case_dir.name,
                expected_file=expected.file or "",
                expected_line=expected.line or 0,
            )
        cases.append(
            BenchmarkCase(case_id=case_dir.name, patch_path=patch_path, expected=expected)
        )
    if not cases:
        raise ValueError(f"No benchmark cases found in {benchmark_dir}")
    return cases


def load_predictions(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError("Predictions must be a JSON object keyed by case ID")
    return payload
