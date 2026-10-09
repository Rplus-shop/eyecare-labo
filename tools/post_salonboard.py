#!/usr/bin/env python3
"""
ホットペッパービューティー（サロンボードのブログ）に記事を投稿する

公開APIが無いため、Playwrightでサロンボードの画面を操作する。

入力欄の位置（SELECTORS）と上限は、2026-10-09 に実際の画面で確かめたもの。
画面が変わって欄が見つからなくなったら、写真を残して止まる。

publish_at（datetime）を渡すと予約投稿にする。岸川様は朝9時の予約投稿で出している。
クーポンの添付はまだ作っていない（選ぶクーポンを決めていただいてから）。

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
BLOG_NEW_URL = "https://salonboard.com/KLP/blog/blog/"
SHOT_DIR = Path(__file__).parent.parent / "screenshots"

# 2026-10-09 アイケアLaBo四ツ谷店のサロンボードで、多々良がログインした画面を読んで埋めた。
# 確認画面（/KLP/blog/blog/confirm）まで進めたが、登録のボタンは押していない。
SELECTORS: dict[str, str | None] = {
    "login_id": "input[name=userId]",
    "login_password": "input[name=password]",
    "login_submit": "a.common-CNCcommon__primaryBtn",  # 「ログイン」のリンク
    "staff": "#staffId",  # 投稿者。いまは「Ren」だけ
    "category": "#blogCategoryCd",  # プライベート／サロンのNEWS／おすすめメニュー／おすすめデザイン／ビューティー
    "title": "#blogTitle",
    "body_textarea": "blogContents",  # nicEdit の元の textarea の id。本文は nicEditors 経由で入れる
    "image_open": "#upload",  # 「画像アップロード」
    "image_input": "#sendFile",
    "image_submit": "input.jscImageUploaderModalSubmitButton",  # モーダルの「登録する」
    "rsv_on": "input[name=rsvTokoFlg][value='1']",  # 予約投稿「設定する」
    "rsv_date": "#rsvTokoDate",  # 表示は「2026年10月14日（水）」。今日から14日先まで
    "rsv_time": "#rsvTokoTime",  # 15分刻み
    "confirm": "#confirm",  # 「確認する」
    "submit": "#reflect",  # 確認画面の「登録・反映する」（試行では押さない）
}

# 画面の注記（全角で数える）
TITLE_MAX = 25
BODY_MAX = 1000
LINES_MAX = 80
IMAGES_MAX = 4
WEEKDAYS = "月火水木金土日"


class SalonBoardError(Exception):
    pass


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SalonBoardError(f"{name} が未設定です")
    return v


def check_limits(article: Article) -> None:
    """サロンボードの上限を超えるものは、入力する前に止める（黙って切らない）"""
    problems = []
    if len(article.title) > TITLE_MAX:
        problems.append(f"タイトル{len(article.title)}字（上限{TITLE_MAX}字）")
    if len(article.body) > BODY_MAX:
        problems.append(f"本文{len(article.body)}字（上限{BODY_MAX}字）")
    lines = article.body.count("\n")
    if lines > LINES_MAX:
        problems.append(f"改行{lines}回（上限{LINES_MAX}回）")
    if problems:
        raise SalonBoardError("サロンボードの上限を超えています: " + "、".join(problems))


def body_html(text: str) -> str:
    """プレーンテキストを、改行を <br> にしたHTMLにする"""
    import html

    return "<br>".join(html.escape(line) for line in text.split("\n"))


def rsv_label(d) -> str:
    return f"{d.year}年{d.month:02d}月{d.day:02d}日（{WEEKDAYS[d.weekday()]}）"


def post_to_salonboard(article: Article, image_path: Path | None, dry_run: bool, publish_at=None) -> str:
    """投稿して、結果の画面のURLを返す。dry_run では入力して写真を撮り、投稿のボタンは押さない"""
    check_limits(article)

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

            if "/login" in page.url:
                raise SalonBoardError("ログインできませんでした（IDかパスワードを確認してください）")

            page.goto(BLOG_NEW_URL)
            page.select_option(SELECTORS["staff"], label=_env("SALONBOARD_STAFF"))
            page.select_option(SELECTORS["category"], label=_env("SALONBOARD_CATEGORY"))
            page.fill(SELECTORS["title"], article.title)
            # 本文は nicEdit（リッチテキスト）。画面の欄に直接打たず、エディタのAPIで入れる
            page.evaluate(
                "([id, html]) => nicEditors.findEditor(id).setContent(html)",
                [SELECTORS["body_textarea"], body_html(article.body)],
            )
            if image_path and image_path.exists():
                page.click(SELECTORS["image_open"])
                page.set_input_files(SELECTORS["image_input"], str(image_path))
                page.click(SELECTORS["image_submit"])
                page.wait_for_timeout(3000)
            if publish_at is not None:
                page.check(SELECTORS["rsv_on"])
                page.select_option(SELECTORS["rsv_date"], label=rsv_label(publish_at))
                page.select_option(SELECTORS["rsv_time"], label=publish_at.strftime("%H:%M"))
            page.click(SELECTORS["confirm"])
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(SHOT_DIR / f"{stem}_confirm.png"), full_page=True)
            if "/confirm" not in page.url:
                # 入力に誤りがあると、確認画面へ進まず入力画面のまま赤字が出る
                raise SalonBoardError(f"確認画面へ進めませんでした。写真: screenshots/{stem}_confirm.png")

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
