# -*- coding: utf-8 -*-
"""Conservative manual GameBanana update matching."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateCandidate:
    kind: str
    installed_file_id: int
    remote_file: object = None


def _normalize(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def check_file(installed, details):
    """Return an update result without guessing across unrelated branches."""
    if details.unavailable_reason:
        return UpdateCandidate("source_unavailable", installed.file_id)
    active = list(details.files)
    archived = list(details.archived_files)
    exact = next((item for item in active + archived if item.id == installed.file_id), None)
    if exact and not exact.archived:
        same_digest = installed.md5 and exact.md5 and installed.md5.casefold() == exact.md5.casefold()
        same_identity = exact.name == installed.file_name and exact.date_added == installed.date_added
        return UpdateCandidate("up_to_date" if same_digest or (not installed.md5 and same_identity) else "review", installed.file_id, exact)
    label = _normalize(installed.description)
    candidates = [item for item in active if item.date_added > installed.date_added and label and _normalize(item.description) == label]
    if len(candidates) == 1:
        return UpdateCandidate("update_available", installed.file_id, candidates[0])
    if len(candidates) > 1:
        return UpdateCandidate("ambiguous", installed.file_id)
    if exact:
        return UpdateCandidate("file_removed", installed.file_id)
    return UpdateCandidate("file_removed", installed.file_id)
