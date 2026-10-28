import AVFoundation
import Combine
import MediaPlayer
import UIKit

/// The one player of the app (video or audio), kept alive above the screens so that audio goes on
/// when the fiche is left or the screen is locked. It reports its progress to
/// `POST /api/videos/{id}/activity` the way the front's JS does: on pause, at the end and when the
/// player is torn down, with the seconds actually watched since the last report.
final class PlayerController: ObservableObject {
    struct Track: Equatable {
        let videoID: Int
        let kind: MediaKind
    }

    @Published private(set) var track: Track?
    @Published private(set) var title = ""
    @Published private(set) var isPlaying = false
    @Published private(set) var position: Double = 0
    @Published private(set) var duration: Double = 0
    @Published private(set) var player: AVPlayer?
    /// The playlist being played, if any; a single fiche played from its page has none.
    @Published private(set) var queue: PlaylistQueue?
    // Kept across launches, like the web's `raton:playlist-*` settings.
    @Published var queueMode: MediaKind = MediaKind(rawValue: UserDefaults.standard.string(forKey: "playlistMode") ?? "") ?? .audio {
        didSet { UserDefaults.standard.set(queueMode.rawValue, forKey: "playlistMode") }
    }
    @Published var shuffle = UserDefaults.standard.bool(forKey: "playlistShuffle") {
        didSet { UserDefaults.standard.set(shuffle, forKey: "playlistShuffle"); queue?.shuffle = shuffle }
    }
    @Published var loop = UserDefaults.standard.bool(forKey: "playlistLoop") {
        didSet { UserDefaults.standard.set(loop, forKey: "playlistLoop"); queue?.loop = loop }
    }

    private var api: RatonAPI?
    private var artist: String?
    private var fallbackDuration: Double = 0
    private var timeObserver: Any?
    private var statusObserver: AnyCancellable?
    private var endObserver: NSObjectProtocol?
    private var watchedSeconds: Double = 0
    private var lastTrackedTime: Double?
    // Segments the back says to skip (SponsorBlock): the player only jumps over them.
    private var skipSegments: [SkipSegment] = []
    // False in free listening: nothing is written to the history.
    private var reportsActivity = true

    init() {
        configureRemoteCommands()
    }

    // MARK: Loading

    /// Starts playing the fiche's file; does nothing when that file is already the loaded one.
    /// A single fiche replaces the playlist queue.
    func play(detail: VideoDetail, kind: MediaKind, api: RatonAPI, startAt: Double? = nil) {
        let newTrack = Track(videoID: detail.id, kind: kind)
        if track == newTrack {
            if let startAt { seek(to: startAt) }
            resume()
            return
        }
        stop()
        let path = kind == .video ? detail.mediaUrls.video : detail.mediaUrls.audio
        guard let path else { return }
        var start = startAt
        if start == nil, let resume = detail.resumePositions[kind.rawValue]?.positionSeconds, resume >= 3 {
            start = resume
        }
        begin(Track(videoID: detail.id, kind: kind), path: path, title: detail.title,
              artist: detail.channel?.name, duration: detail.durationSeconds ?? 0,
              thumbnail: detail.mediaUrls.thumbnail, api: api, startAt: start,
              skipSegments: detail.sponsorSkipEnabled ? detail.skipSegments : [], reports: true)
    }

    /// Loads a file into a fresh `AVPlayer` and starts it.
    private func begin(_ newTrack: Track, path: String, title: String, artist: String?, duration: Int,
                       thumbnail: String?, api: RatonAPI, startAt: Double?,
                       skipSegments: [SkipSegment], reports: Bool) {
        release()
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            // Playback still works, only without the locked-screen behavior.
        }

        self.api = api
        track = newTrack
        self.title = title
        self.artist = artist
        fallbackDuration = Double(duration)
        self.duration = fallbackDuration
        position = 0
        watchedSeconds = 0
        lastTrackedTime = nil
        reportsActivity = reports

        let player = AVPlayer(url: api.url(path))
        self.player = player
        observe(player)
        self.skipSegments = skipSegments
        if let startAt {
            player.seek(to: CMTime(seconds: startAt, preferredTimescale: 600))
            position = startAt
        }
        player.play()
        loadArtwork(path: thumbnail, videoID: newTrack.videoID, api: api)
        updateNowPlaying()
    }

    /// Reports the last progress, releases the player and forgets the playlist queue.
    func stop() {
        release()
        queue = nil
        refreshRemoteCommands()
    }

    /// Reports the last progress and releases the player, keeping the queue.
    private func release() {
        guard let player else { return }
        trackWatchedTime()
        reportActivity()
        if let timeObserver { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        statusObserver = nil
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = nil
        player.pause()
        self.player = nil
        track = nil
        isPlaying = false
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }

    // MARK: Controls

    func resume() { player?.play() }
    func pause() { player?.pause() }

    func togglePlayPause() {
        if isPlaying { pause() } else { resume() }
    }

    func seek(to seconds: Double) {
        guard let player else { return }
        // Seeking is not watching: forget the last tick so the jump is not counted.
        lastTrackedTime = nil
        player.seek(to: CMTime(seconds: max(seconds, 0), preferredTimescale: 600))
        position = max(seconds, 0)
        updateNowPlaying()
    }

    func skip(by seconds: Double) {
        seek(to: position + seconds)
    }

    // MARK: Observation

    private func observe(_ player: AVPlayer) {
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.5, preferredTimescale: 600), queue: .main
        ) { [weak self] time in
            guard let self, time.seconds.isFinite else { return }
            self.position = time.seconds
            if let itemDuration = player.currentItem?.duration.seconds,
               itemDuration.isFinite, itemDuration > 0 {
                self.duration = itemDuration
            }
            if let segment = self.skipSegments.first(where: { time.seconds >= $0.start && time.seconds < $0.end - 0.5 }) {
                self.seek(to: segment.end)
                return
            }
            self.trackWatchedTime()
            self.updateNowPlaying()
        }
        statusObserver = player.publisher(for: \.timeControlStatus)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status in self?.statusChanged(status) }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: player.currentItem, queue: .main
        ) { [weak self] _ in
            self?.trackWatchedTime()
            self?.reportActivity()
            // Without a queue the player just stays at the end.
            if self?.queue != nil { self?.next() }
        }
    }

    private func statusChanged(_ status: AVPlayer.TimeControlStatus) {
        let playing = status == .playing
        if playing {
            lastTrackedTime = player?.currentTime().seconds
        } else if status == .paused {
            trackWatchedTime()
            reportActivity()
        }
        isPlaying = playing
        updateNowPlaying()
    }

    /// Adds the seconds played since the last tick; a jump of 5 seconds or more is a seek.
    private func trackWatchedTime() {
        guard let player else { return }
        let now = player.currentTime().seconds
        guard now.isFinite else { return }
        if isPlaying, let last = lastTrackedTime {
            let delta = now - last
            if delta > 0 && delta < 5 { watchedSeconds += delta }
        }
        lastTrackedTime = now
    }

    private func reportActivity() {
        guard reportsActivity, let track, let api, watchedSeconds >= 1 else { return }
        let body: [String: Any] = [
            "media_type": track.kind.rawValue,
            "position_seconds": position.isFinite ? position : 0,
            "duration_seconds": duration.isFinite ? duration : 0,
            "watched_seconds": Int(watchedSeconds.rounded()),
        ]
        watchedSeconds = 0
        // A failed report must never interrupt playback.
        Task {
            let _: VideoState? = try? await api.post("/api/videos/\(track.videoID)/activity", body: body)
        }
    }

    // MARK: Lock screen

    private var artwork: MPMediaItemArtwork?

    private func loadArtwork(path: String?, videoID: Int, api: RatonAPI) {
        artwork = nil
        guard let path else { return }
        let url = api.url(path)
        Task {
            guard let (data, _) = try? await URLSession.shared.data(from: url),
                  let image = UIImage(data: data) else { return }
            await MainActor.run {
                guard self.track?.videoID == videoID else { return }
                self.artwork = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
                self.updateNowPlaying()
            }
        }
    }

    private func updateNowPlaying() {
        guard track != nil else { return }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: title,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: position,
            MPMediaItemPropertyPlaybackDuration: duration,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
        ]
        if let artist { info[MPMediaItemPropertyArtist] = artist }
        if let artwork { info[MPMediaItemPropertyArtwork] = artwork }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func configureRemoteCommands() {
        let center = MPRemoteCommandCenter.shared()
        center.playCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.resume() }
            return .success
        }
        center.pauseCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.pause() }
            return .success
        }
        center.togglePlayPauseCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.togglePlayPause() }
            return .success
        }
        center.skipForwardCommand.preferredIntervals = [15]
        center.skipForwardCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.skip(by: 15) }
            return .success
        }
        center.skipBackwardCommand.preferredIntervals = [15]
        center.skipBackwardCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.skip(by: -15) }
            return .success
        }
        center.nextTrackCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.next() }
            return .success
        }
        center.previousTrackCommand.addTarget { [weak self] _ in
            DispatchQueue.main.async { self?.previous() }
            return .success
        }
        refreshRemoteCommands()
        center.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else {
                return .commandFailed
            }
            DispatchQueue.main.async { self?.seek(to: event.positionTime) }
            return .success
        }
    }

    /// A queue offers previous/next track on the lock screen in place of the ±15 s jumps.
    private func refreshRemoteCommands() {
        let center = MPRemoteCommandCenter.shared()
        let queued = queue != nil
        center.nextTrackCommand.isEnabled = queued
        center.previousTrackCommand.isEnabled = queued
        center.skipForwardCommand.isEnabled = !queued
        center.skipBackwardCommand.isEnabled = !queued
    }

    // MARK: Playlist queue

    /// Plays a playlist from `startID` (or its first playable track), in the chosen mode.
    func playQueue(playlistID: Int, title: String, free: Bool, tracks: [QueueTrack], startID: Int?, api: RatonAPI) {
        var newQueue = PlaylistQueue(playlistID: playlistID, title: title, free: free, tracks: tracks,
                                     mode: queueMode, shuffle: shuffle, loop: loop)
        let first = startID.flatMap { id in newQueue.eligible.first { $0.videoID == id } } ?? newQueue.eligible.first
        guard let first else { return }
        self.api = api
        newQueue.pick(first.videoID)
        queue = newQueue
        refreshRemoteCommands()
        startQueueTrack(first, startAt: nil)
    }

    /// The rows of the playing playlist changed: the queue follows.
    func updateQueue(playlistID: Int, free: Bool, tracks: [QueueTrack]) {
        guard var current = queue, current.playlistID == playlistID else { return }
        current.update(tracks: tracks)
        queue = current
    }

    /// Switches the queue between video and audio, keeping the position when the track has both files.
    func setQueueMode(_ mode: MediaKind) {
        queueMode = mode
        guard var current = queue, current.mode != mode else { return }
        current.mode = mode
        queue = current
        guard let playing = current.currentTrack else { return }
        if playing.hasFile(mode) {
            startQueueTrack(playing, startAt: position)
        } else if let following = advance() {
            startQueueTrack(following, startAt: nil)
        } else {
            stopPlaybackKeepingQueue()
        }
    }

    func next() {
        guard queue != nil else { return }
        if let following = advance() { startQueueTrack(following, startAt: nil) } else { pause() }
    }

    /// After 3 seconds "previous" goes back to the start of the track, as on the web.
    func previous() {
        guard queue != nil else { return }
        if position > 3 {
            seek(to: 0)
            return
        }
        var current = queue
        let before = current?.previous()
        queue = current
        if let before { startQueueTrack(before, startAt: nil) } else { seek(to: 0) }
    }

    /// Plays a track of the queue the user tapped.
    func playQueueTrack(_ videoID: Int) {
        guard var current = queue, let chosen = current.tracks.first(where: { $0.videoID == videoID }),
              chosen.hasFile(current.mode) else { return }
        current.pick(videoID)
        queue = current
        startQueueTrack(chosen, startAt: nil)
    }

    private func advance() -> QueueTrack? {
        var current = queue
        let following = current?.next()
        queue = current
        return following
    }

    private func stopPlaybackKeepingQueue() {
        release()
    }

    private func startQueueTrack(_ queued: QueueTrack, startAt: Double?) {
        guard let queue, let api else { return }
        let kind = queue.mode
        let id = queued.videoID
        // A track of a queue has no resume position: it starts at 0. The skip segments come from
        // its fiche, read while it already plays.
        begin(Track(videoID: id, kind: kind), path: "/api/videos/\(id)/\(kind.rawValue)", title: queued.title,
              artist: queued.channelName, duration: queued.durationSeconds,
              thumbnail: queued.hasThumbnail ? "/api/videos/\(id)/thumbnail?w=320" : nil,
              api: api, startAt: startAt, skipSegments: [], reports: !queue.free)
        Task { [weak self] in
            guard let detail: VideoDetail = try? await api.get("/api/videos/\(id)") else { return }
            await MainActor.run {
                guard let self, self.track?.videoID == id, detail.sponsorSkipEnabled else { return }
                self.skipSegments = detail.skipSegments
            }
        }
    }
}
