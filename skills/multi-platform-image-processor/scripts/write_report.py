from __future__ import annotations

from pathlib import Path

from common import finalize_report_summary, write_json


def write_report(report: dict, path: Path) -> None:
    finalize_report_summary(report)
    write_json(path, report)
