import Foundation
import SQLite3

/// A consistent SQLite backup includes committed WAL content before SwiftData opens it.
enum ReviewMigration {
    /// Use an app-owned path. Import a recognized legacy store without changing it.
    static func prepareStore(legacyURL: URL, directory: URL) throws -> URL {
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let destination = directory.appendingPathComponent("ReviewToday.store")
        guard !fm.fileExists(atPath: destination.path) else { return destination }
        guard fm.fileExists(atPath: legacyURL.path) else { return destination }
        var source: OpaquePointer?, target: OpaquePointer?, query: OpaquePointer?
        defer { sqlite3_finalize(query); sqlite3_close(source); sqlite3_close(target) }
        guard sqlite3_open_v2(legacyURL.path, &source, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              sqlite3_prepare_v2(source, "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('ZKNOWLEDGE','ZAPPSETTINGS')", -1, &query, nil) == SQLITE_OK,
              sqlite3_step(query) == SQLITE_ROW, sqlite3_column_int(query, 0) == 2 else {
            throw ReviewFlowError.saveFailed // Never open or overwrite an unrelated default store.
        }
        let temporary = directory.appendingPathComponent("import-" + UUID().uuidString + ".sqlite3")
        defer { try? fm.removeItem(at: temporary) }
        guard sqlite3_open(temporary.path, &target) == SQLITE_OK,
              let handle = sqlite3_backup_init(target, "main", source, "main") else { throw ReviewFlowError.saveFailed }
        sqlite3_busy_timeout(source, 5000); sqlite3_busy_timeout(target, 5000)
        let result = sqlite3_backup_step(handle, -1), finish = sqlite3_backup_finish(handle)
        guard result == SQLITE_DONE, finish == SQLITE_OK,
              sqlite3_exec(target, "PRAGMA journal_mode=DELETE", nil, nil, nil) == SQLITE_OK else { throw ReviewFlowError.saveFailed }
        sqlite3_close(target); target = nil
        try fm.moveItem(at: temporary, to: destination)
        return destination
    }

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
