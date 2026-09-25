import Foundation
import SQLite3

@main struct ReviewMigrationContractTests {
    static func main() throws {
        let folder = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("review-today-wal-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appendingPathComponent("test.sqlite3")
        var db: OpaquePointer?
        precondition(sqlite3_open(url.path, &db) == SQLITE_OK)
        defer { sqlite3_close(db) }
        precondition(sqlite3_exec(db, "PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE fixture(value TEXT); INSERT INTO fixture VALUES ('preserved');", nil, nil, nil) == SQLITE_OK)
        precondition(FileManager.default.fileExists(atPath: url.path + "-wal"))
        try ReviewMigration.backupIfNeeded(url)
        let marker = url.appendingPathExtension("review-v2-backup")
        let backup = try String(contentsOf: marker, encoding: .utf8)
        var saved: OpaquePointer?; precondition(sqlite3_open_v2(backup, &saved, SQLITE_OPEN_READONLY, nil) == SQLITE_OK)
        defer { sqlite3_close(saved) }
        var query: OpaquePointer?
        precondition(sqlite3_prepare_v2(saved, "SELECT value FROM fixture", -1, &query, nil) == SQLITE_OK, String(cString: sqlite3_errmsg(saved)))
        defer { sqlite3_finalize(query) }
        precondition(sqlite3_step(query) == SQLITE_ROW && String(cString: sqlite3_column_text(query, 0)) == "preserved")
        try ReviewMigration.backupIfNeeded(url)
        let repeated = try String(contentsOf: marker, encoding: .utf8)
        precondition(repeated == backup)
        let corrupt = folder.appendingPathComponent("corrupt.sqlite3"); try Data("not a database".utf8).write(to: corrupt)
        do { try ReviewMigration.backupIfNeeded(corrupt); preconditionFailure("corrupt backup must stop migration") } catch {}
        precondition(!FileManager.default.fileExists(atPath: corrupt.appendingPathExtension("review-v2-backup").path))
        let owned = folder.appendingPathComponent("owned")
        do { _ = try ReviewMigration.prepareStore(legacyURL: url, directory: owned); preconditionFailure("foreign store must be rejected") } catch {}
        precondition(!FileManager.default.fileExists(atPath: owned.appendingPathComponent("ReviewToday.store").path))
        precondition(sqlite3_exec(db, "CREATE TABLE ZKNOWLEDGE(value TEXT); CREATE TABLE ZAPPSETTINGS(value TEXT); INSERT INTO ZKNOWLEDGE VALUES ('preserved');", nil, nil, nil) == SQLITE_OK)
        let migrated = try ReviewMigration.prepareStore(legacyURL: url, directory: owned)
        precondition(FileManager.default.fileExists(atPath: migrated.path))
        precondition(FileManager.default.fileExists(atPath: url.path))
        let same = try ReviewMigration.prepareStore(legacyURL: corrupt, directory: owned)
        precondition(same == migrated)
        var migratedDB: OpaquePointer?, migratedQuery: OpaquePointer?
        precondition(sqlite3_open_v2(migrated.path, &migratedDB, SQLITE_OPEN_READONLY, nil) == SQLITE_OK)
        defer { sqlite3_finalize(migratedQuery); sqlite3_close(migratedDB) }
        precondition(sqlite3_prepare_v2(migratedDB, "SELECT value FROM ZKNOWLEDGE", -1, &migratedQuery, nil) == SQLITE_OK)
        precondition(sqlite3_step(migratedQuery) == SQLITE_ROW && String(cString: sqlite3_column_text(migratedQuery, 0)) == "preserved")
        print("PASS: owned store migration preserves WAL and legacy source, rejects foreign store, reopens idempotently")
        print("PASS: backup includes committed WAL, repeats are idempotent, backup failure cannot mark migration ready")
    }
}
