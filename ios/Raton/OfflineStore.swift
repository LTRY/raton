import Foundation
import UIKit

/// A fiche's audio kept on the phone for listening without the server.
struct OfflineItem: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let channel: String?
    let duration: Int
    /// The file's name inside the offline folder.
    let file: String
}

/// The audio files downloaded for offline listening, and the small index that remembers what they are.
/// The files are copies of what the back serves (`/api/videos/{id}/audio`): the back stays the only
/// owner of the media, and a purge on the server does not touch these.
final class OfflineStore: ObservableObject {
    static let shared = OfflineStore()

    @Published private(set) var items: [OfflineItem] = []
    @Published private(set) var downloading: Set<Int> = []
    /// How far each running download is, from 0 to 1.
    @Published private(set) var progress: [Int: Double] = [:]

    private let folder: URL
    private var indexURL: URL { folder.appendingPathComponent("index.json") }

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        var folder = base.appendingPathComponent("Offline", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        // Everything here can be downloaded again: keep it out of the iCloud backup.
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? folder.setResourceValues(values)
        self.folder = folder
        if let data = try? Data(contentsOf: folder.appendingPathComponent("index.json")),
           let saved = try? JSONDecoder().decode([OfflineItem].self, from: data) {
            items = saved.filter { FileManager.default.fileExists(atPath: folder.appendingPathComponent($0.file).path) }
        }
    }

    func item(_ id: Int) -> OfflineItem? { items.first { $0.id == id } }

    func fileURL(_ item: OfflineItem) -> URL { folder.appendingPathComponent(item.file) }

    /// The local file of a fiche's audio, when it was downloaded.
    func localAudio(for id: Int) -> URL? { item(id).map(fileURL) }

    @MainActor
    func download(detail: VideoDetail, api: RatonAPI) async throws {
        guard let path = detail.mediaUrls.audio else { return }
        try await download(id: detail.id, title: detail.title, channel: detail.channel?.name,
                           duration: detail.durationSeconds ?? 0, path: path, api: api)
    }

    /// Copies an audio the back serves at `path` onto the phone. `progress` follows it, from 0 to 1.
    @MainActor
    func download(id: Int, title: String, channel: String?, duration: Int, path: String, api: RatonAPI) async throws {
        guard !downloading.contains(id) else { return }
        downloading.insert(id)
        progress[id] = 0
        // A little time to finish when the app goes to the background; iOS still ends a long download
        // there (then it fails and can be asked again).
        let grace = UIApplication.shared.beginBackgroundTask(withName: "offline-\(id)")
        defer {
            downloading.remove(id)
            progress[id] = nil
            UIApplication.shared.endBackgroundTask(grace)
        }
        let watcher = DownloadWatcher { [weak self] fraction in
            Task { @MainActor in if self?.downloading.contains(id) == true { self?.progress[id] = fraction } }
        }
        let (temporary, response) = try await URLSession.shared.download(from: api.url(path), delegate: watcher)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw OfflineError.refused
        }
        let ext = (response.suggestedFilename.map { ($0 as NSString).pathExtension } ?? "").nonEmpty ?? "m4a"
        let name = "\(id).\(ext)"
        let destination = folder.appendingPathComponent(name)
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: temporary, to: destination)
        let item = OfflineItem(id: id, title: title, channel: channel, duration: duration, file: name)
        items.removeAll { $0.id == id }
        items.insert(item, at: 0)
        save()
    }

    @MainActor
    func remove(_ id: Int) {
        guard let item = item(id) else { return }
        try? FileManager.default.removeItem(at: fileURL(item))
        items.removeAll { $0.id == id }
        save()
    }

    private func save() {
        try? JSONEncoder().encode(items).write(to: indexURL, options: .atomic)
    }
}

/// Reports how far one download is, as the system counts it.
private final class DownloadWatcher: NSObject, URLSessionTaskDelegate {
    private let report: (Double) -> Void
    private var observation: NSKeyValueObservation?

    init(report: @escaping (Double) -> Void) { self.report = report }

    func urlSession(_ session: URLSession, didCreateTask task: URLSessionTask) {
        observation = task.progress.observe(\.fractionCompleted) { [report] progress, _ in
            report(progress.fractionCompleted)
        }
    }
}

enum OfflineError: LocalizedError {
    case refused
    var errorDescription: String? { "Le serveur n'a pas pu envoyer l'audio." }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
