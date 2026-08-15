#!/usr/bin/env python3
"""
update_guestbook.py

Called from GitHub Actions. Appends the contents of an issue to the guest book
section of README.md.

Environment:
  ISSUE_BODY   - issue body (GitHub's YAML form)
  ISSUE_USER   - who opened it
  ISSUE_NUMBER - issue number
"""

import os
import re
import html
from datetime import datetime, timezone

README_PATH = "README.md"
MAX_ENTRIES = 20  # How many messages are shown.

START_MARKER = "<!-- GUESTBOOK:START -->"
END_MARKER = "<!-- GUESTBOOK:END -->"


def parse_message(body: str) -> str:
    """Pull the message out of a GitHub issue form body."""
    # YAML form: "### 💬 Your message\n\nHello!"
    match = re.search(
        r"###.*?Your message.*?\n+(.+?)(?:\n###|\Z)", body, re.DOTALL | re.IGNORECASE
    )
    if match:
        msg = match.group(1).strip()
    else:
        # Fall back to the first non-empty line of the whole body
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")]
        msg = lines[0] if lines else "(no message)"
    # Escape what would break the table. str.splitlines() splits on \r, U+2028
    # and U+2029 as well as \n, so a row read back later would be cut in half
    # and take the table with it. These are written as escapes because putting
    # the characters in the source breaks anything reading this file by line.
    msg = re.sub(r"[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]+", " ", msg)
    msg = msg.replace("|", "\\|")
    return msg[:200]


def build_row(user: str, message: str, ts: str, issue_number: str) -> str:
    safe_user = html.escape(user)
    safe_message = html.escape(message)
    profile_url = f"https://github.com/{safe_user}"
    issue_url = f"https://github.com/kanywst/kanywst/issues/{issue_number}"
    return f"    <tr><td><code>{ts}</code></td><td><a href=\"{profile_url}\">@{safe_user}</a></td><td><a href=\"{issue_url}\">{safe_message}</a></td></tr>"


def parse_existing_rows(block: str) -> list[str]:
    """Pull only the data rows out of the block between the markers."""
    rows = []
    for line in block.splitlines():
        # A data row starts with <tr><td><code>, the timestamp cell
        if "<tr><td><code>" in line:
            rows.append(line)
    return rows


def build_table(rows: list[str]) -> str:
    """Build the formatted table block from a list of rows."""
    header = """<table align="center">
  <thead>
    <tr>
      <th>🕐</th>
      <th>👤</th>
      <th>💬</th>
    </tr>
  </thead>
  <tbody>"""
    footer = """  </tbody>
</table>"""
    if not rows:
        empty = "    <tr><td>–</td><td>–</td><td><em>No messages yet. Be the first!</em></td></tr>"
        return f"{header}\n{empty}\n{footer}"
    return f"{header}\n" + "\n".join(rows) + f"\n{footer}"



def update_readme(new_row: str, issue_number: str) -> None:
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )

    match = pattern.search(content)
    existing_rows = parse_existing_rows(match.group(0)) if match else []

    # git push can report failure after the commit has already been taken. On
    # retry the workflow would add the same issue twice, so the row is replaced
    # by issue number. Rewriting a row beats entering it twice.
    marker = f"/issues/{issue_number}\""
    existing_rows = [row for row in existing_rows if marker not in row]

    # Newest entry first, then clip to the maximum
    all_rows = [new_row] + existing_rows
    all_rows = all_rows[:MAX_ENTRIES]

    new_block = f"{START_MARKER}\n{build_table(all_rows)}\n{END_MARKER}"
    # Without the lambda, a \1 or \g written by a visitor is read as a
    # replacement template and the script dies with re.PatternError.
    updated = pattern.sub(lambda _: new_block, content)

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated)


def main():
    body = os.environ.get("ISSUE_BODY", "")
    user = os.environ.get("ISSUE_USER", "anonymous")
    issue_number = os.environ.get("ISSUE_NUMBER", "0")

    message = parse_message(body)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = build_row(user, message, ts, issue_number)

    update_readme(row, issue_number)
    print(f"✅ Added message from @{user}: {message}")


if __name__ == "__main__":
    main()
