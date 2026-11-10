# GBPの投稿待ち

ここに置いた投稿案を、main の `.github/workflows/post_gbp_queue.yml` が各日の 9:00（JST）に Googleビジネスプロフィールへ投稿します。

- `YYYY-MM-DD.json`：`{"date", "stem", "title", "body"}`。本文は人が確かめたもの
- `YYYY-MM-DD.png`：投稿の画像（任意）

案は多々良側のMacの `gbp-queue-push.py` が置きます。手で書き換えないでください。
取り消すときは、投稿日の前にその日の2ファイルを消します。投稿済みの案は消さずに残します（記録のため）。
