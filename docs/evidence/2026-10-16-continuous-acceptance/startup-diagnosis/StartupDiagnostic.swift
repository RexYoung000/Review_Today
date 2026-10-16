import AppKit
import Foundation

let diagnosticDirectory = URL(fileURLWithPath: "/tmp/review-today-startup-diagnosis-1ux5ch6l")
let qaDirectory = URL(fileURLWithPath: "/tmp/review-today-continuous-bnrjmda_")

final class DiagnosticDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var label: NSTextField!
    var active: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 260),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "启动诊断 · 不调用模型"
        label = NSTextField(wrappingLabelWithString: "正在检查测试窗口启动运行环境的差异…\n不运行学习服务，不发送问题。")
        label.frame = NSRect(x: 28, y: 38, width: 624, height: 185)
        label.font = .systemFont(ofSize: 17)
        window.contentView?.addSubview(label)
        window.center(); window.makeKeyAndOrderFront(nil)
        DispatchQueue.global(qos: .userInitiated).async { self.runDiagnostics() }
    }

    func applicationWillTerminate(_ notification: Notification) { active?.terminate() }

    func runDiagnostics() {
        let service = qaDirectory.appendingPathComponent("owned-project/agent-service")
        let python = service.appendingPathComponent(".venv/bin/python")
        let controlled = #"""
import sys
def guard(event, args):
    if event == 'os.listdir':
        print('DIAG_LISTDIR', repr(args[0]), flush=True)
    if event == 'import':
        name = args[0]
        if name in ('sitecustomize', 'usercustomize'):
            print('DIAG_BLOCKED_CUSTOMIZE', name, flush=True)
            raise ModuleNotFoundError('Diagnostic blocks startup customization', name=name)
        if name == 'bootstrap' or name.startswith('agent_service'):
            raise RuntimeError('Diagnostic prohibits learning service imports')
    if event in ('socket.__new__', 'socket.connect', 'subprocess.Popen', 'os.system'):
        raise RuntimeError('Diagnostic prohibits network and child processes')
sys.addaudithook(guard)
print('DIAG_INTERPRETER_READY', flush=True)
import site
site.main()
print('DIAG_SITE_READY', flush=True)
"""#
        let cases: [(String, [String], URL, String)] = [
            ("native_without_site", ["-S", "-u", "-c", "print('DIAG_INTERPRETER_READY', flush=True)"], diagnosticDirectory, diagnosticDirectory.path),
            ("native_default_empty", ["-u", "-v", "-c", "print('DIAG_DEFAULT_READY', flush=True)"], diagnosticDirectory, diagnosticDirectory.path),
            ("native_controlled_site", ["-S", "-u", "-v", "-c", controlled], service, service.path),
        ]
        var results: [[String: Any]] = []
        for (name, arguments, cwd, pythonPath) in cases {
            DispatchQueue.main.async { self.label.stringValue = "正在检查：\(name)\n每项最多 15 秒；模型请求仍为 0／30。" }
            let process = Process()
            active = process
            let inherited = ProcessInfo.processInfo.environment
            var environment: [String: String] = [
                "PATH": inherited["PATH"] ?? "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": inherited["HOME"] ?? NSHomeDirectory(),
                "TMPDIR": inherited["TMPDIR"] ?? NSTemporaryDirectory(),
                "LANG": inherited["LANG"] ?? "zh_CN.UTF-8", "PYTHONUNBUFFERED": "1", "PYTHONPATH": pythonPath,
            ]
            for key in ["USER", "LOGNAME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"] {
                if let value = inherited[key] { environment[key] = value }
            }
            process.executableURL = python; process.currentDirectoryURL = cwd
            process.arguments = arguments; process.environment = environment
            let stdoutURL = diagnosticDirectory.appendingPathComponent(name + ".stdout")
            let stderrURL = diagnosticDirectory.appendingPathComponent(name + ".stderr")
            FileManager.default.createFile(atPath: stdoutURL.path, contents: nil)
            FileManager.default.createFile(atPath: stderrURL.path, contents: nil)
            let output = try! FileHandle(forWritingTo: stdoutURL)
            let errors = try! FileHandle(forWritingTo: stderrURL)
            process.standardOutput = output; process.standardError = errors
            let started = Date()
            do {
                try process.run()
                try! String(process.processIdentifier).write(to: diagnosticDirectory.appendingPathComponent("active-pid.txt"), atomically: true, encoding: .utf8)
                while process.isRunning && Date().timeIntervalSince(started) < 15 { Thread.sleep(forTimeInterval: 0.05) }
                let timedOut = process.isRunning
                if timedOut { process.terminate() }
                process.waitUntilExit()
                results.append(["case": name, "timed_out": timedOut, "exit": process.terminationStatus,
                                "seconds": Date().timeIntervalSince(started), "pid": process.processIdentifier])
            } catch {
                results.append(["case": name, "launch_error": String(describing: type(of: error))])
            }
            try? output.close(); try? errors.close(); active = nil
            let data = try! JSONSerialization.data(withJSONObject: results, options: [.sortedKeys, .prettyPrinted])
            try! data.write(to: diagnosticDirectory.appendingPathComponent("native-results.json"))
        }
        DispatchQueue.main.async { self.label.stringValue = "启动诊断已结束\n只检查了运行环境，没有运行学习服务。\n模型请求仍为 0／30，原失败与暂停记录保留。" }
    }
}

let application = NSApplication.shared
let delegate = DiagnosticDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
