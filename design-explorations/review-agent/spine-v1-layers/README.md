# Spine V1 透明图层

## 当前状态

- `core-body-with-resting-arms-v13-1.png`：Rex 已允许沿用的连续核心身体层。
- 来源：`../mascot-spine-rig-decomposition-v13-1-candidate.png` 中央核心身体。
- 处理：只执行机械裁切、连通背景去除和边缘去污染；没有使用 SVG 或代码重画角色。
- Alpha：520 × 800 px；内容边界 415 × 697 px @ (38, 61)；四角透明。
- `headset-band-back-v13-1.png`：后置头梁透明源层；420 × 220 px，内容边界 306 × 123 px @ (69, 51)。
- `headset-earcup-screen-left-v13-1.png`：画面左侧耳罩透明源层；140 × 180 px，内容边界 74 × 117 px @ (23, 36)。
- `headset-earcup-screen-right-v13-1.png`：画面右侧耳罩透明源层；140 × 180 px，内容边界 73 × 118 px @ (45, 35)。
- `eye-open-screen-left-v13-1.png`、`eye-open-screen-right-v13-1.png`：画面左右两颗开眼源层；均为 80 × 80 px。
- `eyes-blink-v13-1.png`：双眼闭合源层；420 × 180 px，内容边界 256 × 44 px @ (138, 73)。
- `bangs-v13-1.png`：刘海源层；240 × 140 px，内容边界 158 × 63 px @ (38, 42)。
- `ahoge-v13-1.png`：呆毛源层；140 × 180 px，内容边界 57 × 81 px @ (43, 42)。

`screen-left`／`screen-right` 始终按用户看到的画面方向命名，避免与角色自身左右混淆。耳机和脸部源层来自验收板的拆件展示区，必须先统一缩放并在核心身体上完成静止重组，才能记录最终 Spine 坐标。

当前耳机静止重组基线见 `../spine-v1-headset-recomposition-v13-1.png`。机械装配参数为：后置头梁 1.45 倍、画面左右耳罩 1.30 倍；Rex 认为当前视觉重量可以沿用。

开眼／眨眼静止重组候选见 `../spine-v1-face-open-recomposition-v13-1.png` 与 `../spine-v1-face-blink-recomposition-v13-1.png`。两张均为 520 × 800 px，内容边界 508 × 747 px @ (3, 11)，四角透明；当前复用 V12.1 闭口嘴型作为位置占位。它们已通过脚本复现与 Alpha 检查，但尚未经过 Rex 的最终视觉确认，也不代表五档嘴型已经迁移完成。

下一步先验收完整脸部静止重组，再补齐五档嘴型并做全部层归位对比。当前目录不代表正式 Spine 工程已经完成。

## 静止重组复现

从项目根目录运行：

```shell
swift brand/render_spine_headset_recomposition.swift \
  design-explorations/review-agent/spine-v1-layers/core-body-with-resting-arms-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/headset-band-back-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/headset-earcup-screen-left-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/headset-earcup-screen-right-v13-1.png \
  design-explorations/review-agent/spine-v1-headset-recomposition-v13-1.png

swift brand/render_spine_face_recomposition.swift \
  design-explorations/review-agent/spine-v1-layers/core-body-with-resting-arms-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/headset-band-back-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/headset-earcup-screen-left-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/headset-earcup-screen-right-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/eye-open-screen-left-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/eye-open-screen-right-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/eyes-blink-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/bangs-v13-1.png \
  design-explorations/review-agent/spine-v1-layers/ahoge-v13-1.png \
  Review_Today/Assets.xcassets/MascotMouthClosed.imageset/mascot-mouth-closed-v12-1.png \
  design-explorations/review-agent/spine-v1-face-open-recomposition-v13-1.png \
  design-explorations/review-agent/spine-v1-face-blink-recomposition-v13-1.png

swift brand/validate_alpha.swift \
  design-explorations/review-agent/spine-v1-layers/*.png \
  design-explorations/review-agent/spine-v1-*-recomposition-v13-1.png
```

耳机与脸部重组脚本只做统一缩放、坐标装配和 Alpha 合成，不生成或重画角色内容。
