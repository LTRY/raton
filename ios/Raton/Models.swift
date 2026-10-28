import Foundation

// The JSON of the back's `/api`, as far as the screens read it. The decoder converts snake_case
// keys, and ignores every field not listed here.

struct RatonUser: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
}

struct UsersReply: Codable {
    let users: [RatonUser]
    let currentUserId: Int
}

struct ChannelRef: Codable, Hashable {
    let id: Int
    let name: String
}

struct CardPlayback: Codable, Hashable {
    let progressPercent: Double
    let isCompleted: Bool
}

/// A fiche as a list shows it (`LibraryVideoRead`).
struct VideoCard: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let channelName: String?
    let durationSeconds: Int?
    let isNew: Bool
    let hasVideo: Bool
    let hasAudio: Bool
    let hasThumbnail: Bool
    let playback: CardPlayback?
    let shownState: String
}

struct NouveautesStack: Codable, Identifiable, Hashable {
    let channel: ChannelRef
    let items: [VideoCard]
    var id: Int { channel.id }
}

struct NouveautesReply: Codable {
    let stacks: [NouveautesStack]
    let page: Int
    let totalPages: Int
}

struct MediaURLs: Codable, Hashable {
    let video: String?
    let audio: String?
    let thumbnail: String?
}

struct VideoMetadata: Codable, Hashable {
    let description: String?
    let uploader: String?
}

struct PlaybackPosition: Codable, Hashable {
    let positionSeconds: Double
    let atMs: Int
}

/// `GET /api/videos/{id}` (`VideoDetailRead`).
struct VideoDetail: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let isNew: Bool
    let rating: Int
    let listState: String?
    // How the fiche is greyed out ("normal", "watched" or "hidden"): decided by the back.
    let shownState: String
    let durationSeconds: Int?
    let mediaUrls: MediaURLs
    let metadata: VideoMetadata
    let resumePositions: [String: PlaybackPosition]
    let filesPurged: Bool
    let channel: ChannelRef?
}

/// The `PUT`/`POST` replies that carry a fiche's state back; only used to know the call succeeded.
struct VideoState: Codable {
    let id: Int
    let isNew: Bool
    let rating: Int
}

enum MediaKind: String {
    case video
    case audio
}
