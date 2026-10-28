import Foundation

/// A playlist row as the queue sees it: what decides if it can be played, and what the lock screen shows.
struct QueueTrack: Equatable, Identifiable {
    let videoID: Int
    let title: String
    let channelName: String?
    let durationSeconds: Int
    let hasAudio: Bool
    let hasVideo: Bool
    let hasThumbnail: Bool
    var id: Int { videoID }

    func hasFile(_ kind: MediaKind) -> Bool { kind == .audio ? hasAudio : hasVideo }
}

/// The order a playlist plays in: the rules of the web's playlist player
/// (`front/static/js/playlist-player.js`) — a track without the file of the chosen mode is skipped,
/// shuffle does not repeat before everything was played, "previous" walks back through what was played.
struct PlaylistQueue {
    let playlistID: Int
    let title: String
    /// Free listening: nothing is reported to the history.
    let free: Bool
    var tracks: [QueueTrack]
    var mode: MediaKind
    var shuffle: Bool
    var loop: Bool
    private(set) var current: Int?
    private var history: [Int] = []
    private var shuffleSeen: Set<Int> = []

    init(playlistID: Int, title: String, free: Bool, tracks: [QueueTrack], mode: MediaKind, shuffle: Bool, loop: Bool) {
        self.playlistID = playlistID
        self.title = title
        self.free = free
        self.tracks = tracks
        self.mode = mode
        self.shuffle = shuffle
        self.loop = loop
    }

    var eligible: [QueueTrack] { tracks.filter { $0.hasFile(mode) } }

    var currentTrack: QueueTrack? { tracks.first { $0.videoID == current } }

    /// 1-based place of the current track in the whole playlist.
    var currentNumber: Int? { tracks.firstIndex { $0.videoID == current }.map { $0 + 1 } }

    /// The user picked this track: it becomes the current one.
    mutating func pick(_ videoID: Int) {
        if let current, current != videoID { history.append(current) }
        shuffleSeen.insert(videoID)
        current = videoID
    }

    /// The track that follows the current one, or nil at the end of a queue that does not loop.
    mutating func next() -> QueueTrack? {
        let candidates = eligible
        guard !candidates.isEmpty else { return nil }
        let chosen = shuffle ? randomNext(candidates) : orderedNext(candidates)
        if let chosen { pick(chosen.videoID) }
        return chosen
    }

    /// The track before the current one (shuffle: the one played before), or nil when there is none.
    mutating func previous() -> QueueTrack? {
        let candidates = eligible
        var found: QueueTrack?
        if shuffle {
            while let last = history.popLast(), found == nil {
                found = candidates.first { $0.videoID == last }
            }
        } else if let index = candidates.firstIndex(where: { $0.videoID == current }) {
            found = index > 0 ? candidates[index - 1] : (loop ? candidates.last : nil)
        }
        if let found {
            current = found.videoID
            shuffleSeen.insert(found.videoID)
        }
        return found
    }

    /// The rows changed (order, files, removal): keep playing the same track when it is still there.
    mutating func update(tracks newTracks: [QueueTrack]) {
        tracks = newTracks
        let ids = Set(newTracks.map(\.videoID))
        history.removeAll { !ids.contains($0) }
        if let current, !ids.contains(current) { self.current = nil }
    }

    private func orderedNext(_ candidates: [QueueTrack]) -> QueueTrack? {
        if let index = candidates.firstIndex(where: { $0.videoID == current }) {
            if index + 1 < candidates.count { return candidates[index + 1] }
            return loop ? candidates[0] : nil
        }
        // The current track is not playable in this mode: the next playable one after its place.
        let start = tracks.firstIndex { $0.videoID == current } ?? -1
        let later = tracks.enumerated().first { $0.offset > start && $0.element.hasFile(mode) }?.element
        return later ?? (loop ? candidates[0] : nil)
    }

    private mutating func randomNext(_ candidates: [QueueTrack]) -> QueueTrack? {
        var pool = candidates.filter { !shuffleSeen.contains($0.videoID) && $0.videoID != current }
        if pool.isEmpty {
            guard loop else { return nil }
            shuffleSeen = current.map { [$0] } ?? []
            pool = candidates.filter { $0.videoID != current }
            if pool.isEmpty { pool = candidates }
        }
        return pool.randomElement()
    }
}
