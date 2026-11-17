# Robots

roboloomが動かす機体（follower）の一覧です．機体ごとに，概要，使えるcontroller，sensorのページがあります．

<div class="grid cards" markdown>

-   **[Rakuda2](rakuda2/index.md)** <span class="status status--verified">実機検証済み</span>

    ---

    胴体・頭部と左右の腕の17関節．Rakuda-miniのleader，方策，介入で動かす．

-   **[PiPER](piper/index.md)** <span class="status status--dev">開発中</span>

    ---

    AgileXの6関節の腕．Pika SenseとIK，または方策で動かす．模擬のみ．

-   **[Pika Gripper](pika/index.md)** <span class="status status--dev">開発中</span>

    ---

    PiPERの先に付けるgripper．手首cameraとPika Senseを含む一式．

-   **[自分のrobot](../tutorials/own-robot.md)** <span class="status status--mock">模擬のみ</span>

    ---

    roboloomを変えずに，自分のfollowerのclassとtemplateを足す．

</div>

## 対応表 { #matrix }

| 機体 | Controllerと入力 | sensor |
| --- | --- | --- |
| [Rakuda2](rakuda2/index.md) | Leader <span class="status status--verified">実機検証済み</span>，重力補償付きleader <span class="status status--verified">実機検証済み</span>，方策 <span class="status status--verified">実機検証済み</span>，方策＋介入 <span class="status status--verified">実機検証済み</span>，Pika SenseとIK <span class="status status--dev">開発中</span>（[一覧](rakuda2/controllers.md)） | RealSense <span class="status status--verified">実機検証済み</span>，DIGIT <span class="status status--verified">実機検証済み</span>，音声 <span class="status status--dev">開発中</span>（[一覧](rakuda2/sensors.md)） |
| [PiPER](piper/index.md)＋[Pika Gripper](pika/index.md) | Pika SenseとIK <span class="status status--dev">開発中</span>，方策 <span class="status status--dev">開発中</span>（[一覧](piper/controllers.md)） | RealSense <span class="status status--dev">開発中</span>，Pikaの手首camera <span class="status status--dev">開発中</span> |

方策の種類まで含めた表は [対応表](../get-started/support-matrix.md) にあります．

## 機体を足すとき { #adding }

- roboloomを変えずに足す手順は [自分のrobotを足す](../tutorials/own-robot.md)，roboloom本体に足すときは [新しいfollowerを足す](../contribution/index.md#adding-a-follower) にあります．
- 機体ページには概要，関節と単位，観測と行動，起動option，controllerとsensorのページを置きます．実装の有無と実機での検証を分け，[状態label](../reference/status-labels.md) を付けます．
