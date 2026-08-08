#!/usr/bin/env python3
"""
build_readme.py

GitHub Actions から定期的に呼び出され、README.md のマーカー間を生データで埋める。
手で書き換える部分は散文だけで、数字とリストは常にライブのまま保たれる。

埋めるマーカー:
  UPSTREAM - 直近のマージ済み upstream PR
  RELEASES - 自作リポジトリの直近リリース
  WRITING  - dev.to の直近記事

環境変数:
  GITHUB_TOKEN - Search API と GraphQL の認証に使う (必須)

いずれかの取得に失敗したセクションは既存の内容をそのまま残す。
一時的な API 障害で README が空になるより、古いままの方がましなため。
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

README_PATH = "README.md"
USER = "kanywst"

# 自分のリポジトリと下書き用 org は upstream 貢献から除く
EXCLUDE = f"-user:{USER} -org:0-draft"
MERGED_QUERY = f"is:pr author:{USER} is:merged {EXCLUDE}"

# プロフィールページの README カラムは実測 846px、狭い画面では 590px しかない。
# 3 カラムに割ると 1 本 270px / 190px なので、1 行に収まらないものは全部落とす。
MAX_UPSTREAM = 5
MAX_RELEASES = 5
MAX_WRITING = 4
MAX_TITLE = 42

API = "https://api.github.com"


def request_json(url: str, data: dict | None = None) -> dict:
    """GitHub API / dev.to API を叩いて JSON を返す。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-build-readme",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def truncate(text: str, limit: int = MAX_TITLE) -> str:
    """カラム幅に収まるようタイトルを詰める。語の途中では切らない。"""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    # 直前の空白まで戻す。1語で溢れる場合のみ語中で切る。
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,.:;-") + "…"


def search_prs(query: str, per_page: int = 100) -> dict:
    url = (
        f"{API}/search/issues?q={urllib.parse.quote(query)}"
        f"&sort=updated&order=desc&per_page={per_page}"
    )
    return request_json(url)


def repo_of(item: dict) -> str:
    """検索結果の repository_url から owner/name を取り出す。"""
    return item["repository_url"].split("/repos/", 1)[1]


def build_upstream(merged: list[dict]) -> str:
    # 検索は updated 順で返るので、表示に使う closed_at で並べ直す。
    merged = sorted(merged, key=lambda item: item["closed_at"], reverse=True)
    # PR タイトルと日付は載せない。狭いカラムだと 1 件が 4 行に折り返して、
    # 5 件で壁になる。どこに入ったかが読めれば足りる。
    # タイトルを外すと同じリポジトリの複数 PR が同じ行になるので、最新だけ残す。
    lines = []
    seen: set[str] = set()
    for item in merged:
        repo = repo_of(item)
        if repo in seen:
            continue
        seen.add(repo)
        lines.append(f"[{repo}]({item['html_url']})")
        if len(lines) == MAX_UPSTREAM:
            break
    return "\n\n".join(lines)


def build_releases() -> str:
    query = """
    query {
      user(login: "%s") {
        repositories(
          first: 100
          ownerAffiliations: OWNER
          isFork: false
          privacy: PUBLIC
          orderBy: {field: PUSHED_AT, direction: DESC}
        ) {
          nodes {
            name
            isArchived
            releases(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
              nodes { tagName publishedAt url isPrerelease }
            }
          }
        }
      }
    }
    """ % USER

    payload = request_json(f"{API}/graphql", {"query": query})
    nodes = payload["data"]["user"]["repositories"]["nodes"]

    releases = []
    for repo in nodes:
        if repo["isArchived"] or not repo["releases"]["nodes"]:
            continue
        rel = repo["releases"]["nodes"][0]
        if rel["isPrerelease"] or not rel["publishedAt"]:
            continue
        # goreleaser が付ける "name-1.2.3" 形式を v1.2.3 に寄せる
        tag = rel["tagName"]
        if tag.startswith(f"{repo['name']}-"):
            tag = "v" + tag[len(repo["name"]) + 1 :]
        releases.append((rel["publishedAt"], repo["name"], tag, rel["url"]))

    releases.sort(reverse=True)

    lines = []
    for _published, name, tag, url in releases[:MAX_RELEASES]:
        lines.append(f"[{name}]({url}) {tag}")
    return "\n\n".join(lines)


def build_writing() -> str:
    articles = request_json(
        f"https://dev.to/api/articles?username={USER}&per_page={MAX_WRITING}"
    )
    lines = []
    for article in articles[:MAX_WRITING]:
        lines.append(f"[{truncate(article['title'])}]({article['url']})")
    return "\n\n".join(lines)


def replace_block(content: str, name: str, body: str) -> str:
    """<!-- NAME:START --> と <!-- NAME:END --> の間を差し替える。"""
    start = f"<!-- {name}:START -->"
    end = f"<!-- {name}:END -->"
    pattern = re.compile(rf"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)

    if not pattern.search(content):
        raise SystemExit(f"marker {name} not found in {README_PATH}")

    replacement = f"{start}\n{body}\n{end}"
    return pattern.sub(lambda _: replacement, content)


def main() -> None:
    with open(README_PATH, encoding="utf-8") as f:
        content = f.read()

    items = search_prs(MERGED_QUERY)["items"]

    sections = {
        "UPSTREAM": build_upstream(items),
        "RELEASES": build_releases,
        "WRITING": build_writing,
    }

    for name, value in sections.items():
        try:
            body = value() if callable(value) else value
        except (urllib.error.URLError, KeyError, TypeError) as err:
            print(f"skipped {name}: {err}", file=sys.stderr)
            continue
        if not body:
            print(f"skipped {name}: empty", file=sys.stderr)
            continue
        content = replace_block(content, name, body)
        print(f"updated {name}")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    main()
