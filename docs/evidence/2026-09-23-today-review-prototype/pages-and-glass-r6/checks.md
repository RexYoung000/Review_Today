# 定向工程检查

2026-09-23，本轮运行：

```sh
xcrun swiftc -parse-as-library -swift-version 5 -default-isolation MainActor \
  tools/today-review-prototype/PrototypeState.swift \
  tests/mac/TodayReviewPrototypeContracts.swift \
  -o /tmp/today-review-prototype-contracts
/tmp/today-review-prototype-contracts
```

实际结果：退出码 0，`50 prototype state checks passed. No models, microphone, database or FSRS used.`

新增四项：直接打开独立部分小结并继承外观；完整示例采用既有 Spine 收尾；显式重播归零时间；切换示例、重播和关闭均不改变原暂停轮次的队列、结果、题目索引。其余 46 项覆盖队列、帮助、失败、纠正、关闭、迟到与收尾条件。

最终构建和签名检查：

```sh
bash tests/mac/run-today-review-prototype.sh
codesign --verify --deep --strict output/today-review-prototype/TodayReviewPrototype.app
git diff --check
```

均退出码 0。UI 排版、焦点、实际点击及原速动效另见本目录 README；状态检查不等于视觉验收。
