"""Local, non-publishing final-submission artifact checks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SubmissionCheck:
    name: str
    path: str
    required: bool
    status: str
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        return None
    return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")


def _looks_like_mp4(path: Path) -> bool:
    """Check the ISO Base Media File Type box without decoding the video."""

    try:
        with path.open("rb") as stream:
            header = stream.read(64)
    except OSError:
        return False
    return len(header) >= 12 and header[4:8] == b"ftyp"


def _markdown_section(text: str, heading: str) -> str | None:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _normalized_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text)


def _submission_copy_checks(root: Path) -> list[SubmissionCheck]:
    """Validate organizer-facing copy constraints without requiring external URLs."""

    relative = "docs/submission-copy.md"
    path = root / relative
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [
            SubmissionCheck("submission copy format", relative, True, "invalid", "cannot read file")
        ]

    title_section = _markdown_section(text, "Project title")
    short_section = _markdown_section(text, "Short description")
    long_section = _markdown_section(text, "Long description")
    post_section = _markdown_section(text, "Build-in-public drafts")
    checks: list[SubmissionCheck] = []

    title_match = re.search(r"\*\*(.+?)\*\*", title_section or "")
    title = title_match.group(1).strip() if title_match else ""
    if not title:
        checks.append(
            SubmissionCheck("title length", relative, True, "invalid", "project title not found")
        )
    elif len(title) <= 50:
        checks.append(
            SubmissionCheck("title length", relative, True, "ok", f"{len(title)} characters")
        )
    else:
        checks.append(
            SubmissionCheck(
                "title length", relative, True, "invalid", f"{len(title)} characters; maximum is 50"
            )
        )

    short_text = " ".join((short_section or "").split())
    if short_text and len(short_text) <= 255:
        checks.append(
            SubmissionCheck(
                "short description length", relative, True, "ok", f"{len(short_text)} characters"
            )
        )
    else:
        checks.append(
            SubmissionCheck(
                "short description length",
                relative,
                True,
                "invalid",
                f"{len(short_text)} characters; maximum is 255",
            )
        )

    long_words = _normalized_words(long_section or "")
    if len(long_words) >= 100:
        checks.append(
            SubmissionCheck(
                "long description length", relative, True, "ok", f"{len(long_words)} words"
            )
        )
    else:
        checks.append(
            SubmissionCheck(
                "long description length",
                relative,
                True,
                "invalid",
                f"{len(long_words)} words; minimum is 100",
            )
        )

    post_count = len(re.findall(r"^\d+\.\s+\*\*", post_section or "", flags=re.MULTILINE))
    if 1 <= post_count <= 5:
        checks.append(
            SubmissionCheck(
                "build-in-public post count", relative, True, "ok", f"{post_count} drafts"
            )
        )
    else:
        checks.append(
            SubmissionCheck(
                "build-in-public post count",
                relative,
                True,
                "invalid",
                f"{post_count} drafts; maximum is 5",
            )
        )
    return checks


def _file_check(
    root: Path, name: str, relative_path: str, *, required: bool = True
) -> SubmissionCheck:
    path = root / relative_path
    if not path.is_file():
        return SubmissionCheck(name, relative_path, required, "missing", "file not found")
    if path.stat().st_size == 0:
        return SubmissionCheck(name, relative_path, required, "invalid", "file is empty")
    return SubmissionCheck(name, relative_path, required, "ok", "file exists")


def run_submission_checks(root: str | Path = ".") -> list[SubmissionCheck]:
    """Check local artifacts without uploading, publishing, or reading `.env`."""

    workspace = Path(root)
    checks = [
        _file_check(workspace, "MIT license", "LICENSE"),
        _file_check(workspace, "submission copy", "docs/submission-copy.md"),
        _file_check(workspace, "one-page write-up", "docs/one-page-writeup.md"),
        _file_check(
            workspace,
            "one-page PDF",
            "output/pdf/options-alpha-one-page.pdf",
        ),
        _file_check(workspace, "compliance matrix", "docs/compliance-matrix.md"),
        _file_check(workspace, "demo script", "docs/demo-script.md"),
        _file_check(workspace, "worker container", "Dockerfile.worker"),
        _file_check(workspace, "cover PNG", "submission/cover.png"),
        _file_check(
            workspace,
            "slide PDF",
            "submission/options-alpha-slides.pdf",
        ),
        _file_check(workspace, "demo MP4", "submission/demo.mp4"),
    ]
    checks.extend(_submission_copy_checks(workspace))
    cover = workspace / "submission/cover.png"
    dimensions = _png_dimensions(cover) if cover.is_file() else None
    if dimensions != (1600, 900):
        checks = [
            (
                SubmissionCheck(
                    "cover PNG",
                    "submission/cover.png",
                    True,
                    "invalid",
                    f"expected 1600x900, got {dimensions}",
                )
                if check.name == "cover PNG"
                else check
            )
            for check in checks
        ]
    else:
        checks = [
            (
                SubmissionCheck(
                    "cover PNG",
                    "submission/cover.png",
                    True,
                    "ok",
                    "1600x900",
                )
                if check.name == "cover PNG"
                else check
            )
            for check in checks
        ]

    demo = workspace / "submission/demo.mp4"
    if demo.is_file() and (not _looks_like_mp4(demo) or demo.stat().st_size > 300 * 1024 * 1024):
        detail = (
            "missing ISO Base Media ftyp signature"
            if not _looks_like_mp4(demo)
            else "file exceeds the 300 MB submission limit"
        )
        checks = [
            (
                SubmissionCheck(
                    "demo MP4",
                    "submission/demo.mp4",
                    True,
                    "invalid",
                    detail,
                )
                if check.name == "demo MP4"
                else check
            )
            for check in checks
        ]
    elif demo.is_file():
        size_mb = demo.stat().st_size / (1024 * 1024)
        checks = [
            (
                SubmissionCheck(
                    "demo MP4",
                    "submission/demo.mp4",
                    True,
                    "ok",
                    f"ISO Base Media container; {size_mb:.1f} MB",
                )
                if check.name == "demo MP4"
                else check
            )
            for check in checks
        ]

    sensitive_pattern = re.compile(
        r"(?:sk-[A-Za-z0-9]{20,}|"
        r"(?:ALPACA|FEATHERLESS|OPENAI)_(?:API|SECRET)_KEY="
        r"(?![\"'\s]|$|\[\^)[^\s]+)"
    )
    sensitive_hits: list[str] = []
    for relative in ("README.md", "docs", "src", "submission", "scripts", "data", ".github"):
        candidate = workspace / relative
        paths = [candidate] if candidate.is_file() else candidate.rglob("*")
        for path in paths:
            if not path.is_file() or path.name == ".env":
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            try:
                if sensitive_pattern.search(path.read_text(encoding="utf-8")):
                    sensitive_hits.append(path.as_posix())
            except (OSError, UnicodeDecodeError):
                continue
    checks.append(
        SubmissionCheck(
            "secret pattern scan",
            "README.md, docs/, src/, submission/, scripts/, data/, .github/",
            True,
            "invalid" if sensitive_hits else "ok",
            "matched files are not included" if sensitive_hits else "no secret-like values found",
        )
    )
    return checks


def submission_report(root: str | Path = ".") -> dict[str, Any]:
    checks = run_submission_checks(root)
    required_failures = [check for check in checks if check.required and check.status != "ok"]
    optional_pending = [check for check in checks if not check.required and check.status != "ok"]
    return {
        "status": "ready" if not required_failures else "blocked",
        "required_failures": [check.public_dict() for check in required_failures],
        "optional_pending": [check.public_dict() for check in optional_pending],
        "checks": [check.public_dict() for check in checks],
    }
