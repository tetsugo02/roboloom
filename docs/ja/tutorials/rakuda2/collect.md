# Rakuda2：teleopで収集

<span class="status status--verified">実機検証済み</span>

- **目的**：leaderでfollowerを動かし，RealSense（とDIGIT）を含むepisodeをLeRobotDatasetに保存する．
- **前提**：[Rakuda2：機体設定と読み取り確認](setup.md) が済んでいる．重力補償を使うなら [Rakuda2：重力補償](gravity.md) も済んでいる．
- **所要**：30分〜．
- **結果**：`.roboloom/rakuda2/datasets/rakuda2`（`digit` では `rakuda2-digit`）にepisodeが保存される．

## 1. 準備

収集前に，必要なら [leaderの関節固定と腰yaw相殺](../../controllers/leader.md) を設定します．使用する `leader*.yaml` の `control` と `controller.yaml` の `couplings` を変更します．固定するleader関節は起動前にfollowerへ揃えます．通常・重力補償付き構成のどちらでも使える設定ですが，組み合わせの実機動作は未検証です．

`gravity` だけを有効にした構成は **RealSenseのみ** を記録します．DIGITも記録するときはoption `digit` も有効にします（`--with gravity,digit`）．保存先は自動で `rakuda2-digit` に分かれます．使える組み合わせと制約は [Rakuda2](../../robots/rakuda2/index.md) を参照してください．

followerを動かす前に，機体の安全範囲・低速での追従・停止・脱力を確認し，`nodes/follower.yaml` を `torque: true` に変更します．両腕を支え，dataflow停止状態でEEPROMの確認を済ませてから起動します．

## 2. 起動して収集する

```bash
uv run roboloom validate --with gravity
uv run roboloom run --with gravity
```

`--with` を指定するとlauncherを開きません．launcherから起動する場合は `uv run roboloom` を実行し，robotの一覧で `rakuda2` を選んでから `gravity` にチェックを入れます．

1. robotの状態，sensor取得周期，recorderを確認します．初期姿勢（[home](../../controllers/leader.md)）を設定した場合は，`home` で両方を初期姿勢へ動かしてから始められます．
2. leaderをfollowerに揃え，controllerの `following` を確認します．`aligning` の警告中は，姿勢を合わせてから開始を再試行します．
3. `start pick up the cup` で追従・記録を始め，leaderで操作します．
4. `stop` で止めます．`stop` はfollowerを保持し，脱力はしません．
5. `save` でepisodeを保存に回すか，`discard` で破棄します．Logsで保存完了後の欠損率・指令の有効率・制御周期の警告を確認します．
6. 次の `start <task>` で別episodeを収集できます．
7. 終了時は `stop` → 保存または破棄 → leaderとfollowerの腕を支えて `quit` の順に操作し，確認で保持または支持後の脱力を明示選択します．初期選択はcancelです．

異常時の `estop` はlatchされ，自動復帰しません．物理的な支持・停止手段を使える状態で操作してください．

## 3. 長さを決めて収集する

一定時間の収集は次でも行えます．controllerの準備後，画面の指示に従いEnterで開始します．

```bash
uv run roboloom record --task "pick up the cup" --seconds 30 --episodes 3 --with gravity
```

Pythonからは同じdataflowを使えます．

<span class="status status--mock">模擬のみ</span> [background保存](../../data/recording.md#background-saving) では，既定でepisodeが保存待ちになります．保存後の番号を読むには，確定した結果を待ちます．

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as session:
    session.wait_ready()
    result = session.record("pick up the cup", seconds=30)
    if result.pending:
        (result,) = session.wait_saves()
    print(result.index, result.frames, result.warnings)
```

script終了時も腕の支持が必要です．手動の停止・解放を組み込む場合は [Python API](../../reference/python-api/session.md) を参照してください．

## 4. 保存先とlog

`gravity` だけを有効にしたときの保存先は `.roboloom/rakuda2/datasets/rakuda2` です（`output` は設定YAMLからの相対path）．`digit` を有効にすると `datasets/rakuda2-digit` になります．logは `.roboloom/rakuda2/logs/<dataset name>-<time>/` に残ります．設定・校正・調整のYAMLを管理し，同じ設定・FPS・featureのdatasetへ収集を再開できます．

対話CLIは [Textual操作画面](../../reference/operator-screen.md) を使います．Ctrl-Lで入力，Ctrl-Nでpane移動，Ctrl-Gで非常停止，Ctrl-C/Ctrl-Qで終了確認です．`record --plain` と非TTYはEnter待ちなしで始めます．Python APIは入力を読まないRich表示を維持します．

## 次へ

- 記録を検査し，方策を学習して動かす：[Rakuda2：収集から推論まで](train-infer.md)
- dataの列と欠損の扱い：[dataの形式](../../data/format.md)
