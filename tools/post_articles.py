#!/usr/bin/env python3
"""
生成済みの記事を、GBPとサロンボードのブログへ1本ずつ投稿する

Usage:
    python tools/post_articles.py                 # 試行（投稿の直前で止める・Notionは書き換えない）
    python tools/post_articles.py --live          # 本番
    python tools/post_articles.py --channel gbp   # 片方だけ

フロー:
    1. 媒体ごとに、Notionから次に出す記事を1件選ぶ
       （ステータス＝生成済・その媒体の投稿日が空・「投稿日」が今日以前か空。投稿日→作成日の順）
    2. articles/ の記事をプレーンテキストに直して投稿する
    3. 成功したら、Notionにその媒体の投稿日を書く。両方そろったらステータスを「投稿済」にする
    4. 失敗したら、その媒体だけ止めてSlackに知らせる。もう一方は続ける

Notionに要る項目: 「GBP投稿日」「HPB投稿日」（日付）、ステータスの選択肢「投稿済」
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from article_text import load_article  # noqa: E402
from notify import notify  # noqa: E402
from post_gbp import post_to_gbp  # noqa: E402
from post_salonboard import post_to_salonboard  # noqa: E402

TOKEN = os.environ.get("NOTION_TOKEN", "")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

PROJECT_ROOT = Path(__file__).parent.parent
ARTICLES_DIR = PROJECT_ROOT / "articles"
IMAGES_DIR = PROJECT_ROOT / "images"
JST = timezone(timedelta(hours=9))

CHANNELS = {
    "gbp": {"label": "Googleビジネスプロフィール", "date_prop": "GBP投稿日"},
    "hpb": {"label": "ホットペッパー（サロンボード）", "date_prop": "HPB投稿日"},
}
STATUS_READY = "生成済"
STATUS_DONE = "投稿済"


def notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def today_jst() -> date:
    return datetime.now(JST).date()


def fetch_next(channel: str) -> dict | None:
    date_prop = CHANNELS[channel]["date_prop"]
    resp = requests.post(
        f"{NOTION_API_BASE}/databases/{DATABASE_ID}/query",
        headers=notion_headers(),
        json={
            "filter": {
                "and": [
                    {"property": "ステータス", "select": {"equals": STATUS_READY}},
                    {"property": date_prop, "date": {"is_empty": True}},
                    {
                        "or": [
                            {"property": "投稿日", "date": {"is_empty": True}},
                            {"property": "投稿日", "date": {"on_or_before": today_jst().isoformat()}},
                        ]
                    },
                ]
            },
            "sorts": [
                {"property": "投稿日", "direction": "ascending"},
                {"timestamp": "created_time", "direction": "ascending"},
            ],
            "page_size": 1,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Notionの検索に失敗しました（{resp.json().get('message', resp.status_code)}）")
    results = resp.json().get("results", [])
    return results[0] if results else None


def article_path_of(page: dict) -> Path:
    """「生成記事リンク」のURLの末尾から、articles/ のファイルを引く"""
    url = (page["properties"].get("生成記事リンク") or {}).get("url") or ""
    name = unquote(url.rsplit("/", 1)[-1]) if url else ""
    path = ARTICLES_DIR / name
    if not name or not path.exists():
        raise FileNotFoundError(f"記事ファイルが見つかりません（生成記事リンク: {url or '空'}）")
    return path


def image_url_of(path: Path) -> str | None:
    """GBPに渡す画像の公開URL。リポジトリ名は実行中のものを使う（旧名のURLに頼らない）"""
    if not (IMAGES_DIR / f"{path.stem}.png").exists():
        return None
    repo = os.environ.get("GITHUB_REPOSITORY", "tonkatsuphotos-creator/eyecare-labo-ver1")
    return f"https://raw.githubusercontent.com/{repo}/main/images/{path.stem}.png"


def mark_posted(page: dict, channel: str) -> None:
    props = {CHANNELS[channel]["date_prop"]: {"date": {"start": today_jst().isoformat()}}}
    others = [c for c in CHANNELS if c != channel]
    if all((page["properties"].get(CHANNELS[c]["date_prop"]) or {}).get("date") for c in others):
        props["ステータス"] = {"select": {"name": STATUS_DONE}}
    resp = requests.patch(
        f"{NOTION_API_BASE}/pages/{page['id']}", headers=notion_headers(), json={"properties": props}, timeout=10
    )
    if resp.status_code != 200:
        # 投稿は済んでいる。ここで黙ると翌日に同じ記事をもう一度出してしまう
        raise RuntimeError(
            f"投稿は済みましたが、Notionに投稿日を書けませんでした（{resp.json().get('message', resp.status_code)}）。"
            "翌日の便で二重に投稿しないよう、手で投稿日を入れてください"
        )


def run_channel(channel: str, live: bool) -> bool:
    label = CHANNELS[channel]["label"]
    page = fetch_next(channel)
    if page is None:
        print(f"[{label}] 出す記事がありません")
        return True
    path = article_path_of(page)
    article = load_article(path)
    print(f"[{label}] {article.title}（{len(article.body)}字）")

    if channel == "gbp":
        result = post_to_gbp(article, image_url_of(path), dry_run=not live)
    else:
        result = post_to_salonboard(article, IMAGES_DIR / f"{path.stem}.png", dry_run=not live)

    if live:
        mark_posted(page, channel)
        print(f"[{label}] 投稿しました: {result}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="生成済みの記事をGBPとサロンボードへ投稿する")
    parser.add_argument("--channel", choices=["gbp", "hpb", "all"], default="all")
    parser.add_argument("--live", action="store_true", help="本番の投稿をする。付けなければ投稿の直前で止める")
    args = parser.parse_args()

    if not TOKEN or not DATABASE_ID:
        print("[エラー] NOTION_TOKEN か NOTION_DATABASE_ID が未設定です。", file=sys.stderr)
        return 1

    channels = list(CHANNELS) if args.channel == "all" else [args.channel]
    failed = []
    for ch in channels:
        try:
            run_channel(ch, live=args.live)
        except Exception as e:
            label = CHANNELS[ch]["label"]
            failed.append(label)
            msg = f"【アイケアLaBo 自動投稿】{label}への投稿が止まりました\n{e}"
            if not args.live:
                msg = "（試行）" + msg
            notify(msg)
            print(f"[{label}] 失敗: {e}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
