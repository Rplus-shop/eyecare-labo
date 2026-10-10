#!/usr/bin/env python3
"""
自動投稿の失敗をSlackに知らせる

送り先は2通り（2026-10-11 岸川様指定：#96-i_kachitto）。
- SLACK_TOKEN ＋ SLACK_CHANNEL：Slack API（chat.postMessage）。Slack Connect のチャンネルにも送れる
- SLACK_WEBHOOK_URL：Incoming Webhook
どちらも未設定なら送らず、標準エラーに出すだけにする。送れなかったことを隠さないため、戻り値で返す。
"""

from __future__ import annotations

import os
import sys

import requests


def notify(text: str) -> bool:
    token = os.environ.get("SLACK_TOKEN", "").strip()
    channel = os.environ.get("SLACK_CHANNEL", "").strip()
    if token and channel:
        try:
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel": channel, "text": text},
                timeout=10,
            )
            body = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"[通知失敗] {type(e).__name__}\n{text}", file=sys.stderr)
            return False
        if not body.get("ok"):
            print(f"[通知失敗] Slack {body.get('error')}\n{text}", file=sys.stderr)
            return False
        return True

    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        print(f"[通知なし] SLACK_TOKEN/SLACK_CHANNEL も SLACK_WEBHOOK_URL も未設定のため、Slackには送っていません:\n{text}", file=sys.stderr)
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
