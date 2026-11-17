# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0](https://github.com/tetsugo02/roboloom/releases/tag/v0.2.0) - 2026-11-17

### Features

- **hooks**: 方策から独立したフック（周期ごとの step と episode のイベント）を足す ([`bd8e433`](https://github.com/tetsugo02/roboloom/commit/bd8e433d745db97172de2c45cdce6d60db840952))
- PiPER＋Pikaの機器を特定する roboloom setup と，ロボット別のtutorial ([#54](https://github.com/tetsugo02/roboloom/pull/54)) ([`11114ad`](https://github.com/tetsugo02/roboloom/commit/11114ad7bfa4824cfdf836a8a70a3252d40be7c9))

### Documentation

- 日本語docsの英語由来の専門用語を英語表記に統一し，表記方針を記録する ([#55](https://github.com/tetsugo02/roboloom/pull/55)) ([`897cc8b`](https://github.com/tetsugo02/roboloom/commit/897cc8b785b2970e76d92dc46b5d10b93139bd81))

## [0.1.0](https://github.com/tetsugo02/roboloom/releases/tag/v0.1.0) - 2026-11-16

### Features

- 自作方策のための口（観測履歴・hold・別プロセス・記録の再生） ([#26](https://github.com/tetsugo02/roboloom/pull/26)) ([`156a850`](https://github.com/tetsugo02/roboloom/commit/156a85085c901c28bf71d778e0145a953282063d))
- 方策の行動を制御周期に補間する（interpolation_multiplier） ([#21](https://github.com/tetsugo02/roboloom/pull/21)) ([`6fff15e`](https://github.com/tetsugo02/roboloom/commit/6fff15ec01c97a2d9efc1e284efb2ad0e5d65bac))
- 記録する動画の codec を選べるようにし，既定を H.264 にする ([#20](https://github.com/tetsugo02/roboloom/pull/20)) ([`b0cd869`](https://github.com/tetsugo02/roboloom/commit/b0cd86976e53f6ec1485b2236a1242aabfeb7214))
- Web カメラを OpenCV で取得し、OpenCV を共通依存にする ([#17](https://github.com/tetsugo02/roboloom/pull/17)) ([`2100a3b`](https://github.com/tetsugo02/roboloom/commit/2100a3b344a5710391be03b30ff863541d212974))
- 両手の Pika Sense で libsurvive を1つのノードで共有し，トラッカーをシリアル番号で識別する ([#16](https://github.com/tetsugo02/roboloom/pull/16)) ([`f75b77f`](https://github.com/tetsugo02/roboloom/commit/f75b77f12dbed412e6475877ed8a0036fd818e4c))
- ロボットごとの extras に依存を分け，Pika Sense の pysurvive を libsurvive の fork の wheel から入れる ([#15](https://github.com/tetsugo02/roboloom/pull/15)) ([`c87beff`](https://github.com/tetsugo02/roboloom/commit/c87beff02effa7ae356e34235e18752d774287dd))
- allow per-sensor lossless image storage ([#14](https://github.com/tetsugo02/roboloom/pull/14)) ([`3e1c637`](https://github.com/tetsugo02/roboloom/commit/3e1c63707c2a5160e8cdaa5e745b5ccde5e440ad))
- 依存先のプロジェクトのコーディングエージェント向けに Agent Skill を同梱し，docs とコードの食い違いを直す ([#13](https://github.com/tetsugo02/roboloom/pull/13)) ([`64574fc`](https://github.com/tetsugo02/roboloom/commit/64574fc13cc0f2014b31b4fd802cb9f056ffc732))
- Pika Sense を手に持って集め，相対の姿勢の行動に変換する（段階4 a,b，模擬あり，実機未検証） ([#12](https://github.com/tetsugo02/roboloom/pull/12)) ([`5781271`](https://github.com/tetsugo02/roboloom/commit/578127192996715da80902e9916e9a09fd8e9c25))
- 模擬で記録したデータを lerobot-train で学習し，推論までを通す（train の extra，試験，docs） ([#11](https://github.com/tetsugo02/roboloom/pull/11)) ([`abd8a23`](https://github.com/tetsugo02/roboloom/commit/abd8a23e7259a51036ff46a79e27768fd1aa8eee))
- 方策の推論で自作の方策と LeRobot の方策を扱う（模擬あり，実機未検証） ([#10](https://github.com/tetsugo02/roboloom/pull/10)) ([`20010c0`](https://github.com/tetsugo02/roboloom/commit/20010c0de598a47c29693d6c17089b01823ebd00))
- V4L2 の魚眼カメラ（v4l2_rgb）と Pika の手首カメラ（模擬あり，実機未検証） ([#9](https://github.com/tetsugo02/roboloom/pull/9)) ([`67c56f6`](https://github.com/tetsugo02/roboloom/commit/67c56f68d2554645ae64e2cec0faa66af4b0ecb7))
- Pika Sense の入力と IK コントローラで PiPER＋Pika Gripper を遠隔操作する（模擬あり，実機未検証） ([#8](https://github.com/tetsugo02/roboloom/pull/8)) ([`df5fb39`](https://github.com/tetsugo02/roboloom/commit/df5fb39ec8710d53e3094550a659adb6d2cdaa71))
- Pika Gripper のフォロワと，模擬の PiPER＋Pika 構成（実機未検証） ([#7](https://github.com/tetsugo02/roboloom/pull/7)) ([`74ca33b`](https://github.com/tetsugo02/roboloom/commit/74ca33bcb570084133eceb6a6933639457e53070))
- 複数フォロワ，安全に関わる性質の宣言，PiPER の CAN ドライバ（実機未検証） ([#5](https://github.com/tetsugo02/roboloom/pull/5)) ([`2046eed`](https://github.com/tetsugo02/roboloom/commit/2046eedc58c0417c237cabeafd60ea6f03584d76))
- ロボットごとの config.yaml と起動オプション，ランチャー，短いコマンド ([#4](https://github.com/tetsugo02/roboloom/pull/4)) ([`244ed1c`](https://github.com/tetsugo02/roboloom/commit/244ed1c1ab8d41e036ce6b273b120f2bb5564562))
- Rakuda2 バイラテラル制御（力の逆送）段階1〜5（実機未検証） ([#3](https://github.com/tetsugo02/roboloom/pull/3)) ([`292af43`](https://github.com/tetsugo02/roboloom/commit/292af43f5e0e44f968eb6aa4e366396ba4d3954f))
- Textual operator screens for run, record, infer and tune-gravity ([#2](https://github.com/tetsugo02/roboloom/pull/2)) ([`86c9c3c`](https://github.com/tetsugo02/roboloom/commit/86c9c3c3b46d6898e6b8c8a0fd9a9b8f625bf991))
- move leader and follower to a saved home pose; head lead; colored status ([`189a900`](https://github.com/tetsugo02/roboloom/commit/189a900082c39408524f2b635512cd2a40e2ebc2))
- run the Rakuda2 leader and follower at 120 Hz ([`29f64be`](https://github.com/tetsugo02/roboloom/commit/29f64be7de0aa1ef1bfda72379fa1a9bc044aacd))
- check alignment before every start; rename the leader device to rakuda_mini ([`e2f1262`](https://github.com/tetsugo02/roboloom/commit/e2f1262333bafd16c08bede9478b5f03fedac9d9))
- quit can turn the follower torque off ([`ba57898`](https://github.com/tetsugo02/roboloom/commit/ba57898d0eed9e80812944b4c42f6e01c76d47fc))
- lock selected leader joints and compensate head yaw for torso rotation ([`47cfc5c`](https://github.com/tetsugo02/roboloom/commit/47cfc5c3e7d4b15b0a6aa1d1b017e1e98713af9a))
- policy controller node and roboloom infer ([`2ec47a6`](https://github.com/tetsugo02/roboloom/commit/2ec47a6d8b1d4ce009c78db1ab5a2fa8109eb74c))
- Session directs the dora dataflow from Python; roboloom record ([`595564f`](https://github.com/tetsugo02/roboloom/commit/595564fdb55ed091816f5d9ae35ef47bd47464a1))
- Rakuda-2 hardware collection, control laws and operator screen ([`06c12bf`](https://github.com/tetsugo02/roboloom/commit/06c12bf66e45747fc6f5f300e80c332c239a50a7))
- Introduce new robot and sensor modules ([`b62b5ff`](https://github.com/tetsugo02/roboloom/commit/b62b5ff2abe5c1089112bb35e1fbf302100ddc1e))

### Bug Fixes

- 保存したエピソードを，プロセスが落ちても失わない ([#32](https://github.com/tetsugo02/roboloom/pull/32)) ([`2f2c691`](https://github.com/tetsugo02/roboloom/commit/2f2c691e8eb7f4421654aacdbdfd5562db46a99f))
- DIGIT を digit extra に分け，opencv-python-headless に依存する digit-interface の fork を使う ([#18](https://github.com/tetsugo02/roboloom/pull/18)) ([`ba75ca7`](https://github.com/tetsugo02/roboloom/commit/ba75ca78dff6a69cec1b2c804aaaa36aa3634a36))
- YAML が mode: mock のとき，ランチャーの要約に HARDWARE と出さない ([#6](https://github.com/tetsugo02/roboloom/pull/6)) ([`f3fa49b`](https://github.com/tetsugo02/roboloom/commit/f3fa49b86e92d41188f7fe21dcba7743df67144e))
- a leader released by estop or release keeps running instead of crashing ([`00e8db7`](https://github.com/tetsugo02/roboloom/commit/00e8db76f0c451529422cf0b2d19950a150337df))
- pin setup-uv to a published action tag ([`d1529d4`](https://github.com/tetsugo02/roboloom/commit/d1529d4a47cf2e191bb2d8215fb20b8975dda763))
- dataflow nodes use roboloom's own interpreter and dora ([`7b1f1f0`](https://github.com/tetsugo02/roboloom/commit/7b1f1f0e8b14eb61ddaf0b8b6bf39a49f67b8172))
- recorder status crashed on numpy counts; leader watchdog 500 ms ([`3ff6f09`](https://github.com/tetsugo02/roboloom/commit/3ff6f09d5b2f11ed29e3343bb5e5b654b0398061))
- resolve Pyright type errors in runtime and tests ([`dddeb1b`](https://github.com/tetsugo02/roboloom/commit/dddeb1ba47d53b99d9a1f7c74376a056f4e46772))
- warn before starting an unaligned controller ([`0e25870`](https://github.com/tetsugo02/roboloom/commit/0e2587098c206c3e516bd5d464fa273b82ea4094))

### Performance

- cut Dynamixel bus time per control tick ([`dcae63e`](https://github.com/tetsugo02/roboloom/commit/dcae63e626bd00599fd95a8d8c8d692c2764a0aa))

### Refactoring

- setup steps return data and take an Operator; CLI is a thin layer ([`d0af877`](https://github.com/tetsugo02/roboloom/commit/d0af87786f82bfd32c0eea61f5d55314393bf089))

### Documentation

- READMEをOSS標準構成に整理し，Pythonバージョン別CIバッジを追加する ([#50](https://github.com/tetsugo02/roboloom/pull/50)) ([`3ed2097`](https://github.com/tetsugo02/roboloom/commit/3ed20978be25b9a442e994c665ab1116e1fc821c))
- AGENTS.md に他のロボットへの影響とサブエージェントの規則を加える ([`1dfb4f9`](https://github.com/tetsugo02/roboloom/commit/1dfb4f9a74aca234a888d403cb19b723323a2658))
- bilateral control design based on FACTR 2 (not implemented) ([`719da16`](https://github.com/tetsugo02/roboloom/commit/719da1600db87a6e1de130e14349c3c7c741c3f0))
- use uv Git dependencies for user installation ([`1588966`](https://github.com/tetsugo02/roboloom/commit/15889667e349ecae5ae3445974373356e3f1f734))
- Add Roboloom theme styles and language switcher functionality ([`99f93fb`](https://github.com/tetsugo02/roboloom/commit/99f93fb09c950bfaa3b818615e45b49a1e06f36c))
- Python API guide; public names; Session reports failed nodes ([`b6fa80d`](https://github.com/tetsugo02/roboloom/commit/b6fa80d188e74df072f78b70d62145ebc8e629cd))
- update formatting instructions in AGENTS.md and improve code readability in README.md ([`254d898`](https://github.com/tetsugo02/roboloom/commit/254d898d6ba6a32e0f812620ca3a045bfb53d69a))
- gravity tuning guide; README for roboloom init projects; logs next to the experiment ([`fdcccaf`](https://github.com/tetsugo02/roboloom/commit/fdcccaf4948b5b55f4edd4960c3b985cd04661f9))
- right gripper tracking gap was the grasp, confirmed from recorded current ([`5db6c99`](https://github.com/tetsugo02/roboloom/commit/5db6c990349c4a809a894b229a78439167a1b543))

### Tests & Tuning

- 補間の指令周期を，保存のあとではなく記録中に確かめる ([#24](https://github.com/tetsugo02/roboloom/pull/24)) ([`e21c922`](https://github.com/tetsugo02/roboloom/commit/e21c92270e011ceca7f2db1d91584c53d26d222c))
- right leader arm gravity gains and holds ([`78d8f04`](https://github.com/tetsugo02/roboloom/commit/78d8f049a0404464f0d0dfb201f8d723f5904d8a))
- live, joint-by-joint gravity compensation tuning with a guide ([`49b38ac`](https://github.com/tetsugo02/roboloom/commit/49b38ac74215dc20271c58fe4e8033be45592c43))

### CI & Maintenance

- リリースCI/CD・CHANGELOG自動生成・CLI --version・タグ指定インストール手順を追加する ([#53](https://github.com/tetsugo02/roboloom/pull/53)) ([`1e0f1fa`](https://github.com/tetsugo02/roboloom/commit/1e0f1fab54b89e7b22a3fc4713a5952341bd29c6))
- MITライセンスとパッケージメタデータを追加する ([#51](https://github.com/tetsugo02/roboloom/pull/51)) ([`e283c93`](https://github.com/tetsugo02/roboloom/commit/e283c93a0d62eae73782aea507cfad8263619228))
- ソースコード以外の変更でテスト・docs CIを起動しないようトリガーを絞る ([#52](https://github.com/tetsugo02/roboloom/pull/52)) ([`6b7b63d`](https://github.com/tetsugo02/roboloom/commit/6b7b63d51e783388040d875e107f67e0de3c6198))
- E2E テストを手動ワークフロー（e2e.yml）へ分離する ([#46](https://github.com/tetsugo02/roboloom/pull/46)) ([`8fab1e3`](https://github.com/tetsugo02/roboloom/commit/8fab1e35562edced379a26e357b1d43b191b4c63))
- 軽量テストと E2E の分離・並列化，トリガーと AGENTS.md の更新 ([#45](https://github.com/tetsugo02/roboloom/pull/45)) ([`69a203d`](https://github.com/tetsugo02/roboloom/commit/69a203d1c4d2b2abf4e4c9d11804d8e89f2fe3d1))
- deploy bilingual documentation to GitHub Pages ([`415d791`](https://github.com/tetsugo02/roboloom/commit/415d791c12bc1e98f9cc24cb17b3bca7320f70f6))

### Other Changes

- #47・#48 を main に入れる（Python 3.12〜3.14，LeRobot 0.7.0，NumPy の override） ([#49](https://github.com/tetsugo02/roboloom/pull/49)) ([`7cca22e`](https://github.com/tetsugo02/roboloom/commit/7cca22e427eee8ed522aabda7375544bb604452d))
- #33〜#43 を main に入れる（実験ファイル，extends，推論の続行，docs の作り直しなど） ([#44](https://github.com/tetsugo02/roboloom/pull/44)) ([`f24dafd`](https://github.com/tetsugo02/roboloom/commit/f24dafd45ac955a7f629a9c6c6a59baaff561d72))
- #27〜#30 を main に入れる（非同期推論・関節の対応の省略・pchip・Rakuda2 の parts と Pika） ([#31](https://github.com/tetsugo02/roboloom/pull/31)) ([`beabebf`](https://github.com/tetsugo02/roboloom/commit/beabebfd21545ea4d8573537a0fb4f1dabd47087))
- 方策の home と介入（#22・#23）を main に入れる ([#25](https://github.com/tetsugo02/roboloom/pull/25)) ([`839f0a8`](https://github.com/tetsugo02/roboloom/commit/839f0a826f23650368bcf9bd5bd2f7ad229e3bee))
- Support independent sensor selection and PCM/mel audio across robots ([#19](https://github.com/tetsugo02/roboloom/pull/19)) ([`d4959c7`](https://github.com/tetsugo02/roboloom/commit/d4959c73fbc66bfeca27764b220909e9cb1150f4))
- "Claude PR Assistant workflow" ([`56d98cb`](https://github.com/tetsugo02/roboloom/commit/56d98cba19bf3b43efb8fd4047e6580467f15910))
- Enhance live session management and user prompts ([`6a88548`](https://github.com/tetsugo02/roboloom/commit/6a8854857500d1f9406d053a0bb3c8df21f6561a))
- rakuda2 lab unit: gravity tuning from tune-gravity (both arms) ([`ea3390a`](https://github.com/tetsugo02/roboloom/commit/ea3390a47d2eb9f6a79c4e02a9698f4b7dc0ba43))
- roboloom init: per-robot templates in .roboloom/<robot>/, the lab Rakuda-2 moved there ([`87683f3`](https://github.com/tetsugo02/roboloom/commit/87683f309b911183e5a71f07d6e68f0371292288))
- breakaway hold; leader example gains from gravity-check ([`bc31a25`](https://github.com/tetsugo02/roboloom/commit/bc31a25aa4693065ff128808de4d4150c8c0a53d))
- try several multiples of the configured gains per pose ([`e017279`](https://github.com/tetsugo02/roboloom/commit/e017279a778918197cdde18dd7939825aab27aa0))
- show pose, g(q) and sent current at the release; save a trace ([`99be4db`](https://github.com/tetsugo02/roboloom/commit/99be4dbb04f58b1c007031802451689e6e057344))
- release the arm with and without compensation at the same pose and compare drift ([`7502d04`](https://github.com/tetsugo02/roboloom/commit/7502d047a6e87097091d0438d1103ff36011abf6))
- mirror-consistent arm directions, RMS limit on the joints the model explains, elbow on ([`4c58eb1`](https://github.com/tetsugo02/roboloom/commit/4c58eb1e0b1c227ac8026ad731da1d263f25db71))
- leader gravity example: full gain on the shoulders (0.5 sent only ~20-30 mA, too little to feel) ([`2bfd9e8`](https://github.com/tetsugo02/roboloom/commit/2bfd9e87c70154ca2a59ca0115dab2bae7149eda))
- restore .codegraph/ and ignore logs/ on separate lines ([`ae4f15b`](https://github.com/tetsugo02/roboloom/commit/ae4f15b5e8e307fc5d10909e52f08785c9d3049e))
- leader trace: record every control tick and show sent/measured current ([`dca5eae`](https://github.com/tetsugo02/roboloom/commit/dca5eaed8d24f36fce511bd3870786c00e18183f))
- report explained current per joint; compensate only the shoulders for now ([`230fff4`](https://github.com/tetsugo02/roboloom/commit/230fff499a9982ea1c5b9e5b7c07385768b41989))
- one number or one per joint ([`7958ff5`](https://github.com/tetsugo02/roboloom/commit/7958ff599c3ac81978e4988b1e1fec7558ddfd0a))
- leader gravity: a fired bus watchdog freezes goal current, so detect it and keep Current Limit low ([`0e2abee`](https://github.com/tetsugo02/roboloom/commit/0e2abeeac0588bb3c2dc20fb968832eb03df72a2))
- bench test that the Bus Watchdog stops a current-mode motor ([`5601f5e`](https://github.com/tetsugo02/roboloom/commit/5601f5ed7be8e0091b1434ba208584a8ca533dd2))
- record joint travel for current-mode runaway checks ([`5a563f2`](https://github.com/tetsugo02/roboloom/commit/5a563f2384bd10882713caabde51df8bc895951f))
- gravity identification: drop failed measurements robustly and report them ([`d417a29`](https://github.com/tetsugo02/roboloom/commit/d417a29caeb2f6fdcd62858a14832c2708b76d59))
- gravity identification: shared link moments, pose-averaged approaches, stricter acceptance ([`43bcd33`](https://github.com/tetsugo02/roboloom/commit/43bcd33a1413f1a706bc908bd4a7e5268d297725))
- align gravity leader and calibration templates with the probed hardware ([`7da74e2`](https://github.com/tetsugo02/roboloom/commit/7da74e2d3669233585e70090108ffbff2b303f57))
- update .gitignore to include .codegraph and remove extraPaths from VSCode settings ([`67e486f`](https://github.com/tetsugo02/roboloom/commit/67e486fd9e197ae91c8a048b9f4c421d7f8f932e))
- init commit ([`ed428e4`](https://github.com/tetsugo02/roboloom/commit/ed428e4175f17082e541f847a7c0bf8174af2bbc))


