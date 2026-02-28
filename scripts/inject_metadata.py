#!/usr/bin/env python3
"""
Injects an HTML metadata comment block into each runbook at the top AND after
every ## section heading. This ensures Bedrock Knowledge Base retrieval always
returns the metadata regardless of which chunk it scores highest on.

Bedrock strips YAML frontmatter before indexing and splits documents into chunks.
By repeating the comment at every section boundary, every chunk carries the
runbook identity — so _parse_runbook_metadata() always finds it.

Comment format (invisible in rendered markdown, preserved verbatim by Bedrock):
  <!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config... -->

Run from project root:
    python scripts/inject_metadata.py

Safe to re-run — strips existing comments before re-injecting (idempotent).
"""
import re
import sys
from pathlib import Path

RUNBOOKS_DIR = Path(__file__).parent.parent / "runbooks"
COMMENT_RE = re.compile(r"<!-- iq:runbook_id=.*?-->\n?", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, int]:
    if not content.startswith("---"):
        return {}, 0
    try:
        end = content.index("---", 3)
        metadata = {}
        for line in content[3:end].splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                metadata[key] = value
        return metadata, end + 3
    except ValueError:
        return {}, 0


def build_comment(metadata: dict) -> str:
    runbook_id = metadata.get("runbook_id", "unknown")
    title = metadata.get("title", "Unknown")
    first_action_step = metadata.get("first_action_step", "See runbook for details.")
    return f"<!-- iq:runbook_id={runbook_id} | title={title} | first_action_step={first_action_step} -->"


def inject_metadata(content: str) -> tuple[str, bool]:
    """
    1. Strip all existing iq comments (idempotent).
    2. Insert comment immediately after frontmatter.
    3. Insert comment after every ## section heading.
    Returns (updated_content, was_changed).
    """
    metadata, fm_end = parse_frontmatter(content)
    if not metadata:
        return content, False

    comment = build_comment(metadata)

    # Strip all existing iq comments
    clean = COMMENT_RE.sub("", content)

    # Re-find frontmatter end in cleaned content
    _, fm_end = parse_frontmatter(clean)

    # Split into frontmatter block and body
    fm_block = clean[:fm_end]
    body = clean[fm_end:]

    # Inject after frontmatter
    body = "\n" + comment + "\n" + body.lstrip("\n")

    # Inject after every ## heading (not ### or deeper)
    def inject_after_h2(match):
        return match.group(0) + comment + "\n"

    body = re.sub(r"(^## .+\n)", inject_after_h2, body, flags=re.MULTILINE)

    updated = fm_block + body
    return updated, updated != content


def process_all():
    runbooks = sorted(RUNBOOKS_DIR.glob("*.md"))
    if not runbooks:
        print(f"❌ No .md files found in {RUNBOOKS_DIR}")
        sys.exit(1)

    print(f"🔧 Injecting metadata comments into {len(runbooks)} runbooks\n")
    changed = 0

    for path in runbooks:
        content = path.read_text(encoding="utf-8")
        updated, was_changed = inject_metadata(content)

        if was_changed:
            path.write_text(updated, encoding="utf-8")
            meta, _ = parse_frontmatter(content)
            comment_count = len(re.findall(r"<!-- iq:runbook_id=", updated))
            print(f"  ✅ {path.name}")
            print(f"     runbook_id      : {meta.get('runbook_id')}")
            print(f"     title           : {meta.get('title')}")
            print(
                f"     comments inject : {comment_count} (top + after each ## section)"
            )
            changed += 1
        else:
            print(f"  ⏭️  {path.name} — already up to date")

    print(f"\n✅ Done — {changed}/{len(runbooks)} files updated")
    print("\nNext steps:")
    print(
        "  1. python scripts/seed_runbooks.py   <- re-uploads to S3 + triggers KB re-index"
    )
    print("  2. Wait ~2-3 minutes for Bedrock ingestion to complete")
    print("  3. Hit REPLAY DEMO and verify all 3 runbook hits show real titles")


if __name__ == "__main__":
    process_all()
