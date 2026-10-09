#!/usr/bin/env python3
"""
Googleビジネスプロフィール（GBP）に「最新情報」として記事を投稿する

Business Profile API（v4 localPosts）を使う。
**APIはGoogleへの利用申請が通るまで呼べない**（それまでは上限0回で 429/403 が返る）。

必要な環境変数（GitHub Secrets）:
    GBP_CLIENT_ID / GBP_CLIENT_SECRET   Google CloudのOAuthクライアント
    GBP_REFRESH_TOKEN                    店舗のオーナーか管理者のアカウントで同意して得た更新用トークン
    GBP_ACCOUNT_ID / GBP_LOCATION_ID     数字のID（accounts/{ここ}/locations/{ここ}）
    GBP_BOOKING_URL                      任意。あれば「予約」ボタンを付ける
"""

from __future__ import annotations

import os

import requests

from article_text import Article

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://mybusiness.googleapis.com/v4"
SUMMARY_MAX = 1500  # GBPの最新情報の本文の上限


class GbpError(Exception):
    pass


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise GbpError(f"{name} が未設定です")
    return v


def access_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": _env("GBP_CLIENT_ID"),
            "client_secret": _env("GBP_CLIENT_SECRET"),
            "refresh_token": _env("GBP_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise GbpError(f"アクセストークンを取れませんでした（{resp.status_code} {resp.json().get('error', '')}）")
    return resp.json()["access_token"]


def build_post(article: Article, image_url: str | None) -> dict:
    if len(article.body) > SUMMARY_MAX:
        # 黙って切ると免責文が落ちる。切らずに止める
        raise GbpError(f"本文が{len(article.body)}字あり、GBPの上限{SUMMARY_MAX}字を超えています")
    post: dict = {"languageCode": "ja", "topicType": "STANDARD", "summary": article.body}
    if image_url:
        post["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": image_url}]
    booking = os.environ.get("GBP_BOOKING_URL", "").strip()
    if booking:
        post["callToAction"] = {"actionType": "BOOK", "url": booking}
    return post


def post_to_gbp(article: Article, image_url: str | None, dry_run: bool) -> str:
    """投稿して、GBP側の投稿の名前（accounts/…/localPosts/…）を返す。dry_run では送らない"""
    body = build_post(article, image_url)
    if dry_run:
        print(f"[GBP・試行] 送らずに止めました。本文{len(article.body)}字・画像{'あり' if image_url else 'なし'}")
        return "dry-run"

    url = f"{API_BASE}/accounts/{_env('GBP_ACCOUNT_ID')}/locations/{_env('GBP_LOCATION_ID')}/localPosts"
    resp = requests.post(url, headers={"Authorization": f"Bearer {access_token()}"}, json=body, timeout=30)
    if resp.status_code != 200:
        msg = resp.json().get("error", {}).get("message", "") if resp.content else ""
        if resp.status_code in (403, 429):
            msg += "（APIの利用申請が通っていない可能性があります）"
        raise GbpError(f"GBPへの投稿に失敗しました（{resp.status_code}）{msg}")
    return resp.json().get("name", "")
