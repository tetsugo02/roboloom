# 方策サーバー <span class="status status--mock">模擬のみ</span>

方策を，roboloomとは別のプロセス・別の環境で動かす方法です．キーの一覧は [方策の設定](../reference/configuration/policy.md#backend)，コマンドは [CLI](../reference/cli.md#serve-policy) にあります．

## 方策を別のプロセスで動かす { #running-the-policy-in-another-process }

方策を読み込む場所は2通りあり，方策のYAMLの `backend` で選びます．方策の書き方（`bind`，`reset`，`infer`，`options`）はどちらも同じです．

| `backend` | 方策を読み込むプロセス | 使う場面 |
| --- | --- | --- |
| `process`（既定） | 方策ノード自身 | 方策の依存関係がroboloomの環境に入る．サーバーの起動が要らない |
| `server` | 別に起動した方策サーバー | 依存関係が入らないモデル（torchの版が違うなど），別のマシンで動かすモデル |

```yaml
# nodes/policy.yaml
factory: my_lab.policies:load        # どちらの backend でも，方策そのものを書く
kwargs: {checkpoint: "..."}
backend: server                      # 省略すると process
server: {address: "127.0.0.1:18765"} # backend: server のときだけ読む
```

`backend: server` では，方策ノードは `factory` を読み込まず，`server.address` へつなぎます．サーバーは同じYAMLから `factory`，`kwargs`，`server.address` を読んで起動します．

## サーバーを起動する { #starting-the-server }

```bash
# モデルのある側：そのモデルの環境．roboloomはextraなしで入れる
export ROBOLOOM_POLICY_AUTHKEY=some-shared-secret
uv run roboloom serve-policy --experiment configs/roboloom/drawer.yaml   # 実験ファイルの方策
# 方策のYAMLから：roboloom serve-policy --from .roboloom/rakuda2/nodes/policy.yaml
# roboloomのコマンドを使わない場合：python -m roboloom.policy.remote --from <同じファイル>
# YAMLを使わない場合：roboloom serve-policy my_lab.policies:load --kwargs '{"checkpoint": "..."}'
```

| `server` のキー | 意味 |
| --- | --- |
| `address` | `host:port`（既定 `127.0.0.1:18765`） |
| `timeout_s` | `infer` 1回の上限（既定30秒） |
| `connect_timeout_s` | サーバーの起動を待つ上限（既定30秒） |
| `authkey_env` | 秘密の文字列を読む環境変数（既定 `ROBOLOOM_POLICY_AUTHKEY`）．roboloomを動かす環境にも同じ値が要る |

- `factory` のモジュールと `kwargs` の相対パスは，サーバーを起動したディレクトリと環境で解決します．
- `backend: server` では `roboloom infer --policy`・`--policy-kwargs` は使えません（方策を読み込むのはサーバーです）．
- `factory: roboloom.policy.remote:connect` と `kwargs: {address: ...}` を直接書く以前の形も動きます．

## サーバーの動き { #behavior }

- サーバーはモデルを1回だけ読み込み，方策ノードを1つずつ相手にします．エピソードやセッションをまたいで使えます．`roboloom infer` より先に起動してください．ノードは `connect_timeout_s`（30秒）まで待ちます．1つを相手にしている間につないできた2つ目のノードには，待たせずに，使用中であること（`the policy server is serving another policy node`）を返します．
- `timeout_s` 以内に答えがない呼び出しは，そのエピソードを失敗させます（`TimeoutError`）．あとから届いたその答えは捨てます．呼び出しには番号が付いていて，同じ番号の答えだけを受け取ります．
- サーバー側に要るのは，numpyとextraなしのroboloomだけです（LeRobotも，roboloomが入れるtorchも要りません）．
- 方策が出した例外は，同じプロセスの方策と同じく，controllerの行に出ます（[失敗したとき](custom.md#failures)）．
- 共有する秘密の文字列で両側を認証します．通信は暗号化しません．アドレスはループバックか，信頼できるネットワークにしてください．メッセージはJSONのヘッダと配列の生のバイト列です（pickleは使いません）．
- ネットワーク越しでは，`infer` のたびに観測を送ります（480×640の画像1枚で約0.9 MB，`observation_history` の枚数分）．
