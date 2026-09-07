# 北京听写配置

将原始控制台密钥写入此目录的 `.env`（Git 已忽略），参照 `.env.example`。不要写 Markdown 转义字符，不在聊天或日志中回显密钥。Key、Workspace 与地域必须匹配；服务启动时加载，修改后需重启服务。

当前为北京 `fun-asr-flash-2026-06-15`，通过原生 HTTP 调用，无 SDK、OSS 或文字供应商切换。API Key 未配置时明确返回不可用，录音留在本机供重试。

验证：在 agent-service 目录运行 `uv run --no-sync --with pytest python -m pytest tests/test_dictation.py -q`。真实付费验证使用 `tests/dictation_real_smoke.py`，只传非敏感测试录音，输出包含该测试录音的识别文字；不用于真实用户隐私录音的公开日志。

供应商隐私说明：https://help.aliyun.com/zh/model-studio/privacy-notice 。不用于训练并不表示不保存调用数据；本机删除不等于云端即时删除。后续进入海外市场时重新确认地域与该条款。
