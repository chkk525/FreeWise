"""Background watcher that auto-imports Kindle scraper output files.

The Kindle scraper (in the separate `freewise-qnap-deploy/feat/kindle-scraper`
worktree) writes timestamped JSON files into a shared directory on QNAP. This
module scans that directory at configurable intervals and runs each new file
through :func:`app.importers.kindle_notebook.import_kindle_notebook_json`,
moving processed files into a sibling ``processed/`` subdirectory so we never
re-import them.

Disabled by default. Enabled by setting ``KINDLE_IMPORTS_DIR`` to a path that
exists. The default scan interval is 15 minutes.

The caller owns the SQLModel session lifecycle. We commit per file so a bad
file at position N does not roll back files 0..N-1, but we never close the
caller's session.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from app.importers.kindle_notebook import (
    KindleImportResult,
    import_kindle_notebook_json,
)
from app.services.notifier import notify


logger = logging.getLogger(__name__)


KINDLE_IMPORTS_DIR_ENV = "KINDLE_IMPORTS_DIR"
KINDLE_IMPORT_INTERVAL_ENV = "KINDLE_IMPORT_INTERVAL_SECONDS"
KINDLE_IMPORT_USER_ID_ENV = "KINDLE_IMPORT_USER_ID"
DEFAULT_INTERVAL_SECONDS = 15 * 60


@dataclass(frozen=True)
class ScanResult:
    """Aggregate outcome of one scan_and_import call."""

    files_scanned: int
    files_imported: int
    files_failed: int
    books_created: int
    books_matched: int
    highlights_created: int
    highlights_skipped_duplicates: int
    errors: tuple[str, ...] = field(default_factory=tuple)


def scan_and_import(
    *,
    imports_dir: Path,
    session: Session,
    user_id: int = 1,
    log: logging.Logger | None = None,
) -> ScanResult:
    """Process every unprocessed ``*.json`` under ``imports_dir`` once."""

    log = log or logger
    if not imports_dir.exists() or not imports_dir.is_dir():
        log.debug("imports_dir does not exist: %s", imports_dir)
        return _empty_result()

    processed_dir = imports_dir / "processed"
    processed_dir.mkdir(exist_ok=True)

    candidates = sorted(
        (
            p
            for p in imports_dir.glob("*.json")
            if p.is_file() and not p.is_symlink()
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        return _empty_result()

    log.info("scanning %d Kindle JSON file(s) in %s", len(candidates), imports_dir)

    files_imported = 0
    files_failed = 0
    books_created = 0
    books_matched = 0
    highlights_created = 0
    highlights_skipped = 0
    errors: list[str] = []

    for path in candidates:
        try:
            result = _import_one_file(path, session=session, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            files_failed += 1
            errors.append(f"{path.name}: {exc}")
            log.exception("Kindle import FAILED for %s", path.name)
            continue

        files_imported += 1
        books_created += result.books_created
        books_matched += result.books_matched
        highlights_created += result.highlights_created
        highlights_skipped += result.highlights_skipped_duplicates
        errors.extend(
            f"{path.name}: {e['book_title']}: {e['reason']}"
            for e in result.errors
        )

        target = processed_dir / path.name
        if target.exists():
            target = processed_dir / _stamp_name(path.name)
        shutil.move(str(path), str(target))
        log.info(
            "Kindle imported %s: %d books (%d new, %d matched), %d highlights "
            "(%d skipped duplicates) -> %s",
            path.name,
            result.books_created + result.books_matched,
            result.books_created,
            result.books_matched,
            result.highlights_created,
            result.highlights_skipped_duplicates,
            target,
        )

    result = ScanResult(
        files_scanned=len(candidates),
        files_imported=files_imported,
        files_failed=files_failed,
        books_created=books_created,
        books_matched=books_matched,
        highlights_created=highlights_created,
        highlights_skipped_duplicates=highlights_skipped,
        errors=tuple(errors),
    )
    _maybe_notify(result)
    return result


def _maybe_notify(result: ScanResult) -> None:
    """Fire a webhook iff something actually happened. Skips silent ticks."""
    if result.files_imported == 0 and result.files_failed == 0:
        return
    if result.files_failed > 0:
        msg = (
            f"imported {result.files_imported}/{result.files_scanned} kindle files, "
            f"{result.files_failed} failed; "
            f"books={result.books_created}+{result.books_matched} new+matched, "
            f"highlights={result.highlights_created}"
        )
        notify(
            "failure",
            msg,
            extra={
                "files_imported": result.files_imported,
                "files_failed": result.files_failed,
                "files_scanned": result.files_scanned,
                "books_created": result.books_created,
                "highlights_created": result.highlights_created,
                "errors": list(result.errors)[:5],
            },
        )
    else:
        msg = (
            f"imported {result.files_imported} kindle file(s): "
            f"{result.books_created} new books, {result.books_matched} matched, "
            f"{result.highlights_created} highlights"
        )
        notify(
            "success",
            msg,
            extra={
                "files_imported": result.files_imported,
                "books_created": result.books_created,
                "books_matched": result.books_matched,
                "highlights_created": result.highlights_created,
            },
        )


def _import_one_file(
    path: Path,
    *,
    session: Session,
    user_id: int,
) -> KindleImportResult:
    with path.open("rb") as fh:
        result = import_kindle_notebook_json(fh, session, user_id=user_id)
    session.commit()
    return result


def _empty_result() -> ScanResult:
    return ScanResult(
        files_scanned=0,
        files_imported=0,
        files_failed=0,
        books_created=0,
        books_matched=0,
        highlights_created=0,
        highlights_skipped_duplicates=0,
        errors=(),
    )


def _stamp_name(name: str) -> str:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem, _, suffix = name.rpartition(".")
    if not stem:
        return f"{name}.{stamp}"
    return f"{stem}.{stamp}.{suffix}"


def imports_dir_from_env() -> Path | None:
    raw = os.environ.get(KINDLE_IMPORTS_DIR_ENV)
    if not raw:
        return None
    return Path(raw)


def interval_seconds_from_env() -> int:
    raw = os.environ.get(KINDLE_IMPORT_INTERVAL_ENV)
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        n = int(raw)
        if n < 60:
            logger.warning(
                "KINDLE_IMPORT_INTERVAL_SECONDS=%s is below 60s; raising to 60", n
            )
            return 60
        return n
    except ValueError:
        logger.warning(
            "ignoring invalid KINDLE_IMPORT_INTERVAL_SECONDS=%r; using default", raw
        )
        return DEFAULT_INTERVAL_SECONDS


def user_id_from_env() -> int:
    raw = os.environ.get(KINDLE_IMPORT_USER_ID_ENV)
    if not raw:
        return 1
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring invalid KINDLE_IMPORT_USER_ID=%r; using 1", raw)
        return 1
