# PiPER＋Pikaの道筋

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> PiPER，Pika Gripper，Pika Senseのdriverと `roboloom setup` は，模擬のdeviceと偽の機器を使った試験でだけ確かめています．実機で動かしたことはありません．

PiPER 2台に1台ずつPika Gripperを付け，2つのPika Senseで遠隔操作する構成です．[機体を立ち上げる段階](../../explanation/robot-setup-flow.md) の順に並べています．

| 順 | ページ | 段階 | 内容 |
| --- | --- | --- | --- |
| 0 | [模擬で一周する](mock.md) | — | 装置なしで記録，学習，推論までを通す |
| 1 | [機体設定](setup.md) | 1〜3 | `roboloom init piper-pika`，`roboloom setup` で機器を特定し，読み取りで確かめる |
| 2 | [初めての遠隔操作](first-teleop.md) | 4〜5 | 保持を確かめ，home へ動かし，ゆるい設定で遠隔操作する |
| 3 | [設定を絞る](tighten.md) | 6 | `tool_offset` と `workspace` を書き足し，速度を上げる |

構成の詳細は [PiPER](../../robots/piper/index.md)，[Pika Gripper](../../robots/pika/index.md)，[Pika SenseとIK](../../controllers/pose-ik.md) にあります．

## 公式のソフトとの違い

AgileXの公式の遠隔操作（PikaAnyArm の `pika_remote_piper`，ROS Noetic）と同じく，握った瞬間の手と道具の姿勢を基準にした相対の対応（`T_a0 · inv(T_s0) · T_s`）を使い，trackerとrobotの座標の校正はしません．trackerはlibsurvive（SteamVRは使わない）で読みます．公式にない `workspace` は，roboloomが足した任意の安全の制限です．
