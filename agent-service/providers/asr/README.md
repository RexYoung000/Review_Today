# 北京听写配置

将原始控制台密钥写入此目录的 `.env`（Git 已忽略），参照 `.env.example`。不要写 Markdown 转义字符，不在聊天或日志中回显密钥。Key、Workspace 与地域必须匹配；服务启动时加载，修改后需重启服务。

当前为北京 `fun-asr-flash-2026-06-15`，通过原生 HTTP 调用，无 SDK、OSS 或文字供应商切换。API Key 未配置时明确返回不可用，录音留在本机供重试。

验证：在 agent-service 目录运行 `uv run --no-sync --with pytest python -m pytest tests/test_dictation.py -q`。真实付费验证使用 `tests/dictation_real_smoke.py`，只传非敏感测试录音，输出包含该测试录音的识别文字；不用于真实用户隐私录音的公开日志。

供应商隐私说明：https://help.aliyun.com/zh/model-studio/privacy-notice 。不用于训练并不表示不保存调用数据；本机删除不等于云端即时删除。后续进入海外市场时重新确认地域与该条款。

## 连续语音复习（2026-09-23）

`/v2/review` 独立使用北京 `qwen3.8-omni-flash-realtime`。沿用此处的 Key，`REVIEW_TODAY_REALTIME_MODEL` 单独指定；`REVIEW_TODAY_REALTIME_WORKSPACE` 省略时沿用 ASR Workspace。不改变上面的输入框听写和 DeepSeek 配置。官方连接需要 workspace 专用 WSS 地址；Python 依赖包含 SOCKS 代理支持。

Mac 连续送入 PCM16/16k 单声道音频；本机检测停顿、提交原始转写，文字模型按题目绑定标准评价。播放为 PCM24k，服务核对播报文本与本机授权文本一致才释放暂存音频；改写、擅自回答问题或增加保存声明时拦截，仍可用文字继续。暂停、关闭、结束清理临时音频，不生成复习录音文件。

真实付费烟测：`uv run python -m tests.review_voice_live <新的结果文件.json>`（使用 macOS 合成音频，不开启麦克风），文字评价：`uv run python -m tests.review_text_live <新的结果文件.json>`。两者各用临时数据库。原生入口见 `tests/mac/run-review-native.sh`，须先按测试文件启动独立的 review-only 服务。实际结果与局限见 `docs/evidence/2026-09-23-review-voice/README.md`。
