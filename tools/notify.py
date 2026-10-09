#!/usr/bin/env python3
"""
自動投稿の失敗をSlackに知らせる

SLACK_WEBHOOK_URL（Incoming Webhook）が未設定なら送らず、標準エラーに出すだけにする。
送れなかったことを隠さないため、戻り値で送れたかどうかを返す。
"""

from __future__ import annotations

import os
import sys

import requests


def notify(text: str) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        print(f"[通知なし] SLACK_WEBHOOK_URL が未設定のため、Slackには送っていません:\n{text}", file=sys.stderr)
        return False
    try:
        resp = requests.post(url, json={"text": text}, timeout=10)
    except requests.RequestException as e:
        print(f"[通知失敗] {type(e).__name__}\n{text}", file=sys.stderr)
        return False
    if resp.status_code != 200:
        print(f"[通知失敗] Slack {resp.status_code}\n{text}", file=sys.stderr)
        return False
    return True
