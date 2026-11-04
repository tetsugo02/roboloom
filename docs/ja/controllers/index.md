# Controllers

現在のガイドでは，[Leader](leader.md) を使った関節空間のteleoperationを説明します．学習した方策でフォロワを動かすcontrollerは [方策で動かす](policy.md) にあります．

操作入力を読む `inputs`，入力をフォロワへの指令へ変換する `controllers`，モーターに適用する `control` は別の設定です．controllerが動かすフォロワと，フォロワが止まったときの振る舞いは [設定](../reference/configuration.md) の「フォロワとcontroller」を参照してください．機体に対応する入力と組み合わせは [Rakuda2](../robots/rakuda2.md) を参照してください．
