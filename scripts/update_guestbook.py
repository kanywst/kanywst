#!/usr/bin/env python3
"""
update_guestbook.py

GitHub Actions から呼び出され、Issue の内容を README.md のゲストブックセクションに追記する。
環境変数:
  ISSUE_BODY   - Issue 本文 (GitHub フォームの YAML 形式)
  ISSUE_USER   - Issue 作成者のユーザー名
  ISSUE_NUMBER - Issue 番号
"""

import os
import re
import html
from datetime import datetime, timezone

README_PATH = "README.md"
MAX_ENTRIES = 20  # 表示する最大メッセージ数

START_MARKER = "<!-- GUESTBOOK:START -->"
END_MARKER = "<!-- GUESTBOOK:END -->"


def parse_message(body: str) -> str:
    """GitHub Issue フォームの本文からメッセージを抽出する。"""
    # YAML form: "### 💬 Your message\n\nHello!" の形式
    match = re.search(
        r"###.*?Your message.*?\n+(.+?)(?:\n###|\Z)", body, re.DOTALL | re.IGNORECASE
    )
    if match:
        msg = match.group(1).strip()
    else:
        # フォールバック: 本文全体の最初の非空行
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")]
        msg = lines[0] if lines else "(no message)"
    # テーブル内で問題になる文字をエスケープ
    msg = msg.replace("|", "\\|").replace("\n", " ")
    return msg[:200]  # 最大200文字


def build_row(user: str, message: str, ts: str, issue_number: str) -> str:
    safe_user = html.escape(user)
    safe_message = html.escape(message)
    profile_url = f"https://github.com/{safe_user}"
    issue_url = f"https://github.com/kanywst/kanywst/issues/{issue_number}"
    return f"    <tr><td><code>{ts}</code></td><td><a href=\"{profile_url}\">@{safe_user}</a></td><td><a href=\"{issue_url}\">{safe_message}</a></td></tr>"


def parse_existing_rows(block: str) -> list[str]:
    """マーカー間のブロックからデータ行だけを抽出する。"""
    rows = []
    for line in block.splitlines():
        # データ行: <tr><td><code> で始まる行（タイムスタンプ付き）
        if "<tr><td><code>" in line:
            rows.append(line)
    return rows


def build_table(rows: list[str]) -> str:
    """行リストから整形済みテーブルブロックを生成する。"""
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



def update_readme(new_row: str) -> None:
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )

    match = pattern.search(content)
    existing_rows = parse_existing_rows(match.group(0)) if match else []

    # 新しいエントリを先頭に追加し、最大件数にクリップ
    all_rows = [new_row] + existing_rows
    all_rows = all_rows[:MAX_ENTRIES]

    new_block = f"{START_MARKER}\n{build_table(all_rows)}\n{END_MARKER}"
    updated = pattern.sub(new_block, content)

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated)


def main():
    body = os.environ.get("ISSUE_BODY", "")
    user = os.environ.get("ISSUE_USER", "anonymous")
    issue_number = os.environ.get("ISSUE_NUMBER", "0")

    message = parse_message(body)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = build_row(user, message, ts, issue_number)

    update_readme(row)
    print(f"✅ Added message from @{user}: {message}")


if __name__ == "__main__":
    main()
