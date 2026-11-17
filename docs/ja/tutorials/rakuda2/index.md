# Rakuda2の道筋

<span class="status status--verified">実機検証済み</span>

Rakuda2を立ち上げてから，収集，学習，推論までの順です．[機体を立ち上げる段階](../../explanation/robot-setup-flow.md) の1〜4は「機体設定と読み取り確認」，5は「teleopで収集」にあたります．

| 順 | ページ | 内容 |
| --- | --- | --- |
| 1 | [機体設定と読み取り確認](setup.md) | 設定を作り，portを読み，torqueを切って経路を一周する |
| 2 | [重力補償](gravity.md) | 零点，可動域，重力modelを測り，leaderの補償を調整する |
| 3 | [teleopで収集](collect.md) | leaderで動かし，RealSenseとDIGITと一緒に記録する |
| 4 | [収集から推論まで](train-infer.md) | 検査，LeRobotで学習，推論，成否の記録までを通す |
| 5 | [介入しながら評価する](intervention.md) | 方策の途中でleaderに代わり，介入した行を区別して記録する |

装置なしで先に試すときは [装置なしで一周する](../first-run-mock.md) から始めます．
