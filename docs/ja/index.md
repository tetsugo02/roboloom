# roboloom

roboloomは，ロボットのteleoperationで観測と行動を集め，LeRobotDataset（0.7.0）に保存し，学習した方策で同じロボットを動かすPythonパッケージです．

- **収集**：leaderや手に持つ機器でフォロワを動かし，カメラや触覚と一緒に記録する．
- **学習**：記録をそのまま `lerobot-train` や自作のモデルで学習する．
- **推論と評価**：方策でフォロワを動かし，途中で人が介入し，成否を残す．

各ノードはdora-rsのdataflowで別のプロセスとして動きます．`Session`（操作画面，CLI，Python）がdataflowを起動し，エピソードの開始・停止・保存を送ります．

```mermaid
flowchart LR
  S["Session<br/>操作画面・CLI・Python"]
  I["入力<br/>leader・Pika Sense"] --> C["controller"]
  P["方策"] --> C
  C --> F["フォロワ<br/>Rakuda2・PiPER"]
  X["センサー<br/>RealSense・DIGIT"] --> R["recorder"]
  F --> R
  I --> R
  R --> D[("LeRobotDataset")]
  S -. "start・stop・save" .-> C
  S -.-> R
```

<div class="grid cards" markdown>

-   **[Get started](get-started/installation.md)**

    ---

    インストール，[しくみ](get-started/concepts.md)，[対応表](get-started/support-matrix.md)．

-   **[Tutorials](tutorials/index.md)**

    ---

    装置なしで一周する手順から，Rakuda2の収集・学習・推論まで．

-   **[Robots](robots/index.md)**

    ---

    機体ごとの関節，使えるcontrollerとセンサー．

-   **[Policy](policy/index.md)**

    ---

    方策の書き方，LeRobotの方策，介入，評価．

-   **[Reference](reference/configuration/index.md)**

    ---

    設定のキー，CLI，Python API，データセットの列．

</div>

## 状態ラベル { #status }

機能ごとに，どこまで確かめたかをラベルで示します：<span class="status status--verified">実機検証済み</span> <span class="status status--mock">模擬のみ</span> <span class="status status--dev">開発中</span> <span class="status status--design">設計のみ</span>．定義は [状態ラベル](reference/status-labels.md) にあります．実機のコマンドは，操作者が設定値を照合し，機体ごとに動作を確かめてから使います．模擬の実行やdocsのビルドの成功は，実機の検証ではありません．
