from collections import Counter
from pathlib import Path

from patchbench.loader import load_cases, load_coverage_matrix
from patchbench.schemas import CaseKind, CoverageArea, Difficulty


def test_bundled_coverage_matrix_matches_case_corpus() -> None:
    root = Path(__file__).parents[1]
    benchmark_cases = {case.case_id: case for case in load_cases(root / "benchmark")}
    matrix = load_coverage_matrix(root / "benchmark" / "coverage.json")
    coverage_cases = {case.case_id: case for case in matrix.cases}

    assert coverage_cases.keys() == benchmark_cases.keys()

    for case_id, coverage in coverage_cases.items():
        expected = benchmark_cases[case_id].expected
        assert coverage.kind is (CaseKind.BUGGY if expected.bug_present else CaseKind.SAFE)
        assert coverage.expected_finding == expected.category


def test_bundled_coverage_counts_and_targets_are_explicit() -> None:
    root = Path(__file__).parents[1]
    matrix = load_coverage_matrix(root / "benchmark" / "coverage.json")

    area_counts = Counter(case.coverage_area for case in matrix.cases)
    difficulty_counts = Counter(case.difficulty for case in matrix.cases)
    safe_count = sum(case.kind is CaseKind.SAFE for case in matrix.cases)

    assert area_counts == {
        CoverageArea.LOGIC: 4,
        CoverageArea.VALIDATION: 1,
        CoverageArea.SECURITY: 12,
        CoverageArea.RESOURCES: 4,
        CoverageArea.BOUNDARIES: 3,
    }
    assert difficulty_counts == {
        Difficulty.EASY: 10,
        Difficulty.MEDIUM: 12,
        Difficulty.HARD: 2,
    }
    assert safe_count == 12 == len(matrix.cases) // 2

    assert matrix.targets.total_cases == 30
    assert matrix.targets.safe_cases == 15
    assert all(
        area_counts[area] <= target for area, target in matrix.targets.coverage_areas.items()
    )
    assert all(
        difficulty_counts[difficulty] <= target
        for difficulty, target in matrix.targets.difficulty.items()
    )
