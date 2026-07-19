"""Reproducibility metadata for classification jobs."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import subprocess
from typing import Any

from .ollama import citation_prompt_templates, list_models, person_facet_prompt_template


def new_classification_job(
    *,
    command: str,
    classifier_mode: str,
    ollama_model: str | None,
    ollama_host: str,
    ollama_timeout: float,
    ollama_think: bool,
    ollama_think_on_review: bool = False,
    include_categories: bool,
    include_person_facets: bool,
) -> dict[str, Any]:
    """Create immutable, job-level metadata before a classification run."""
    prompts: dict[str, object] = {}
    if include_categories:
        prompts["citation_category"] = citation_prompt_templates()
    if include_person_facets:
        prompts["person_facet"] = person_facet_prompt_template()

    resolved_model = ollama_model
    if classifier_mode != "rules" and not resolved_model:
        models = list_models(host=ollama_host)
        resolved_model = models[0] if models else None
    commit, dirty = _git_revision()
    started_at = _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="microseconds")
    prompts_json = json.dumps(prompts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = {
        "command": command,
        "started_at": started_at,
        "classifier_mode": classifier_mode,
        "ollama_model": resolved_model,
        "ollama_host": ollama_host,
        "ollama_timeout": ollama_timeout,
        "ollama_think": bool(ollama_think),
        "ollama_think_on_review": bool(ollama_think_on_review),
        "code_commit": commit,
        "worktree_dirty": dirty,
        "prompts_json": prompts_json,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["job_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload["prompt_sha256"] = hashlib.sha256(prompts_json.encode("utf-8")).hexdigest()
    return payload


def _git_revision() -> tuple[str | None, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, stdout=subprocess.PIPE, text=True,
            stderr=subprocess.DEVNULL,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], check=True, stdout=subprocess.PIPE, text=True,
                stderr=subprocess.DEVNULL,
            ).stdout.strip()
        )
        return commit or None, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False
