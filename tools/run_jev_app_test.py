"""Build and open the real App with Jev and an independent temporary database."""
from pathlib import Path
import json
import os
import socket
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    key_file = Path(os.environ.get("REVIEW_TODAY_JEV_KEY_FILE", str(Path.home() / ".codex/mcp/jev/credentials.json"))).expanduser().resolve()
    if not key_file.is_file():
        raise SystemExit("未找到已有 Jev 凭证文件；未启动测试，也未修改模型配置。")
    directory = Path(tempfile.mkdtemp(prefix="review-today-jev-app-", dir="/tmp"))
    build = Path("/tmp/review-today-jev-native-build")
    with (directory / "build.log").open("w") as log:
        result = subprocess.run([
            "xcodebuild", "-quiet", "-project", str(root / "Review_Today.xcodeproj"),
            "-scheme", "Review_Today", "-configuration", "Debug", "-derivedDataPath", str(build),
            "PRODUCT_BUNDLE_IDENTIFIER=Rex.Review-Today.Jev.NativeQA",
            "INFOPLIST_KEY_CFBundleDisplayName=Review Today · Jev 测试", "build",
        ], cwd=root, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit("测试 App 构建失败，日志：" + str(directory / "build.log"))
    app = build / "Build/Products/Debug/Review_Today.app"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = {
        "REVIEW_TODAY_NATIVE_TEST_DIR": str(directory),
        "REVIEW_TODAY_NATIVE_TEST_PORT": str(port),
        "REVIEW_TODAY_PROJECT_ROOT": str(root),
        "REVIEW_TODAY_JEV_TEST": "1",
        "REVIEW_TODAY_JEV_KEY_FILE": str(key_file),
    }
    command = ["open", "-n", str(app), "--stdout", str(directory / "app.log"), "--stderr", str(directory / "app.log")]
    for name, value in environment.items():
        command += ["--env", name + "=" + value]
    subprocess.run(command, check=True)
    metadata = dict(app=str(app), directory=str(directory), port=port, bundle_id="Rex.Review-Today.Jev.NativeQA")
    (directory / "launch.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata, ensure_ascii=False), flush=True)
    print("已请求打开 Jev 测试 App。底部显示‘Jev 测试已启用’后可输入；关闭该窗口所属 App 即结束本次测试。", flush=True)


if __name__ == "__main__":
    main()
