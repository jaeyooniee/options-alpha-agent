from pathlib import Path

from options_alpha_agent.submission_check import run_submission_checks


def _write_required_files(root: Path) -> None:
    for relative in (
        "LICENSE",
        "docs/submission-copy.md",
        "docs/one-page-writeup.md",
        "output/pdf/options-alpha-one-page.pdf",
        "docs/compliance-matrix.md",
        "docs/demo-script.md",
        "Dockerfile.worker",
        "submission/options-alpha-slides.pdf",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("safe", encoding="utf-8")


def _write_cover(root: Path) -> None:
    cover = root / "submission/cover.png"
    cover.parent.mkdir(parents=True, exist_ok=True)
    header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR"
    cover.write_bytes(header + (1600).to_bytes(4, "big") + (900).to_bytes(4, "big"))


def test_submission_check_rejects_non_mp4_placeholder(tmp_path: Path) -> None:
    _write_required_files(tmp_path)
    _write_cover(tmp_path)
    demo = tmp_path / "submission/demo.mp4"
    demo.write_bytes(b"this is not an mp4")

    checks = {check.name: check for check in run_submission_checks(tmp_path)}

    assert checks["demo MP4"].status == "invalid"
    assert "ftyp" in checks["demo MP4"].detail


def test_submission_check_accepts_mp4_container_signature(tmp_path: Path) -> None:
    _write_required_files(tmp_path)
    _write_cover(tmp_path)
    demo = tmp_path / "submission/demo.mp4"
    demo.write_bytes((24).to_bytes(4, "big") + b"ftypisom" + b"\x00" * 16)

    checks = {check.name: check for check in run_submission_checks(tmp_path)}

    assert checks["demo MP4"].status == "ok"


def test_submission_check_rejects_nonempty_api_key_assignment(tmp_path: Path) -> None:
    _write_required_files(tmp_path)
    _write_cover(tmp_path)
    demo = tmp_path / "submission/demo.mp4"
    demo.write_bytes((24).to_bytes(4, "big") + b"ftypisom" + b"\x00" * 16)
    script = tmp_path / "scripts/example.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("ALPACA_API_KEY=not-a-real-key", encoding="utf-8")

    checks = {check.name: check for check in run_submission_checks(tmp_path)}

    assert checks["secret pattern scan"].status == "invalid"
