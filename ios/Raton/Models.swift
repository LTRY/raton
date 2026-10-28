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
    let rating: Int
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

struct Chapter: Codable, Hashable {
    let title: String
    let startSeconds: Double?
}

struct VideoMetadata: Codable, Hashable {
    let description: String?
    let tags: [String]
    let chapters: [Chapter]
    let viewCount: Int?
    let likeCount: Int?
    let commentCount: Int?
    let uploader: String?
}

struct PlaybackPosition: Codable, Hashable {
    let positionSeconds: Double
    let atMs: Int
}

struct ChatMessage: Codable, Hashable {
    let role: String
    let content: String
}

struct VideoDocuments: Codable, Hashable {
    let transcript: String?
    let notes: String?
    let shortSummary: String?
    let suggestedQuestions: [String]
    let chatMessages: [ChatMessage]
}

struct SponsorSegment: Codable, Hashable {
    let category: String
    let startSeconds: Double
    let endSeconds: Double
}

struct SkipSegment: Codable, Hashable {
    let start: Double
    let end: Double
}

struct TranscriptLine: Codable, Hashable {
    let startSeconds: Double
    let text: String
}

struct VideoPlaylistRef: Codable, Hashable {
    let playlistId: Int
    let title: String
    let itemId: Int
}

/// `GET /api/videos/{id}` (`VideoDetailRead`).
struct VideoDetail: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let url: String
    let isNew: Bool
    let rating: Int
    let categories: [String]
    let listState: String?
    // How the fiche is greyed out ("normal", "watched" or "hidden"): decided by the back.
    let shownState: String
    let comment: String?
    let durationSeconds: Int?
    let mediaUrls: MediaURLs
    let metadata: VideoMetadata
    let documents: VideoDocuments
    let sponsorSegments: [SponsorSegment]
    let sponsorSkipEnabled: Bool
    let skipSegments: [SkipSegment]
    let resumePositions: [String: PlaybackPosition]
    let filesPurged: Bool
    let playlists: [VideoPlaylistRef]
    let channel: ChannelRef?
    let hasTranscript: Bool
    let transcriptLines: [TranscriptLine]
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

// MARK: Bibliothèque, chaînes, playlists, Historique

/// `GET /api/library`: one page of cards (the Bibliothèque, or a channel's fiches).
struct LibraryReply: Codable {
    let items: [VideoCard]
    let page: Int
    let totalPages: Int
    let total: Int
}

/// `GET /api/channels` item.
struct ChannelItem: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let rating: Int
    let autoMetadataEnabled: Bool
    let autoShortsEnabled: Bool
    let avatarUrl: String?
    let videoCount: Int
}

struct ChannelsReply: Codable {
    let items: [ChannelItem]
    let page: Int
    let totalPages: Int
    let channelCount: Int
}

/// `PUT /api/channels/{id}/bells/{section}`: the channel with its bells as stored.
struct ChannelBellReply: Codable {
    let channel: ChannelState
}

struct ChannelState: Codable {
    let id: Int
    let autoMetadataEnabled: Bool
    let autoShortsEnabled: Bool
}

struct PlaylistSummary: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let itemCount: Int
    let coverVideoId: Int?
    let coverHasThumbnail: Bool
}

struct PlaylistItem: Codable, Identifiable, Hashable {
    let itemId: Int
    let videoId: Int
    let title: String
    let channelName: String?
    let durationSeconds: Int
    let hasThumbnail: Bool
    let seen: Bool
    var id: Int { itemId }
}

struct PlaylistDetail: Codable {
    let id: Int
    let title: String
    let items: [PlaylistItem]
}

struct HistoryVideo: Codable, Hashable {
    let id: Int
    let title: String
    let rating: Int
}

struct HistoryPlayback: Codable, Hashable {
    let action: String
    let mediaLabel: String
    let title: String
    let progressPercent: Double
    let isCompleted: Bool
}

struct HistoryRow: Codable, Identifiable, Hashable {
    let jobId: Int
    let day: String
    let video: HistoryVideo?
    let channel: ChannelRef?
    let playback: HistoryPlayback
    let watchedSeconds: Double
    let shownState: String
    var id: Int { jobId }
}

struct HistoriqueReply: Codable {
    let rows: [HistoryRow]
    let page: Int
    let totalPages: Int
}

struct CategoryStyle: Codable, Hashable {
    let label: String
    let color: String
}

/// A queued background job (download, LLM request).
struct QueuedJob: Codable {
    let jobId: Int
    let status: String
    let statusUrl: String?
    let conversationId: Int?
}

struct LLMJobStatus: Codable {
    let id: Int
    let status: String
    let message: String?
    let documents: VideoDocuments?
    let chatMessages: [ChatMessage]?
    let libraryChat: LibraryChat?
}

struct LibraryChatCitation: Codable, Hashable {
    let videoId: Int
    let title: String
}

struct LibraryChatMessage: Codable, Hashable {
    let role: String
    let content: String
    let citations: [LibraryChatCitation]
}

struct LibraryChatConversation: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
}

struct LibraryChat: Codable {
    let conversationId: Int?
    let title: String?
    let messages: [LibraryChatMessage]
    let conversations: [LibraryChatConversation]
}

/// `POST /api/raton/visit`: Raton's line for this visit.
struct RatonLine: Codable {
    let line: String
    let art: String
    let ctaLabel: String
    let ctaHref: String
}

struct YoutubeFicheRef: Codable, Hashable {
    let id: Int
    let title: String
}

struct YoutubeVideo: Codable, Identifiable, Hashable {
    let ytVideoId: String
    let title: String
    let url: String
    let channelName: String?
    let durationSeconds: Int?
    let viewCount: Int?
    let thumbnailUrl: String
    let existing: YoutubeFicheRef?
    var id: String { ytVideoId }
}

struct YoutubeChannel: Codable, Identifiable, Hashable {
    let ytChannelId: String
    let name: String
    let handle: String?
    let url: String
    let subscriberCount: Int?
    let thumbnailUrl: String?
    let existing: ChannelRef?
    var id: String { ytChannelId }
}
