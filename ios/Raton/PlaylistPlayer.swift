import AVKit
import SwiftUI

/// The player at the top of a playlist, laid out like a fiche's: the video and audio stages side by side
/// (the Vidéo / Audio switch is in the top bar), the seek bar under the audio, then the queue controls
/// (shuffle, previous, play-pause, next, loop). Same behavior as the web's playlist player.
struct PlaylistPlayerPanel: View {
    let detail: PlaylistDetail
    let api: RatonAPI
    @EnvironmentObject private var player: PlayerController

    private var owns: Bool { player.queue?.playlistID == detail.id }
    private var tracks: [QueueTrack] { detail.items.map(\.queueTrack) }
    private var playable: Int { tracks.filter { $0.hasFile(player.queueMode) }.count }
    /// The track the stages show: the playing one, else the first one that can be played.
    private var shown: QueueTrack? {
        owns ? player.queue?.currentTrack : (tracks.first { $0.hasFile(player.queueMode) } ?? tracks.first)
    }
    private var playing: Bool { owns && player.isPlaying }

    var body: some View {
        VStack(spacing: 0) {
            MediaPager(mode: player.queueMode, onSelect: { player.setQueueMode($0) }) {
                videoStage
            } audio: {
                audioStage
            }
            if player.queueMode == .audio {
                AudioSeekBar(videoID: owns ? (player.track?.videoID ?? -1) : -1).transition(.opacity)
            }
            nowPlaying
            // On the audio stage the controls are over the cover; the video stage has the native player's own.
            if player.queueMode == .video { controls(onStage: false).padding(.top, 8) }
            if detail.freeListening {
                Text("Écoute libre : rien n'est ajouté à l'historique").font(.raton(13)).foregroundStyle(Theme.textMuted)
                    .padding(.top, 10)
            }
        }
    }

    private func playPause() {
        if owns, player.track != nil {
            player.togglePlayPause()
        } else {
            player.playQueue(playlistID: detail.id, title: detail.title, free: detail.freeListening,
                             tracks: tracks, startID: nil, api: api)
        }
    }

    /// The video: the native player once a video track plays, else the track's thumbnail under a play button.
    private var videoStage: some View {
        ZStack {
            Theme.player
            if let shown, shown.hasThumbnail {
                Color.clear
                    .overlay { Thumbnail(videoID: shown.videoID, hasThumbnail: true, api: api) }
                    .clipped()
                    .overlay(Color.black.opacity(0.25))
            }
            if owns, player.track?.kind == .video, let avPlayer = player.player {
                NativeVideoPlayer(player: avPlayer)
            } else if playable > 0 {
                Button(action: playPause) {
                    Image(systemName: playing ? "pause.fill" : "play.fill")
                        .font(.system(size: 34)).foregroundStyle(.white)
                        .frame(width: 72, height: 72)
                        .background(Circle().fill(Theme.primary))
                }
                .accessibilityLabel(playing ? "Pause" : "Lecture")
            }
        }
    }

    /// The audio: the track's thumbnail fills the stage, under a dark veil, with the queue controls centered on it.
    private var audioStage: some View {
        ZStack {
            AudioStageBackground()
            if let shown, shown.hasThumbnail {
                Color.clear
                    .overlay { Thumbnail(videoID: shown.videoID, hasThumbnail: true, api: api) }
                    .clipped()
                    .overlay(Color.black.opacity(playable > 0 ? 0.5 : 0.25))
            }
            if playable > 0 { controls(onStage: true) }
        }
    }

    /// What plays (or what is waiting) under the stages.
    private var nowPlaying: some View {
        VStack(spacing: 4) {
            if owns, let current = player.queue?.currentTrack {
                Text(current.title).font(.raton(18, .bold)).foregroundStyle(Theme.text)
                    .multilineTextAlignment(.center).lineLimit(2)
                Text("\(current.channelName.map { "\($0) · " } ?? "")\(player.queue?.currentNumber ?? 0) sur \(tracks.count)")
                    .font(.raton(14)).foregroundStyle(Theme.textMuted)
            } else if playable == 0 {
                Text("Aucune piste lisible").font(.raton(18, .bold)).foregroundStyle(Theme.text)
                Text("Aucune fiche n'a de fichier \(player.queueMode == .audio ? "audio" : "vidéo").")
                    .font(.raton(14)).foregroundStyle(Theme.textMuted)
            }
        }
        .padding(.horizontal, 20).padding(.top, owns || playable == 0 ? 8 : 0)
    }

    /// Shuffle, previous, play-pause, next, loop. On the stage they are white over the cover, the play button
    /// a glass disc; under the video they are the sand and terracotta ones of the fiche.
    private func controls(onStage: Bool) -> some View {
        HStack(spacing: onStage ? 0 : 22) {
            toggle("shuffle", on: player.shuffle, label: "Aléatoire", onStage: onStage) { player.shuffle.toggle() }
            if onStage { Spacer(minLength: 0) }
            Button { player.previous() } label: {
                Image(systemName: "backward.fill").frame(width: onStage ? 44 : nil, height: onStage ? 44 : nil).contentShape(Rectangle())
            }
            .disabled(!owns).accessibilityLabel("Piste précédente")
            if onStage { Spacer(minLength: 0) }
            Button(action: playPause) {
                Image(systemName: owns && player.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: onStage ? 22 : 26)).foregroundStyle(onStage ? Color.white : Theme.primary)
                    .frame(width: onStage ? 52 : 60, height: onStage ? 52 : 60)
                    .modifier(PlayDisc(onStage: onStage))
            }
            .disabled(playable == 0)
            .accessibilityLabel(owns && player.isPlaying ? "Pause" : "Lecture")
            if onStage { Spacer(minLength: 0) }
            Button { player.next() } label: {
                Image(systemName: "forward.fill").frame(width: onStage ? 44 : nil, height: onStage ? 44 : nil).contentShape(Rectangle())
            }
            .disabled(!owns).accessibilityLabel("Piste suivante")
            if onStage { Spacer(minLength: 0) }
            toggle("repeat", on: player.loop, label: "Boucle", onStage: onStage) { player.loop.toggle() }
        }
        .font(.system(size: onStage ? 18 : 20)).foregroundStyle(onStage ? Color.white : Theme.textSoft)
        .padding(.horizontal, onStage ? 24 : 0)
    }

    private func toggle(_ icon: String, on: Bool, label: String, onStage: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Group {
                if onStage {
                    // Over the cover: a white icon, lit up in a warm tone when on.
                    Image(systemName: icon).foregroundStyle(on ? Color(hex: 0xFFB48A) : Color.white)
                        .frame(width: 44, height: 44)
                } else {
                    Image(systemName: icon).foregroundStyle(on ? Theme.primary : Theme.textSoft)
                        .frame(width: 46, height: 46)
                        .surface(in: RoundedRectangle(cornerRadius: 14, style: .continuous), tint: on ? Theme.primary : nil, interactive: true)
                }
            }
        }
        .accessibilityLabel(label)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// The title block under the player: name, where an imported playlist comes from, and its figures.
/// A manual playlist has no kind line, and a playlist has no Vu count.
struct PlaylistTitleBlock: View {
    let detail: PlaylistDetail

    private var kind: String? {
        detail.source == "url" ? "Playlist YouTube" : detail.source == "csv" ? "Playlist CSV Takeout" : nil
    }

    private var figures: String {
        guard let stats = detail.stats else { return "" }
        let minutes = Int((Double(stats.totalDurationSeconds) / 60).rounded())
        let duration = minutes >= 60 ? "\(minutes / 60) h \(String(format: "%02d", minutes % 60))" : "\(minutes) min"
        return "\(duration) · \(stats.count) vidéo\(stats.count > 1 ? "s" : "")"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(detail.title).font(.raton(30, .bold)).foregroundStyle(Theme.text)
            if let kind { Text(kind).font(.raton(16)).foregroundStyle(Theme.textMuted) }
            if !figures.isEmpty { Text(figures).font(.raton(16)).foregroundStyle(Theme.textMuted) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20).padding(.vertical, 12)
    }
}

/// The play-pause disc: terracotta ring under the video, Liquid Glass over the audio cover.
private struct PlayDisc: ViewModifier {
    let onStage: Bool

    func body(content: Content) -> some View {
        if onStage {
            content.glassEffect(.regular.interactive(), in: Circle())
        } else {
            content.surface(in: Circle(), tint: Theme.primary, interactive: true)
        }
    }
}
