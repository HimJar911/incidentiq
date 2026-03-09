"""
Push Filter — Pre-pipeline gate (V1)

Runs BEFORE creating an incident. Two-layer check:

Layer 1 (free, instant): file pattern check
  - All files are docs/tests/config-as-code → skip
  - Any risky file present → proceed to layer 2

Layer 2 (cheap Nova call ~$0.001): semantic risk check
  - Ask Nova: is this push worth paging an engineer?
  - Only if YES → create incident + run full pipeline

This means a team pushing 20x/day only pages on genuinely risky ones.
"""

from __future__ import annotations

import json
import logging
import os
import re

import boto3

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# ─── Layer 1: File pattern classification ────────────────────────────────────

# Files that are NEVER risky — if ALL changed files match these, skip entirely
SAFE_PATTERNS = [
    r"^README",
    r"^CHANGELOG",
    r"^LICENSE",
    r"^\.github/",
    r"^docs?/",
    r"^\.?runbooks?/",
    r"^wiki/",
    r"^examples?/",
    r"^demos?/",
    r"test_.*\.(py|js|ts)$",
    r".*\.test\.(js|ts|jsx|tsx)$",
    r".*\.spec\.(js|ts|jsx|tsx)$",
    r".*_test\.go$",
    r".*Test\.java$",
    r"^tests?/",
    r".*\.(md|txt|rst|adoc)$",
    r".*\.(png|jpg|jpeg|gif|svg|ico|webp)$",
    r".*\.(pdf|docx|xlsx|pptx)$",
    r"^\.gitignore$",
    r"^\.editorconfig$",
    r"^\.prettierrc",
    r"^\.eslintrc",
    r"^Makefile$",
    r"^CODEOWNERS$",
]

# Files that are HIGH RISK — presence of any of these escalates immediately
HIGH_RISK_PATTERNS = [
    r".*\bpayment[s]?\b.*\.(py|js|ts|go|java|rb)$",
    r".*\bauth\b.*\.(py|js|ts|go|java|rb)$",
    r".*\bsecurity\b.*\.(py|js|ts|go|java|rb)$",
    r".*\bmigrat\b.*\.(py|js|ts|go|sql)$",
    r".*\.sql$",
    r"requirements\.txt$",
    r"package\.json$",
    r"go\.mod$",
    r"Pipfile$",
    r"poetry\.lock$",
    r".*config.*\.(py|js|ts|yml|yaml|json|env)$",
    r".*settings.*\.(py|js|ts|yml|yaml|json)$",
    r".*\.env$",
    r".*\.env\..*$",
    r"docker-compose.*\.yml$",
    r"Dockerfile",
    r".*k8s.*\.ya?ml$",
    r".*deploy.*\.ya?ml$",
    r".*infra.*\.(py|ts|js)$",
]

# Commit message keywords that suggest risk
RISKY_MESSAGE_KEYWORDS = [
    "hotfix",
    "patch",
    "urgent",
    "critical",
    "emergency",
    "adjust",
    "update config",
    "change rate",
    "change limit",
    "change threshold",
    "change timeout",
    "divisor",
    "multiplier",
    "fee",
    "price",
    "rate",
    "limit",
    "threshold",
    "migration",
    "breaking",
    "security",
    "auth",
    "permission",
]

SAFE_MESSAGE_KEYWORDS = [
    "readme",
    "typo",
    "comment",
    "docs",
    "documentation",
    "test",
    "lint",
    "format",
    "style",
    "refactor",
    "cleanup",
    "chore",
    "ci",
    "bump version",
    "release notes",
]

# Commit message patterns that indicate a restorative/fix commit
# These should SKIP the pipeline — they are the resolution, not the problem
RESTORATIVE_MESSAGE_PATTERNS = [
    r"^revert[\s:]",  # "revert: ..." or "revert ..."
    r"^revert\b",  # starts with "revert"
    r"^rollback[\s:]",  # "rollback: ..."
    r"^rollback\b",
    r"^restore[\s:]",  # "restore: ..."
    r"^restore\b",
    r"\brestore\s+\w+\s+to\b",  # "restore TAX_RATE to 0.08"
    r"\brestored?\s+\w+\s+to\b",
    r"\breverted?\s+\w+\s+to\b",
    r"^fix:\s+restore",  # "fix: restore TAX_RATE_MULTIPLIER"
    r"^fix:\s+revert",
    r"^undo[\s:]",
    r"^undo\b",
]

# Diff patterns that indicate a value is being restored to non-zero/non-empty
# i.e. the diff removes a zero/broken value and restores a real one
RESTORATIVE_DIFF_PATTERNS = [
    r'^\-.*=.*["\']0["\']',  # removing a "0" value
    r"^\-.*=\s*0\b",  # removing = 0
    r'^\+.*=.*["\'][1-9]',  # adding back a non-zero string value
    r"^\+.*=\s*[1-9]",  # adding back a non-zero number
    r'^\+.*=.*["\'][a-zA-Z]',  # adding back a string value (e.g. restored hostname)
]


def should_run_pipeline(
    commit_message: str,
    all_files_changed: list[str],
    all_commits: list[dict],
    repo_id: str,
    diff_content: str = "",
) -> tuple[bool, str]:
    """
    Main entry point. Returns (should_run: bool, reason: str).

    Called from webhook handler BEFORE creating incident.
    Fast path: returns in <1ms for obvious safe/risky cases.
    Slow path: Nova call for ambiguous cases (~500ms, ~$0.001).
    """
    # Aggregate all changed files across all commits in the push
    all_files = list(set(all_files_changed))
    message_lower = commit_message.lower()

    logger.info(
        f"[push_filter] Evaluating push: {repo_id} | "
        f"{len(all_files)} files | msg='{commit_message[:60]}'"
    )

    # ── Fast pass: check if this is a restorative commit ─────────────────────
    # Revert/rollback/restore commits should NEVER create new incidents —
    # they ARE the fix. Check message pattern first, then optionally verify diff.
    if _is_restorative_commit(commit_message, diff_content):
        reason = f"Restorative commit detected (revert/rollback/restore): '{commit_message[:60]}'"
        logger.info(f"[push_filter] SKIP — {reason}")
        return False, reason

    # ── Fast pass: check message for explicit safe keywords ──────────────────
    if any(kw in message_lower for kw in SAFE_MESSAGE_KEYWORDS):
        # Even safe-looking messages should proceed if risky files are touched
        has_risky_files = _has_risky_files(all_files)
        if not has_risky_files:
            reason = (
                f"Commit message suggests non-critical change: '{commit_message[:60]}'"
            )
            logger.info(f"[push_filter] SKIP — {reason}")
            return False, reason

    # ── Fast pass: check message for explicit risky keywords ─────────────────
    if any(kw in message_lower for kw in RISKY_MESSAGE_KEYWORDS):
        reason = f"Commit message contains risk keyword in: '{commit_message[:60]}'"
        logger.info(f"[push_filter] RUN — {reason}")
        return True, reason

    # ── Layer 1: File pattern analysis ───────────────────────────────────────
    if not all_files:
        logger.info("[push_filter] SKIP — no files changed")
        return False, "No files changed"

    # Check if ALL files are safe
    all_safe = all(_is_safe_file(f) for f in all_files)
    if all_safe:
        reason = f"All {len(all_files)} changed files are docs/tests/assets"
        logger.info(f"[push_filter] SKIP — {reason}")
        return False, reason

    # Check if any file is explicitly high risk
    if _has_risky_files(all_files):
        risky = [f for f in all_files if _is_high_risk_file(f)]
        reason = f"High-risk files changed: {risky[:3]}"
        logger.info(f"[push_filter] RUN — {reason}")
        return True, reason

    # ── Layer 2: Ambiguous — ask Nova ─────────────────────────────────────────
    logger.info("[push_filter] Ambiguous push — escalating to Nova for risk assessment")
    return _nova_risk_check(commit_message, all_files, all_commits, repo_id)


def _is_restorative_commit(commit_message: str, diff_content: str = "") -> bool:
    """
    Returns True if this commit is clearly a revert/rollback/restore.

    Two-signal check:
    1. Message pattern matches a restorative prefix (revert:, rollback, restore X to Y)
    2. If diff is provided, optionally verify it shows values being restored

    If message clearly signals restore, we trust it even without diff.
    This prevents fix commits from firing new incidents.
    """
    message_lower = commit_message.lower().strip()

    # Check message patterns
    message_is_restorative = any(
        re.search(p, message_lower) for p in RESTORATIVE_MESSAGE_PATTERNS
    )

    if not message_is_restorative:
        return False

    # Message looks restorative — if we have a diff, do a sanity check
    # to make sure the diff isn't actually introducing new broken values
    if diff_content:
        diff_lines = diff_content.split("\n")
        added_lines = [
            l for l in diff_lines if l.startswith("+") and not l.startswith("+++")
        ]
        removed_lines = [
            l for l in diff_lines if l.startswith("-") and not l.startswith("---")
        ]

        # If diff only removes things (pure deletion), treat as restorative
        if added_lines and removed_lines:
            # Check if any added line looks like it's restoring a real value
            # (non-zero, non-empty string)
            has_restore_signal = any(
                re.search(p, line)
                for line in added_lines
                for p in RESTORATIVE_DIFF_PATTERNS
            )
            # If diff has no restore signal at all, be cautious and run pipeline
            if not has_restore_signal:
                logger.info(
                    "[push_filter] Message looks restorative but diff has no restore signal — "
                    "deferring to Nova"
                )
                return False

    logger.info(f"[push_filter] Restorative commit confirmed: '{commit_message[:60]}'")
    return True


def _is_safe_file(filepath: str) -> bool:
    """Returns True if this file is categorically safe (docs, tests, assets)."""
    return any(re.search(p, filepath, re.IGNORECASE) for p in SAFE_PATTERNS)


def _is_high_risk_file(filepath: str) -> bool:
    """Returns True if this file is categorically high risk."""
    return any(re.search(p, filepath, re.IGNORECASE) for p in HIGH_RISK_PATTERNS)


def _has_risky_files(files: list[str]) -> bool:
    return any(_is_high_risk_file(f) for f in files)


def _nova_risk_check(
    commit_message: str,
    all_files: list[str],
    all_commits: list[dict],
    repo_id: str,
) -> tuple[bool, str]:
    """
    Lightweight Nova call to assess if this push warrants paging an engineer.
    Only runs for ambiguous cases that passed layer 1.
    Cost: ~$0.001 per call.
    """
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        system_prompt = """You are a senior SRE deciding whether a git push warrants waking up an on-call engineer.

Answer with ONLY valid JSON:
{
  "should_page": true/false,
  "confidence": 0.0-1.0,
  "reason": "One sentence explanation"
}

Be conservative — only page for genuine production risk, not routine code changes.
Never page on revert, rollback, or restore commits — those are fixes, not incidents."""

        user_message = f"""Repo: {repo_id}
Commit message: "{commit_message}"
Files changed ({len(all_files)} total): {json.dumps(all_files[:20])}
Number of commits in push: {len(all_commits)}

Should this push trigger an incident investigation?"""

        response = bedrock.invoke_model(
            modelId=NOVA_LITE_MODEL,
            body=json.dumps(
                {
                    "messages": [{"role": "user", "content": [{"text": user_message}]}],
                    "system": [{"text": system_prompt}],
                    "inferenceConfig": {"maxTokens": 128, "temperature": 0.1},
                }
            ),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        raw = response_body["output"]["message"]["content"][0]["text"].strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        should_page = result.get("should_page", True)  # Default to safe (run pipeline)
        reason = result.get("reason", "Nova assessment")
        confidence = result.get("confidence", 0.5)

        logger.info(
            f"[push_filter] Nova says: should_page={should_page} "
            f"confidence={confidence} reason='{reason}'"
        )
        return should_page, reason

    except Exception as e:
        # On any error, default to running the pipeline (fail safe)
        logger.error(f"[push_filter] Nova check failed: {e} — defaulting to RUN")
        return True, f"Filter error — running pipeline as precaution: {e}"
