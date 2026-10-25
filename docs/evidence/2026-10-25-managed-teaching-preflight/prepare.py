"""Prepare a held clone of the full daily App; never launch App or service."""
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import py_compile
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from common import *


def main():
    assert not (OUT / "setup.json").exists()
    previous_state, previous_pins = unchanged()
    if PRIVATE.exists() or ARCHIVE.exists():
        initial = read(OUT / "initial-preparation-result.json")
        assert initial["actual_model_requests"] == 0 and initial["raw_owned_app_copies_removed"]
        assert sha(Path(initial["initial_app_zip"])) == initial["initial_app_zip_sha256"]
        assert not (ARCHIVE / "ManagedTeachingQA.zip").exists()
    else:
        PRIVATE.mkdir(mode=0o700)
        ARCHIVE.mkdir(mode=0o700, parents=True)
    runtime = Path(tempfile.mkdtemp(prefix="review-today-managed-teaching-", suffix=".noindex", dir="/private/tmp")).resolve()
    runtime.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    assert port != 8742
    batch = str(uuid.uuid4())
    previous_plan = read(ROOT / "docs/evidence/2026-10-24-teaching-scope-fullflow-preflight/plan.json")
    scope = "one App-managed startup and bounded native teaching check in a fresh isolated full-App clone; no daily writes, saving, web or manual service startup"
    gates = [dict(id="app_managed_startup", estimated_model_requests=8,
        action="从真实完整 App 入口冷启动；8742 和本批端口都无现存监听，不独立启动 Python",
        pass_criteria="记录 App PID、服务 PID 与真实父进程路径；一次准入，三角色／教学两档流式就绪；输入尚未发送、原生空库；不可借用旧服务或旧就绪")]
    gates += [g for g in previous_plan["gates"] if g["id"] in {"lesson", "partial_answer", "complete_answer"}]
    gates += [dict(id="native_experience_and_disk", estimated_model_requests=0,
        action="同一窗口核对浅色默认尺寸及深色最小内容区、键盘焦点、逐字讲解与题面完整性，正常退出并新进程读隔离盘",
        pass_criteria="无截断遮挡、题目只出现一次、漏答未认证、补答只认证真实概念；预览仍未保存，零卡／来源／复习，原步骤和整节理解保持真实未知；消息／Run 与服务一致；退出 App 后托管子进程退出、无新监听或后续调用")]
    plan = dict(status="PREPARED_PENDING_NEW_20_0", decision=274, date="2026-10-25", batch_id=batch, scope=scope,
        model_request_limit=20, provider_web_operation_limit=0, startup_estimate=8, path_estimate=15, reserve_within_limit=5,
        first_input=previous_plan["first_input"], required_concepts=previous_plan["required_concepts"], gates=gates,
        counting="所有真实 SDK 请求含启动、格式与教学有界修复、重试、后台和失败均计数；所有 provider 搜索／读取／网页兜底禁止。次数不是金额上限。",
        stop_conditions=["启动首次探测失败，禁止新请求，不手动重新探测或重启",
            "任一功能关最终失败、需改代码／数据库／替换输出／重新启动才能继续", "任一上限到限，后续请求拒绝，在途回执留存",
            "正式数据、源码、旧证据、版本归属或持久化保护不符"],
        existing_bounded_repairs_allowed_and_counted=True, formal_app_kept_closed=True,
        proposed_clone="same full App executable and ContentView/AgentServiceMonitor machine code, separate NativeQA identity/data/root and ad-hoc signature",
        difference_from_daily_identity="验证完整 App 托管实现及隔离体验；不代验正式签名身份的系统目录权限、日常数据恢复或 Rex 最终体验",
        excluded=["日常 App 更换／启动和正式库写入", "知识卡保存、独立插问及完整保存链重跑", "网页和所有旧额度恢复", "通用教学质量、完整 VoiceOver、跨系统或 M1 总验收"],
        expected_environment=dict(platform="macOS", version=platform.mac_ver()[0], architecture=platform.machine(),
            default_content=[1280, 820], minimum_content=[760, 620], appearances=["light", "dark"],
            size_evidence="记录实际外窗和内容区尺寸；无法达到目标时不能写通过", interaction="真实完整主界面输入与控件；原速观察／录像，语义、服务与退出磁盘相互核对"),
        real_credentials_and_app_child_directory_permissions_not_yet_verified=True,
        prior_273_8_0_closed=True, all_old_allowances_frozen=True)
    write(OUT / "plan.json", plan)
    service = runtime / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    real = ROOT / "agent-service"
    (service / ".venv/bin/python").symlink_to(real / ".venv/bin/python")
    shutil.copy2(real / ".venv/pyvenv.cfg", service / ".venv/pyvenv.cfg")
    (service / ".venv/lib").symlink_to(real / ".venv/lib", target_is_directory=True)
    site = service / "sitecustomize.py"
    site.write_text("import os,sys\nsys.dont_write_bytecode=True\n_admitted=False\n"
        "def _audit(event,args):\n    if not _admitted and event in {'sqlite3.connect','socket.connect'}:raise PermissionError('Pending runtime access')\n"
        "sys.addaudithook(_audit)\ntry:\n" +
        f"    os.environ['REVIEW_TODAY_REVIEW_DB']={str(runtime / 'review.sqlite3')!r}\n" +
        f"    sys.path.insert(0,{str(real)!r})\n    sys.path.insert(0,{str(OUT)!r})\n" +
        f"    import bootstrap\n    bootstrap.check_approved({str(runtime)!r},{str(ROOT)!r})\n" +
        f"    _admitted=True\n    bootstrap.install({str(runtime)!r},{str(ROOT)!r})\n" +
        "except BaseException as error:\n    print('QA_BOOTSTRAP_FAILED:'+type(error).__name__,flush=True)\n    os._exit(74)\n")
    py_compile.compile(str(site), doraise=True)
    app = runtime / "ManagedTeachingQA.app"
    shutil.copytree(DAILY, app)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    original_id = info["CFBundleIdentifier"]
    info.update(CFBundleIdentifier="Rex.Review-Today.ManagedTeaching.NativeQA",
                CFBundleName="Review Today 托管首启隔离", CFBundleDisplayName="Review Today 托管首启隔离")
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    before_text = {p.name: text_section(p) for p in (DAILY / "Contents/MacOS").iterdir() if p.is_file()}
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    assert {p.name: text_section(p) for p in (app / "Contents/MacOS").iterdir() if p.is_file()} == before_text
    resources = {str(p.relative_to(DAILY)): sha(p) for p in (DAILY / "Contents/Resources").rglob("*") if p.is_file()}
    assert all(sha(app / p) == digest for p, digest in resources.items())
    package = ARCHIVE / "ManagedTeachingQA.zip"
    app_inventory = inventory(app)
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(package)], check=True)
    extracted = runtime / "archive-check.noindex"
    extracted.mkdir()
    subprocess.run(["ditto", "-x", "-k", str(package), str(extracted)], check=True)
    assert inventory(extracted / app.name) == app_inventory
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(extracted / app.name)], check=True)
    for path in [app, extracted / app.name]:
        result = subprocess.run([LS, "-u", str(path)], capture_output=True)
        assert result.returncode in {0, 1}
    registrations = subprocess.check_output([LS, "-dump"], text=True)
    assert str(app) not in registrations and str(extracted / app.name) not in registrations
    shutil.rmtree(extracted)
    shutil.rmtree(app)
    native_home = runtime / "native-home"
    native_home.mkdir()
    prior_records = files(PRIOR)
    for name in ["actual-runtime", "actual-public-records"]:
        for suffix in [".zip", "-manifest.json"]:
            path = PREVIOUS_ARCHIVE / (name + suffix)
            prior_records[str(path)] = sha(path)
    for name in ["authorization.json", "quota.json", "STOP"]:
        path = PREVIOUS_ACTIVATION / name
        prior_records[str(path)] = sha(path)
    state = dict(status="PREPARED_HOLD_ARCHIVED", decision=274, directory=str(runtime), port=port,
        batch_id=batch, scope=scope, baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        native_app=str(app), native_zip=str(package), native_zip_sha256=sha(package), native_inventory=app_inventory,
        native_environment=dict(REVIEW_TODAY_NATIVE_TEST_DIR=str(runtime), REVIEW_TODAY_NATIVE_TEST_PORT=str(port),
            REVIEW_TODAY_PROJECT_ROOT=str(runtime / "owned-project"), REVIEW_TODAY_JEV_TEST="0", CFFIXED_USER_HOME=str(native_home)),
        native_executable_text_sha256=before_text, original_bundle_id=original_id,
        native_bundle_id=info["CFBundleIdentifier"], exact_full_app_not_custom_qa_shell=True,
        native_resources_matched=len(resources), native_archive_extracted_strictly_verified=True, raw_qa_app_removed=True,
        protected_fingerprints=previous_pins, prior_records=prior_records,
        daily_files=files(SUPPORT), daily_app_inventory=inventory(DAILY), user_project_diff_sha256=previous_state["project_diff_sha256"],
        known_missing_old_paths=previous_state["known_missing_old_paths"],
        native_store_absent=not (runtime / "app.store").exists(), service_store_absent=not (runtime / "checkpoint.sqlite3").exists(),
        prior_guard_sha256=sha(ROOT / "docs/evidence/2026-10-21-learning-save-preflight/quota.py"),
        sitecustomize_sha256=sha(site), actual_model_requests=0, actual_web_operations=0,
        app_launched=False, service_started=False, authorization_confirmed=False)
    write(OUT / "setup.json", state)
    pins = dict(previous_pins)
    for path in list(OUT.glob("*.py")) + [OUT / "plan.json", OUT / "setup.json"]:
        pins[str(path.relative_to(ROOT))] = sha(path)
    write(OUT / "source-pins.json", pins)
    write(runtime / "authorization.json", dict(status="pending", batch_id=batch, actual_model_request_limit=20,
        provider_web_operation_limit=0, scope=scope, plan_sha256=sha(OUT / "plan.json"), source_pins_sha256=sha(OUT / "source-pins.json")))
    (runtime / "HOLD").write_text("Preparation only. New 20/0 App-managed teaching batch requires explicit approval. All old allowances remain frozen.\n")
    write(PRIVATE / "runtime-pins.json", files(runtime))
    unchanged()
    print("Prepared exact-code full-App NativeQA clone, verified ZIP and empty runtime; App/service not launched, real 0/0, pending new 20/0.")


if __name__ == "__main__":
    main()
