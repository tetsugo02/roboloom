# Tutorials

目的ごとの手順です．多くは目的，前提，所要，結果，次へ，の順に書いています．labelの意味は [状態label](../reference/status-labels.md) にあります．

```mermaid
flowchart LR
  A["収集<br/>teleop"] --> B["検査<br/>check-dataset"]
  B --> C["学習<br/>lerobot-train"]
  C --> D["推論<br/>roboloom infer"]
  D --> E["評価<br/>label"]
  E --> F["介入しながら収集<br/>policy_teleop"]
  F --> B
```

## はじめの一歩 { #first-steps }

<div class="grid cards gallery" markdown>

-   [![装置なしで一周する](../assets/gallery/first-run-mock.svg)](first-run-mock.md)

    **[装置なしで一周する](first-run-mock.md)**

    examples/mockで起動，記録，検査を一周する．

    <span class="gallery-tags">模擬のRakuda · 15分 · <span class="status status--mock">模擬のみ</span></span>

-   [![自分のrobotを足す](../assets/gallery/own-robot.svg)](own-robot.md)

    **[自分のrobotを足す](own-robot.md)**

    自分のfollowerのclassとtemplateで，模擬の腕を動かす．

    <span class="gallery-tags">自分のrobot · 20分 · <span class="status status--mock">模擬のみ</span></span>

</div>

## Rakuda2 { #rakuda2 }

<div class="grid cards gallery" markdown>

-   [![Rakuda2：機体設定と読み取り確認](../assets/gallery/rakuda2-setup.svg)](rakuda2-setup.md)

    **[Rakuda2：機体設定と読み取り確認](rakuda2-setup.md)**

    設定を作り，portを読み，torqueを切って経路を一周する．

    <span class="gallery-tags">Rakuda2 · 1〜2時間 · <span class="status status--verified">実機検証済み</span></span>

-   [![Rakuda2：重力補償](../assets/gallery/rakuda2-gravity.svg)](rakuda2-gravity.md)

    **[Rakuda2：重力補償](rakuda2-gravity.md)**

    零点，可動域，重力modelを測り，leaderの補償を調整する．

    <span class="gallery-tags">Rakuda2 · 1〜2時間 · <span class="status status--verified">実機検証済み</span></span>

-   [![Rakuda2：teleopで収集](../assets/gallery/rakuda2-collect.svg)](rakuda2-collect.md)

    **[Rakuda2：teleopで収集](rakuda2-collect.md)**

    leaderで動かし，RealSenseとDIGITと一緒に記録する．

    <span class="gallery-tags">Rakuda2 · 30分〜 · <span class="status status--verified">実機検証済み</span></span>

</div>

## 方策 { #policy }

<div class="grid cards gallery" markdown>

-   [![Rakuda2：収集から推論まで](../assets/gallery/rakuda2-train-infer.svg)](rakuda2-train-infer.md)

    **[Rakuda2：収集から推論まで](rakuda2-train-infer.md)**

    検査，LeRobotで学習，推論，成否の記録までを通す．

    <span class="gallery-tags">Rakuda2 · 学習＋1時間 · <span class="status status--verified">実機検証済み</span></span>

-   [![Rakuda2：介入しながら評価する](../assets/gallery/rakuda2-intervention.svg)](rakuda2-intervention.md)

    **[Rakuda2：介入しながら評価する](rakuda2-intervention.md)**

    方策の途中でleaderに代わり，介入した行を区別して記録する．

    <span class="gallery-tags">Rakuda2 · 1時間 · <span class="status status--verified">実機検証済み</span></span>

-   [![自作の方策を動かす](../assets/gallery/custom-policy.svg)](custom-policy.md)

    **[自作の方策を動かす](custom-policy.md)**

    見本のchunk_mlp.pyを模擬の記録で学習し，inferで動かす．

    <span class="gallery-tags">模擬のRakuda2 · 30分 · <span class="status status--mock">模擬のみ</span></span>

</div>

## 開発中の機体 { #in-development }

<div class="grid cards gallery" markdown>

-   [![PiPER＋Pikaを模擬で](../assets/gallery/piper-pika-mock.svg)](piper-pika-mock.md)

    **[PiPER＋Pikaを模擬で](piper-pika-mock.md)**

    模擬のPika SenseとIKで記録し，LeRobotの方策で動かす．

    <span class="gallery-tags">PiPER＋Pika · 30分 · <span class="status status--dev">開発中</span></span>

-   [![Pika Senseを手に持った収集](../assets/gallery/pika-handheld.svg)](pika-handheld.md)

    **[Pika Senseを手に持った収集](pika-handheld.md)**

    robotなしでSenseを手に持って集め，学習用に変換する．

    <span class="gallery-tags">Pika Sense · 30分 · <span class="status status--dev">開発中</span></span>

</div>
