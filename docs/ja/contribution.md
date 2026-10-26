# Contribution

## 開発環境とチェック

Python 3.12とuvを使い，リポジトリルートで実行します．

```bash
uv sync --extra test --group dev --group docs
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pyright
uv run pytest
uv run --group docs python scripts/docs.py build
```

変更と無関係な整形差分は含めないでください．模擬試験・実データ・実機検証は区別して報告します．

## 機能とdocsを一緒に更新する

機能追加・動作変更と同じ変更で，影響する `docs/` を更新します．日本語（`docs/ja/`）と英語（`docs/en/`）の両方を同じ変更で更新し，ページ構成・見出し・コード例・リンク先を揃えます．設定・既定値・CLI・Python API・制限事項と，実際の実装を揃えます．

| 変更 | 更新するページ |
| --- | --- |
| インストールや初回操作 | Quick start |
| 機体や対応する組み合わせ | Robotsの機体ページと機体別Quick start |
| センサーの設定・形式 | Sensorsと対応機体ページ |
| 操作入力・開始条件 | Controllersと対応機体ページ |
| API・CLI・設定の変更 | Referenceと関連するサンプル |

新しいページは両言語の同じパスに置き，`mkdocs.yml`（日本語）と `mkdocs.en.yml`（英語）の `nav` に登録します．READMEと `roboloom init` が配布するテンプレートのREADMEも，手順に影響があれば同時に更新します．現行コードとドキュメントが食い違っていた場合は，コードの規約を基準に修正し，食い違いを変更報告に記載します．

機体ページには対応センサーとcontrollerを記載し，詳しい設定をそれぞれの章へリンクします．現在のガイドの対象はRakuda2，leader，RealSense RGB，DIGITです．設計案や過去の調査メモを，実装済み・実機検証済みの仕様として案内しないでください．

## docsの編集とプレビュー

[ZensicalのMkDocs互換機能](https://zensical.org/docs/compatibility/mkdocs/) を使います．言語ごとに設定を分け，共通設定は `docs/base.yml` に置きます．

| 言語 | Markdown | 設定 | 出力先 |
| --- | --- | --- | --- |
| 日本語 | `docs/ja/` | `mkdocs.yml` | `site/ja/` |
| 英語 | `docs/en/` | `mkdocs.en.yml` | `site/en/` |

```bash
uv run --group docs python scripts/docs.py build   # 両言語をstrictでビルド
uv run --group docs python scripts/docs.py serve   # 両言語をビルドして http://127.0.0.1:8000 で表示
uv run --group docs zensical serve                 # 日本語だけをライブリロードで表示
uv run --group docs zensical serve -f mkdocs.en.yml  # 英語だけをライブリロードで表示
```

右上の言語切り替えは，`site/` に両言語が並んでいるときに同じページの別言語へ移ります．片方の言語だけを `zensical serve` で開いているときは，切り替え先が表示されません．`site/index.html` はブラウザの言語に応じて `ja/` か `en/` へ転送します．生成物はGitへ追加しません．公開・ホスティングは別途設定します．

フォントと配色は `docs/overrides/`（`main.html` と `assets/stylesheets/roboloom.css`）で調整しています．

`docs/ja/yam-safety-and-smoothness.md` は過去の調査・設計メモとして残し，利用ガイドのビルド対象から除外しています．
