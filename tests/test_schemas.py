import pytest
from pydantic import ValidationError

from patchbench.schemas import ExpectedFinding


def test_safe_case_rejects_bug_location_details() -> None:
    with pytest.raises(ValidationError, match="Safe cases cannot specify"):
        ExpectedFinding(
            bug_present=False,
            category="possible_bug",
            file="module.py",
            line=1,
            explanation="Marked safe but still has finding details.",
        )
