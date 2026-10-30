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
    let publishedAt: String?
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

    private enum CodingKeys: String, CodingKey {
        case id, title, url, isNew, rating, categories, listState, shownState, comment, durationSeconds
        case mediaUrls, metadata, documents, sponsorSegments, sponsorSkipEnabled, skipSegments
        case resumePositions, filesPurged, playlists, channel, hasTranscript, transcriptLines
    }

    /// `shown_state` came with this app: a back that predates it still has to open its fiches, so
    /// the app falls back on the stored choice and shows the automatic state as normal.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        url = try c.decode(String.self, forKey: .url)
        isNew = try c.decode(Bool.self, forKey: .isNew)
        rating = try c.decode(Int.self, forKey: .rating)
        categories = try c.decodeIfPresent([String].self, forKey: .categories) ?? []
        listState = try c.decodeIfPresent(String.self, forKey: .listState)
        shownState = try c.decodeIfPresent(String.self, forKey: .shownState)
            ?? (listState == "watched" || listState == "hidden" ? listState! : "normal")
        comment = try c.decodeIfPresent(String.self, forKey: .comment)
        durationSeconds = try c.decodeIfPresent(Int.self, forKey: .durationSeconds)
        mediaUrls = try c.decode(MediaURLs.self, forKey: .mediaUrls)
        metadata = try c.decode(VideoMetadata.self, forKey: .metadata)
        documents = try c.decode(VideoDocuments.self, forKey: .documents)
        sponsorSegments = try c.decodeIfPresent([SponsorSegment].self, forKey: .sponsorSegments) ?? []
        sponsorSkipEnabled = try c.decodeIfPresent(Bool.self, forKey: .sponsorSkipEnabled) ?? false
        skipSegments = try c.decodeIfPresent([SkipSegment].self, forKey: .skipSegments) ?? []
        resumePositions = try c.decodeIfPresent([String: PlaybackPosition].self, forKey: .resumePositions) ?? [:]
        filesPurged = try c.decodeIfPresent(Bool.self, forKey: .filesPurged) ?? false
        playlists = try c.decodeIfPresent([VideoPlaylistRef].self, forKey: .playlists) ?? []
        channel = try c.decodeIfPresent(ChannelRef.self, forKey: .channel)
        hasTranscript = try c.decodeIfPresent(Bool.self, forKey: .hasTranscript) ?? false
        transcriptLines = try c.decodeIfPresent([TranscriptLine].self, forKey: .transcriptLines) ?? []
    }
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
    // A channel page only: counts, and what "Explorer la suite" imports next.
    let counts: [String: Int]?
    let exploreNextPage: Int?
    let explorePageSize: Int?
}

/// `GET /api/channels/{id}`: the channel with its profile (banner, description, keywords).
struct ChannelDetail: Codable {
    let id: Int
    let url: String
    let name: String
    let rating: Int
    let categories: [String]
    let autoMetadataEnabled: Bool
    let autoShortsEnabled: Bool
    let description: String?
    let keywords: [String]
    let avatarUrl: String?
    let bannerUrl: String?
}

/// `GET /api/jobs/{id}`: the app only waits for `done`.
struct JobProgress: Codable {
    let status: String
    let message: String
    let done: Bool
}

/// `GET /api/channels` item.
struct ChannelItem: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let rating: Int
    let categories: [String]
    let autoMetadataEnabled: Bool
    let autoShortsEnabled: Bool
    let avatarUrl: String?
    let bannerUrl: String?
    let videoCount: Int
    let lastPlayedAt: String?
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
    let source: String
    let categories: [String]
    let freeListening: Bool
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
    let hasAudio: Bool
    let hasVideo: Bool
    let hasThumbnail: Bool
    let seen: Bool
    var id: Int { itemId }
}

struct PlaylistDetail: Codable {
    let id: Int
    let title: String
    let source: String
    let categories: [String]
    let freeListening: Bool
    let items: [PlaylistItem]
    let stats: PlaylistStats?
}

struct PlaylistStats: Codable, Hashable {
    let count: Int
    let totalDurationSeconds: Int
    let seenCount: Int
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

// MARK: Réglages

struct CurfewSettings: Codable {
    let enabled: Bool
    let start: String
    let end: String
    let active: Bool
}

struct RatonLanguage: Codable {
    let address: String
    let nickname: String
}

/// The part of `GET /api/settings` that is the user's own (the rest is administration).
struct UserSettings: Codable {
    let screenTimeLimits: [String: [String: Int]]
    let curfew: CurfewSettings
    let ratonLanguage: RatonLanguage
}

struct ScreenTimeItem: Codable {
    let seconds: Double
    let count: Int
    let limitMinutes: Int
}

struct ScreenTimeReply: Codable {
    let periods: [String: [String: ScreenTimeItem]]
}

extension PlaylistItem {
    func hasFile(_ kind: MediaKind) -> Bool { kind == .audio ? hasAudio : hasVideo }

    var queueTrack: QueueTrack {
        QueueTrack(videoID: videoId, title: title, channelName: channelName, durationSeconds: durationSeconds,
                   hasAudio: hasAudio, hasVideo: hasVideo, hasThumbnail: hasThumbnail)
    }
}
