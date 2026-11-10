#!/usr/bin/env python3
"""
確認済みの投稿案（gbp-queue ブランチ）のうち、今日の分をGBPへ投稿する

自動生成の記事には施術の効果をうたう言い方が入るため、GBPへはそのまま出さない。
言い回しを直した本文と画像を人が確かめ、gbp-queue ブランチに置いたものだけを出す。

gbp-queue ブランチの形（1日1件）:
    YYYY-MM-DD.json   {"date": "...", "stem": "202610_…", "title": "…", "body": "…"}
    YYYY-MM-DD.png    画像（任意）。GBPには raw.githubusercontent.com の公開URLで渡す

二重投稿を防ぐため、次のどれかに当たれば投稿しない:
    - Notionのその記事の「GBP投稿日」が埋まっている
    - GBPに同じ本文の投稿（公開中・予約中・審査中）がすでにある

Usage:
    python tools/post_gbp_queue.py --queue <gbp-queueを展開した場所> [--date YYYY-MM-DD] [--live]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import requests

sys.path.insert(0, str(Path(__file__).parent))
from article_text import Article  # noqa: E402
from notify import notify  # noqa: E402
from post_gbp import _env, access_token, post_to_gbp  # noqa: E402

JST = timezone(timedelta(hours=9))
QUEUE_BRANCH = "gbp-queue"
NOTION = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {os.environ.get('NOTION_TOKEN', '')}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}
REQUIRED = ("当店は医療機関ではありません", "アイケアLaBo四ツ谷店")


def norm(s: str) -> str:
    return re.sub(r"\s", "", s)


def notion_page(stem: str) -> dict | None:
    """「生成記事リンク」の末尾が <stem>.md の行を探す（リンクは日本語がURLエンコードされていることがある）"""
    rows, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        resp = requests.post(
            f"{NOTION}/databases/{os.environ['NOTION_DATABASE_ID']}/query",
            headers=NOTION_HEADERS,
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for p in data["results"]:
            url = (p["properties"].get("生成記事リンク") or {}).get("url") or ""
            if url and unquote(url.rsplit("/", 1)[-1]) == f"{stem}.md":
                rows.append(p)
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    if len(rows) > 1:
        raise RuntimeError(f"Notionに同じ記事の行が{len(rows)}件あります（{stem}）")
    return rows[0] if rows else None


def already_on_gbp(body: str) -> bool:
    url = (
        f"https://mybusiness.googleapis.com/v4/accounts/{_env('GBP_ACCOUNT_ID')}"
        f"/locations/{_env('GBP_LOCATION_ID')}/localPosts?pageSize=100"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {access_token()}"}, timeout=30)
    resp.raise_for_status()
    mine = norm(body)
    return any(norm(p.get("summary", "")) == mine for p in resp.json().get("localPosts", []))


def run(queue: Path, day: str, live: bool) -> str:
    item_path = queue / f"{day}.json"
    if not item_path.exists():
        return f"{day} の投稿案はありません"
    item = json.loads(item_path.read_text(encoding="utf-8"))
    if item.get("date") != day:
        raise RuntimeError(f"{item_path.name} の日付が {item.get('date')} になっています")
    missing = [w for w in REQUIRED if w not in item["body"]]
    if missing:
        raise RuntimeError(f"本文に必要な文がありません：{'、'.join(missing)}")

    page = notion_page(item["stem"])
    if page is None:
        raise RuntimeError(f"Notionに記事の行がありません（{item['stem']}）")
    done = (page["properties"].get("GBP投稿日") or {}).get("date")
    if done:
        return f"{item['title']} はGBP投稿日が {done['start']} で入っているため、出しません"
    if already_on_gbp(item["body"]):
        return f"{item['title']} は同じ本文の投稿がGBPにあるため、出しません"

    image_url = None
    if (queue / f"{day}.png").exists():
        repo = os.environ.get("GITHUB_REPOSITORY", "Rplus-shop/eyecare-labo")
        image_url = f"https://raw.githubusercontent.com/{repo}/{QUEUE_BRANCH}/{day}.png"

    article = Article(title=item["title"], body=item["body"], path=item_path)
    name = post_to_gbp(article, image_url, dry_run=not live)
    if not live:
        return f"（試行）{item['title']} を出す準備ができています。画像{'あり' if image_url else 'なし'}"

    resp = requests.patch(
        f"{NOTION}/pages/{page['id']}",
        headers=NOTION_HEADERS,
        json={"properties": {"GBP投稿日": {"date": {"start": day}}}},
        timeout=10,
    )
    if resp.status_code != 200:
        # 投稿は済んでいる。GBPの本文の照合で二重投稿は防げるが、Notionは手で直す
        raise RuntimeError(f"投稿は済みましたが（{name}）、NotionにGBP投稿日を書けませんでした。手で入れてください")
    return f"{item['title']} を投稿しました（{name}）"


def main() -> int:
    parser = argparse.ArgumentParser(description="gbp-queue の今日の投稿案をGBPへ出す")
    parser.add_argument("--queue", required=True, type=Path)
    parser.add_argument("--date", default=datetime.now(JST).date().isoformat())
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        msg = run(args.queue, args.date, args.live)
    except Exception as e:  # noqa: BLE001
        text = f"【アイケアLaBo 自動投稿】Googleビジネスプロフィール（{args.date}）が止まりました\n{e}"
        notify(("" if args.live else "（試行）") + text)
        print(text, file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
