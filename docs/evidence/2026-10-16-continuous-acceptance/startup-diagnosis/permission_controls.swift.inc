    @State private var startupAuthorized = false
    @State private var selectedProjectURL: URL?
    @State private var folderPanel: NSOpenPanel?
    @State private var permissionNotice = "启动已暂停；先选择本项目文件夹，再检查运行环境。"
    @State private var probeRunning = false
    @State private var probeReady = false

    private var projectFolderControls: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(permissionNotice).font(.caption)
            HStack {
                Button("选择 Review_Today 项目文件夹") { chooseProjectFolder() }
                    .disabled(probeRunning || startupAuthorized)
                if selectedProjectURL != nil {
                    Button("检查运行环境（不调用模型）") { Task { await checkInterpreter() } }
                        .disabled(probeRunning || startupAuthorized)
                }
                if probeReady && !startupAuthorized {
                    Button("开始已授权的学习验收") {
                        guard let directory = AppRuntime.current.validationDirectory,
                              !FileManager.default.fileExists(atPath: directory.appendingPathComponent("STOP").path) else {
                            permissionNotice = "环境检查通过；暂停记录仍保留，学习验收尚未启动。"
                            return
                        }
                        record("resume_start")
                        startupAuthorized = true
                        monitor.start()
                    }
                }
            }
        }.padding(.horizontal, 8).padding(.bottom, 8)
    }

    private func chooseProjectFolder() {
        let expected = URL(fileURLWithPath: "/Users/rexyoung/Desktop/vibe coding/Review_Today", isDirectory: true)
        let panel = NSOpenPanel()
        panel.title = "为隔离验收选择项目文件夹"
        panel.message = "仅选择 Review_Today 项目，用于加载运行环境与现有模型配置。选择后先检查环境，不会自动开始模型调用。"
        panel.prompt = "选择此项目"
        panel.canChooseFiles = false; panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false; panel.canCreateDirectories = false
        panel.directoryURL = expected
        folderPanel = panel
        panel.begin { response in
            guard response == .OK, let url = panel.url else {
                permissionNotice = "未授予项目访问；学习服务继续暂停。"
                folderPanel = nil
                return
            }
            guard url.standardizedFileURL.resolvingSymlinksInPath() == expected.standardizedFileURL.resolvingSymlinksInPath() else {
                permissionNotice = "请选择 Review_Today 项目本身；服务仍暂停。"
                folderPanel = nil
                return
            }
            _ = url.startAccessingSecurityScopedResource()
            selectedProjectURL = url
            permissionNotice = "已选择本项目；请先检查运行环境，学习服务仍暂停。"
            record("project_folder_selected")
            folderPanel = nil
        }
    }

    private func checkInterpreter() async {
        guard selectedProjectURL != nil, !probeRunning, !startupAuthorized else { return }
        probeRunning = true; probeReady = false
        permissionNotice = "正在检查依赖目录访问（最多 15 秒）；不运行学习服务。"
        let directory = URL(fileURLWithPath: "/tmp/review-today-startup-diagnosis-1ux5ch6l")
        let qa = AppRuntime.current.validationDirectory!
        let outputURL = directory.appendingPathComponent("permission-probe.stdout")
        let errorURL = directory.appendingPathComponent("permission-probe.stderr")
        FileManager.default.createFile(atPath: outputURL.path, contents: nil)
        FileManager.default.createFile(atPath: errorURL.path, contents: nil)
        let output = try! FileHandle(forWritingTo: outputURL)
        let errors = try! FileHandle(forWritingTo: errorURL)
        let process = Process()
        process.executableURL = qa.appendingPathComponent("owned-project/agent-service/.venv/bin/python")
        process.currentDirectoryURL = directory
        process.arguments = ["-u", "-c", "print('RT.DIAG.PERMISSION_READY', flush=True)"]
        let inherited = ProcessInfo.processInfo.environment
        var environment: [String: String] = [
            "PATH": inherited["PATH"] ?? "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": inherited["HOME"] ?? NSHomeDirectory(), "TMPDIR": inherited["TMPDIR"] ?? NSTemporaryDirectory(),
            "LANG": inherited["LANG"] ?? "zh_CN.UTF-8", "PYTHONUNBUFFERED": "1", "PYTHONPATH": directory.path,
        ]
        for key in ["USER", "LOGNAME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"] {
            if let value = inherited[key] { environment[key] = value }
        }
        process.environment = environment; process.standardOutput = output; process.standardError = errors
        let started = Date()
        do {
            try process.run()
            while process.isRunning && Date().timeIntervalSince(started) < 15 {
                try? await Task.sleep(for: .milliseconds(100))
            }
            let timedOut = process.isRunning
            if timedOut { process.terminate() }
            process.waitUntilExit()
            try? output.close(); try? errors.close()
            let text = (try? String(contentsOf: outputURL, encoding: .utf8)) ?? ""
            probeReady = !timedOut && process.terminationStatus == 0 && text.contains("RT.DIAG.PERMISSION_READY")
            let row: [String: Any] = ["timed_out": timedOut, "exit": process.terminationStatus,
                "seconds": Date().timeIntervalSince(started), "ready": probeReady, "model_calls": 0]
            let data = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .prettyPrinted])
            try! data.write(to: directory.appendingPathComponent("permission-probe-result.json"))
            permissionNotice = probeReady ? "依赖加载检查通过；学习服务尚未启动。" : "依赖加载仍受阻；已停止，不启动学习服务。"
            record(probeReady ? "permission_probe_ready" : "permission_probe_failed")
        } catch {
            try? output.close(); try? errors.close()
            permissionNotice = "运行环境检查未能启动；学习服务继续暂停。"
        }
        probeRunning = false
    }
