"""
GitHub Diff Fetcher

Fetches actual code diffs for commits from GitHub API.
Used by investigation agent to analyze real code changes
instead of just filename + commit message.

Returns truncated, token-aware diffs suitable for Nova context.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Max characters of diff to pass to Nova — keeps us under token limits
# ~8000 chars ≈ ~2000 tokens, leaves plenty of room in Nova's context
MAX_DIFF_CHARS = 8000
MAX_LINES_PER_FILE = 150


def fetch_commit_diff(
    repo_id: str,
    commit_sha: str,
    github_token: str,
) -> Optional[str]:
    """
    Fetch the full diff for a single commit from GitHub API.
    Returns truncated unified diff string, or None on failure.

    Args:
        repo_id:      "owner/repo" e.g. "HimJar911/payments-service"
        commit_sha:   Full or short SHA
        github_token: GitHub PAT with repo read scope
    """
    url = f"https://api.github.com/repos/{repo_id}/commits/{commit_sha}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3.diff",
                "User-Agent": "IncidentIQ/2.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_diff = resp.read().decode("utf-8", errors="replace")

        logger.info(
            f"[diff_fetcher] Fetched diff for {commit_sha[:8]}: "
            f"{len(raw_diff)} chars across "
            f"{raw_diff.count('diff --git')} files"
        )

        return _truncate_diff(raw_diff)

    except urllib.error.HTTPError as e:
        logger.error(
            f"[diff_fetcher] HTTP {e.code} fetching diff for {commit_sha}: {e.read().decode()}"
        )
        return None
    except Exception as e:
        logger.error(f"[diff_fetcher] Failed to fetch diff for {commit_sha}: {e}")
        return None


def fetch_compare_diff(
    repo_id: str,
    base_sha: str,
    head_sha: str,
    github_token: str,
) -> Optional[str]:
    """
    Fetch diff between two commits (useful for multi-commit pushes).
    Returns truncated unified diff string, or None on failure.
    """
    url = f"https://api.github.com/repos/{repo_id}/compare/{base_sha}...{head_sha}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3.diff",
                "User-Agent": "IncidentIQ/2.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_diff = resp.read().decode("utf-8", errors="replace")

        logger.info(
            f"[diff_fetcher] Fetched compare diff {base_sha[:8]}...{head_sha[:8]}: "
            f"{len(raw_diff)} chars"
        )

        return _truncate_diff(raw_diff)

    except Exception as e:
        logger.error(f"[diff_fetcher] Failed to fetch compare diff: {e}")
        return None


def _truncate_diff(raw_diff: str) -> str:
    """
    Intelligently truncate a diff to fit in Nova's context window.

    Strategy:
    1. Split into per-file sections
    2. Prioritize files by risk score (payment/auth/config > tests > docs)
    3. Truncate individual files that are too long
    4. Cap total at MAX_DIFF_CHARS

    Returns clean, readable diff string.
    """
    if not raw_diff:
        return ""

    # Split into per-file sections
    file_sections = _split_diff_by_file(raw_diff)

    if not file_sections:
        return raw_diff[:MAX_DIFF_CHARS]

    # Score and sort by risk
    scored = sorted(file_sections, key=lambda x: _file_risk_score(x[0]), reverse=True)

    result_parts = []
    total_chars = 0

    for filename, diff_content in scored:
        # Truncate individual file diffs
        truncated_content = _truncate_file_diff(diff_content)

        section = f"--- {filename} ---\n{truncated_content}\n"

        if total_chars + len(section) > MAX_DIFF_CHARS:
            remaining = MAX_DIFF_CHARS - total_chars
            if remaining > 200:  # Only add if there's meaningful space left
                result_parts.append(section[:remaining] + "\n[... truncated ...]")
            break

        result_parts.append(section)
        total_chars += len(section)

    result = "\n".join(result_parts)

    if len(raw_diff) > MAX_DIFF_CHARS:
        result += f"\n\n[Diff truncated — showed {len(result_parts)} of {len(file_sections)} files]"

    return result


def _split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    """Split a unified diff into (filename, content) pairs."""
    sections = []
    current_file = None
    current_lines = []

    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            if current_file and current_lines:
                sections.append((current_file, "\n".join(current_lines)))
            # Extract filename: "diff --git a/foo.py b/foo.py" → "foo.py"
            match = re.search(r"diff --git a/(.+) b/", line)
            current_file = match.group(1) if match else "unknown"
            current_lines = [line]
        elif current_file is not None:
            current_lines.append(line)

    if current_file and current_lines:
        sections.append((current_file, "\n".join(current_lines)))

    return sections


def _truncate_file_diff(diff_content: str) -> str:
    """
    Truncate a single file's diff to MAX_LINES_PER_FILE lines.
    Keeps the header and changed lines (+/-), drops excess context.
    """
    lines = diff_content.split("\n")
    if len(lines) <= MAX_LINES_PER_FILE:
        return diff_content

    # Keep header lines (@@, ---, +++)
    header_lines = [
        l for l in lines[:10] if l.startswith(("@@", "---", "+++", "diff", "index"))
    ]
    # Keep changed lines (+ or - but not +++ or ---)
    changed_lines = [
        l
        for l in lines
        if (l.startswith("+") and not l.startswith("+++"))
        or (l.startswith("-") and not l.startswith("---"))
    ]
    # Keep some context lines
    context_lines = [l for l in lines if l.startswith(" ")][:20]

    combined = header_lines + changed_lines + context_lines
    if len(combined) > MAX_LINES_PER_FILE:
        combined = combined[:MAX_LINES_PER_FILE]
        combined.append(
            f"[... {len(lines) - MAX_LINES_PER_FILE} more lines truncated ...]"
        )

    return "\n".join(combined)


def _file_risk_score(filename: str) -> int:
    """
    Score a file by risk level for diff prioritization.
    Higher = more important to include in truncated diff.
    """
    fname = filename.lower()

    # Critical paths
    if any(x in fname for x in ["payment", "billing", "charge", "fee", "price"]):
        return 100
    if any(
        x in fname
        for x in ["auth", "login", "session", "token", "security", "password"]
    ):
        return 95
    if any(x in fname for x in ["database", "migration", "schema", "model"]):
        return 90

    # Config/infra
    if any(x in fname for x in ["config", "settings", "env", "secret"]):
        return 80
    if fname in (
        "requirements.txt",
        "package.json",
        "go.mod",
        "pipfile",
        "poetry.lock",
    ):
        return 75
    if any(x in fname for x in ["docker", "k8s", "deploy", "infra"]):
        return 70

    # Core service code
    if fname.endswith((".py", ".js", ".ts", ".go", ".java", ".rb")):
        return 60

    # Tests (low priority for diff analysis)
    if any(x in fname for x in ["test", "spec", "__test__"]):
        return 20

    # Docs/assets (skip)
    if fname.endswith((".md", ".txt", ".png", ".jpg", ".svg")):
        return 5

    return 40  # default
