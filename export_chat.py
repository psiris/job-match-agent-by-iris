#!/usr/bin/env python3
"""Convert the Claude Code JSONL transcript to a readable markdown file."""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parent

def _find_latest_jsonl() -> Path:
    """Locate the most-recently-modified JSONL session file for this project.

    Claude Code stores sessions under ~/.claude/projects/<encoded-path>/*.jsonl.
    The encoded path replaces path separators with dashes and strips the leading slash.
    """
    home = Path.home()
    encoded = str(_PROJECT_ROOT).lstrip("/").replace("/", "-").replace(" ", "-")
    project_dir = home / ".claude" / "projects" / encoded
    if not project_dir.exists():
        sys.exit(f"ERROR: Claude project dir not found: {project_dir}")
    files = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        sys.exit(f"ERROR: No JSONL session files found in {project_dir}")
    return files[0]

SRC = _find_latest_jsonl()
DST = _PROJECT_ROOT / f"chat_transcript_{datetime.now():%Y%m%d_%H%M%S}.md"

def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            t = block.get("type")
            if t == "text":
                parts.append(block.get("text", ""))
            elif t == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                parts.append(f"\n**[Tool call: {name}]**\n```json\n{json.dumps(inp, indent=2, ensure_ascii=False)[:2000]}\n```")
            elif t == "tool_result":
                res = block.get("content", "")
                if isinstance(res, list):
                    res = "".join(b.get("text", "") for b in res if isinstance(b, dict))
                parts.append(f"\n**[Tool result]**\n```\n{str(res)[:2000]}\n```")
            elif t == "thinking":
                continue
        return "\n".join(parts)
    return str(content)


def main():
    out = ["# Job Match Agent — Chat Transcript", f"\n_Exported: {datetime.now().isoformat(timespec='seconds')}_\n"]
    with SRC.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message")
            if not msg:
                continue
            role = msg.get("role", "?")
            content = msg.get("content", "")
            text = extract_text(content).strip()
            if not text:
                continue
            ts = rec.get("timestamp", "")
            header = f"\n---\n\n## {role.upper()}"
            if ts:
                header += f"  _{ts}_"
            out.append(header)
            out.append("")
            out.append(text)
    DST.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {DST} ({DST.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
