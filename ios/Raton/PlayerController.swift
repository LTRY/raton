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

    private var api: RatonAPI?
    private var artist: String?
    private var fallbackDuration: Double = 0
    private var timeObserver: Any?
    private var statusObserver: AnyCancellable?
    private var endObserver: NSObjectProtocol?
    private var watchedSeconds: Double = 0
    private var lastTrackedTime: Double?

    init() {
        configureRemoteCommands()
    }

    // MARK: Loading

    /// Starts playing the fiche's file; does nothing when that file is already the loaded one.
    func play(detail: VideoDetail, kind: MediaKind, api: RatonAPI) {
        let newTrack = Track(videoID: detail.id, kind: kind)
        if track == newTrack {
            resume()
            return
        }
        stop()
        let path = kind == .video ? detail.mediaUrls.video : detail.mediaUrls.audio
        guard let path else { return }

        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            // Playback still works, only without the locked-screen behavior.
        }

        self.api = api
        track = newTrack
        title = detail.title
        artist = detail.channel?.name
        fallbackDuration = Double(detail.durationSeconds ?? 0)
        duration = fallbackDuration
        position = 0
        watchedSeconds = 0
        lastTrackedTime = nil

        let player = AVPlayer(url: api.url(path))
        self.player = player
        observe(player)
        if let resume = detail.resumePositions[kind.rawValue]?.positionSeconds, resume >= 3 {
            player.seek(to: CMTime(seconds: resume, preferredTimescale: 600))
            position = resume
        }
        player.play()
        loadArtwork(for: detail, api: api)
        updateNowPlaying()
    }

    /// Reports the last progress and releases the player.
    func stop() {
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
            forInterval: CMTime(seconds: 1, preferredTimescale: 600), queue: .main
        ) { [weak self] time in
            guard let self, time.seconds.isFinite else { return }
            self.position = time.seconds
            if let itemDuration = player.currentItem?.duration.seconds,
               itemDuration.isFinite, itemDuration > 0 {
                self.duration = itemDuration
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
        guard let track, let api, watchedSeconds >= 1 else { return }
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

    private func loadArtwork(for detail: VideoDetail, api: RatonAPI) {
        artwork = nil
        guard let path = detail.mediaUrls.thumbnail else { return }
        let url = api.url(path)
        let videoID = detail.id
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
        center.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else {
                return .commandFailed
            }
            DispatchQueue.main.async { self?.seek(to: event.positionTime) }
            return .success
        }
    }
}
