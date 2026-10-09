#!/usr/bin/env python3
"""
ホットペッパービューティー（サロンボードのブログ）に記事を投稿する

公開APIが無いため、Playwrightでサロンボードの画面を操作する。

**入力欄の位置（SELECTORS）はまだ空。** サロンボードの画面を人がログインした状態で確かめてから埋める。
空のまま動かすと、ログインもせずに止まる。

画像認証（CAPTCHA）が出たら、自動で越えずに止める。

必要な環境変数（GitHub Secrets）:
    SALONBOARD_LOGIN_ID / SALONBOARD_PASSWORD
    SALONBOARD_STAFF     ブログの投稿者に選ぶスタッフ名
    SALONBOARD_CATEGORY  ブログのカテゴリ名
"""

from __future__ import annotations

import os
from pathlib import Path

from article_text import Article

LOGIN_URL = "https://salonboard.com/login/"
SHOT_DIR = Path(__file__).parent.parent / "screenshots"

# 画面で確かめてから埋める。None のものが1つでもあれば動かさない
SELECTORS: dict[str, str | None] = {
    "login_id": None,
    "login_password": None,
    "login_submit": None,
    "blog_new_url": None,  # ブログの新規投稿画面のURL
    "title": None,
    "category": None,
    "staff": None,
    "body": None,
    "image_input": None,  # <input type="file">
    "confirm": None,  # 確認画面へ進むボタン
    "submit": None,  # 投稿を確定するボタン（試行では押さない）
}

TITLE_MAX = int(os.environ.get("SALONBOARD_TITLE_MAX", "0") or 0)  # 画面で上限を確かめて入れる。0は未確認


class SalonBoardError(Exception):
    pass


def _missing_selectors() -> list[str]:
    return [k for k, v in SELECTORS.items() if not v]


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SalonBoardError(f"{name} が未設定です")
    return v


def post_to_salonboard(article: Article, image_path: Path | None, dry_run: bool) -> str:
    """投稿して、結果の画面のURLを返す。dry_run では入力して写真を撮り、投稿のボタンは押さない"""
    missing = _missing_selectors()
    if missing:
        raise SalonBoardError("サロンボードの入力欄の位置が未設定です: " + ", ".join(missing))
    if TITLE_MAX and len(article.title) > TITLE_MAX:
        raise SalonBoardError(f"タイトルが{len(article.title)}字あり、上限{TITLE_MAX}字を超えています")

    from playwright.sync_api import sync_playwright  # 使うときだけ読み込む

    SHOT_DIR.mkdir(exist_ok=True)
    stem = article.path.stem
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="ja-JP")
        try:
            page.goto(LOGIN_URL)
            if page.locator("iframe[src*='recaptcha'], .g-recaptcha").count() > 0:
                raise SalonBoardError("ログイン画面に画像認証が出ています。自動では進めません")
            page.fill(SELECTORS["login_id"], _env("SALONBOARD_LOGIN_ID"))
            page.fill(SELECTORS["login_password"], _env("SALONBOARD_PASSWORD"))
            page.click(SELECTORS["login_submit"])
            page.wait_for_load_state("networkidle")

            page.goto(SELECTORS["blog_new_url"])
            page.fill(SELECTORS["title"], article.title)
            page.select_option(SELECTORS["category"], label=_env("SALONBOARD_CATEGORY"))
            page.select_option(SELECTORS["staff"], label=_env("SALONBOARD_STAFF"))
            page.fill(SELECTORS["body"], article.body)
            if image_path and image_path.exists():
                page.set_input_files(SELECTORS["image_input"], str(image_path))
            page.click(SELECTORS["confirm"])
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(SHOT_DIR / f"{stem}_confirm.png"), full_page=True)

            if dry_run:
                print(f"[サロンボード・試行] 確認画面で止めました。写真: screenshots/{stem}_confirm.png")
                return "dry-run"

            page.click(SELECTORS["submit"])
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(SHOT_DIR / f"{stem}_done.png"), full_page=True)
            return page.url
        except SalonBoardError:
            raise
        except Exception as e:  # 画面が変わった・時間切れなど
            page.screenshot(path=str(SHOT_DIR / f"{stem}_error.png"), full_page=True)
            raise SalonBoardError(f"サロンボードの操作で止まりました（{type(e).__name__}）") from e
        finally:
            browser.close()
