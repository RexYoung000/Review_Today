import Foundation
import SQLite3

/// A consistent SQLite backup includes committed WAL content before SwiftData opens it.
enum ReviewMigration {
    static func backupIfNeeded(_ url: URL) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: url.path) else { return }
        let marker = url.appendingPathExtension("review-v2-backup")
        guard !fm.fileExists(atPath: marker.path) else { return }
        let directory = url.deletingLastPathComponent().appendingPathComponent("ReviewBackups", isDirectory: true)
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let backup = directory.appendingPathComponent("before-review-v2-\(UUID().uuidString).sqlite3")
        var source: OpaquePointer?, destination: OpaquePointer?
        defer { sqlite3_close(source); sqlite3_close(destination) }
        guard sqlite3_open_v2(url.path, &source, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              sqlite3_open(backup.path, &destination) == SQLITE_OK,
              let handle = sqlite3_backup_init(destination, "main", source, "main") else { throw ReviewFlowError.saveFailed }
        sqlite3_busy_timeout(source, 5000); sqlite3_busy_timeout(destination, 5000)
        let result = sqlite3_backup_step(handle, -1)
        let finish = sqlite3_backup_finish(handle)
        guard result == SQLITE_DONE, finish == SQLITE_OK else { throw ReviewFlowError.saveFailed }
        // A standalone backup must not require recreating WAL/SHM files when
        // opened read-only for inspection or restore validation.
        guard sqlite3_exec(destination, "PRAGMA journal_mode=DELETE", nil, nil, nil) == SQLITE_OK else {
            throw ReviewFlowError.saveFailed
        }
        try Data(backup.path.utf8).write(to: marker, options: .atomic)
    }
}
