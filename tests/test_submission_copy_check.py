from pathlib import Path

from options_alpha_agent.submission_check import run_submission_checks


def _write_submission_copy(root: Path, *, short: str = "A short description.") -> None:
    path = root / "docs/submission-copy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    long_description = " ".join(["This is a sufficiently detailed project description."] * 25)
    path.write_text(
        "\n".join(
            [
                "# Submission Copy Draft",
                "",
                "## Project title",
                "",
                "**Options Alpha**",
                "",
                "## Short description",
                "",
                short,
                "",
                "## Long description",
                "",
                long_description,
                "",
                "## Build-in-public drafts",
                "",
                "1. **One:** Draft post.",
                "2. **Two:** Draft post.",
            ]
        ),
        encoding="utf-8",
    )


def test_submission_copy_constraints_are_reported(tmp_path: Path) -> None:
    _write_submission_copy(tmp_path)

    checks = {check.name: check for check in run_submission_checks(tmp_path)}

    assert checks["title length"].status == "ok"
    assert checks["short description length"].status == "ok"
    assert checks["long description length"].status == "ok"
    assert checks["build-in-public post count"].status == "ok"


def test_submission_copy_rejects_long_short_description(tmp_path: Path) -> None:
    _write_submission_copy(tmp_path, short="x" * 256)

    checks = {check.name: check for check in run_submission_checks(tmp_path)}

    assert checks["short description length"].status == "invalid"
