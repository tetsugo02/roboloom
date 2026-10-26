# roboloom

roboloom は，ロボットのteleoperationとセンサー観測を収集し，LeRobotDatasetに保存するPythonパッケージです．現在のガイドは **Rakuda2・leader・RealSense RGB・DIGIT** を対象にしています．

実機の収集では `Session` がdora dataflowを起動し，leader，follower，センサー，recorderを別プロセスで動かします．Python 3.12，dora-rs / dora-rs-cli 1.0.1，LeRobotDataset 0.6.1を使います．

| 章 | 内容 |
| --- | --- |
| [Quick start](quick-start/installation.md) | インストール，Rakuda2の設定，重力補償，teleoperationでのデータ収集 |
| [Robots](robots/index.md) | 機体の構成と対応するセンサー・controller |
| [Sensors](sensors/index.md) | RealSenseとDIGITの設定・画像形式 |
| [Controllers](controllers/index.md) | leaderによる操作，姿勢合わせ，入力の期限 |
| [Reference](reference/configuration.md) | 設定，CLI，Python API，重力補償の詳細 |
| [Contribution](contribution.md) | 開発環境，検証，機能変更に合わせたdocs更新 |

まず [インストール](quick-start/installation.md)，次に [Rakuda2 Quick start](quick-start/rakuda2.md) に進んでください．ガイドの実機コマンドには，操作者による設定値の照合と機体ごとの動作確認が必要です．模擬実行やdocsのビルド成功は，実機検証を意味しません．
