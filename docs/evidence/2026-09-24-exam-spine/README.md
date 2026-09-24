# 模拟考清单 Spine 图标验证 · 2026-09-24

将模拟考入口的原生静态图标换成 Rex 提供的两行清单轮廓，动画和静态态均由同一 SF `checklist` 图标生成。四个部分按上勾、上短线、下圆、下短线的顺序冒出；勾选与小闪光再次强调后停在完整图标，再进入下一轮。仅在悬停播放，无音频。模拟考使用只含清单骨骼的透明离线 WebKit 表面，不再从共享 Mr. B 画布切换，因此没有角色黑圆帧。

[原速交互录像](checklist-loop.mp4)为原生比较窗口的受控图标预览，30 fps 目标、4.19 秒、无音频；它不替代 Rex 在测试 App 中的真实指针手感验收。

验证结果：

- 74 项动效测试通过，其中清单底图与四层像素一致、出现顺序、二次强调、完整态和循环接点均有检查。
- 独立原生 WKWebView 检查通过：离线资源、透明初帧、浅深色、停播清空、没有 Mr. B 骨骼。
- 共享角色渲染器原生回归通过；App 与原型构建通过。
- 原型实看浅色、深色及减少动态；App 中实看静态入口、确认点击进入「知识测验／模拟面试」选择页并返回。隔离数据库 `PRAGMA integrity_check` 返回 `ok`。

随后 Rex 在测试版体验后确认“OK，不错”，授权接入。已将同一代码构建到本机日常 App（`Rex.Review-Today`）并打开，当前入口可从「今天 → 模拟考」进入「知识测验／模拟面试」选择页，返回后仍在今天。日常 App 路径为 `/Users/rexyoung/Library/Developer/Xcode/DerivedData/Review_Today-gkeqhkrlvxqhunchqjqzselqoapv/Build/Products/Debug/Review_Today.app`；这是本机开发签名构建，不是外部发布。构建成功，严格签名校验通过，包内 `ExamEntrySpine.html` 与仓库内容的 SHA-1 一致。

更新前已把旧 App 与 SwiftData 的一致性快照备份到 `/Users/rexyoung/Library/Application Support/Review Today/Backups/before-exam-spine-20260924-194150/`。更新前后数据完整性均为 `ok`，知识 8、会话 2、消息 2、复习轮次 3、复习尝试 3，计数未变。没有启动录音、提交答案或写复习成绩。原有 Jev 测试实例仍使用独立数据库。

自动化没有稳定的纯鼠标悬停动作，故未把日常 App 的自由指针循环列为自动化通过项；Rex 已确认主观动效。完整辅助技术检查未运行。
