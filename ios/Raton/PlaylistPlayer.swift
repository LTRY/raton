import AVKit
import SwiftUI

/// The player at the top of a playlist: Video / Audio, the stage, the seek bar and the queue controls
/// (shuffle, previous, play-pause, next, loop). Same behavior as the web's playlist player.
struct PlaylistPlayerPanel: View {
    let detail: PlaylistDetail
    let api: RatonAPI
    @EnvironmentObject private var player: PlayerController

    private var owns: Bool { player.queue?.playlistID == detail.id }
    private var tracks: [QueueTrack] { detail.items.map(\.queueTrack) }
    private var playable: Int { tracks.filter { $0.hasFile(player.queueMode) }.count }

    var body: some View {
        VStack(spacing: 14) {
            modePicker
            stage
            if owns, player.queue?.mode == .audio, player.track != nil {
                AudioControls()
            }
            controls
            if detail.freeListening {
                Text("Écoute libre : rien n'est compté comme vu").font(.raton(13)).foregroundStyle(Theme.textMuted)
            }
        }
        .padding(16)
        .surfaceCard(radius: 28)
        .padding(.horizontal, 16).padding(.bottom, 8)
    }

    private var modePicker: some View {
        HStack(spacing: 8) {
            ForEach([MediaKind.video, MediaKind.audio], id: \.self) { kind in
                let active = player.queueMode == kind
                Button { player.setQueueMode(kind) } label: {
                    Text(kind == .video ? "Vidéo" : "Audio").font(.raton(16, .bold))
                        .foregroundStyle(active ? Theme.primary : Theme.textMuted)
                        .frame(maxWidth: .infinity).frame(height: 40)
                        .background(Capsule().fill(active ? Color.white : Color.clear))
                }
            }
        }
        .padding(4)
        .sandTrack()
    }

    /// The square cover of the audio mode: the track's thumbnail, or the terracotta gradient, with its "Audio" tag.
    private var art: some View {
        ZStack(alignment: .topLeading) {
            if let current = player.queue?.currentTrack, current.hasThumbnail, owns {
                AsyncImage(url: api.url("/api/videos/\(current.videoID)/thumbnail")) { image in
                    image.resizable().scaledToFill()
                } placeholder: { gradient }
            } else {
                gradient
            }
            Text("Audio").font(.raton(13, .bold)).foregroundStyle(Theme.text)
                .padding(.horizontal, 12).padding(.vertical, 5)
                .background(Capsule().fill(Color.white.opacity(0.9))).padding(12)
        }
        .frame(width: 250, height: 250).clipped()
        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
    }

    private var gradient: some View {
        LinearGradient(colors: [Color(hex: 0xE8A07A), Color(hex: 0xC2410C), Color(hex: 0x8A2C10)],
                       startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    @ViewBuilder
    private var stage: some View {
        if owns, player.track?.kind == .video, let avPlayer = player.player {
            VideoPlayer(player: avPlayer).aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        } else {
            VStack(spacing: 10) {
                if player.queueMode == .audio { art }
                if owns, let current = player.queue?.currentTrack {
                    Text(current.title).font(.raton(18, .bold)).foregroundStyle(Theme.text)
                        .multilineTextAlignment(.center).lineLimit(2)
                    Text("\(current.channelName.map { "\($0) · " } ?? "")\(player.queue?.currentNumber ?? 0) sur \(tracks.count)")
                        .font(.raton(14)).foregroundStyle(Theme.textMuted)
                } else if playable == 0 {
                    Text("Aucune piste lisible").font(.raton(18, .bold)).foregroundStyle(Theme.text)
                    Text("Aucune fiche n'a de fichier \(player.queueMode == .audio ? "audio" : "vidéo").")
                        .font(.raton(14)).foregroundStyle(Theme.textMuted)
                } else {
                    Text("\(playable) piste\(playable > 1 ? "s" : "") à lire").font(.raton(18, .bold))
                        .foregroundStyle(Theme.text)
                }
            }
            .frame(maxWidth: .infinity).padding(.vertical, 10)
        }
    }

    private var controls: some View {
        HStack(spacing: 22) {
            toggle("shuffle", on: player.shuffle, label: "Aléatoire") { player.shuffle.toggle() }
            Button { player.previous() } label: { Image(systemName: "backward.fill") }
                .disabled(!owns).accessibilityLabel("Piste précédente")
            Button {
                if owns, player.track != nil {
                    player.togglePlayPause()
                } else {
                    player.playQueue(playlistID: detail.id, title: detail.title, free: detail.freeListening,
                                     tracks: tracks, startID: nil, api: api)
                }
            } label: {
                Image(systemName: owns && player.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 26)).foregroundStyle(Theme.primary)
                    .frame(width: 60, height: 60).surface(in: Circle(), tint: Theme.primary, interactive: true)
            }
            .disabled(playable == 0)
            .accessibilityLabel(owns && player.isPlaying ? "Pause" : "Lecture")
            Button { player.next() } label: { Image(systemName: "forward.fill") }
                .disabled(!owns).accessibilityLabel("Piste suivante")
            toggle("repeat", on: player.loop, label: "Boucle") { player.loop.toggle() }
        }
        .font(.system(size: 20)).foregroundStyle(Theme.textSoft)
    }

    private func toggle(_ icon: String, on: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon).foregroundStyle(on ? Theme.primary : Theme.textSoft)
                .frame(width: 46, height: 46)
                .surface(in: RoundedRectangle(cornerRadius: 14, style: .continuous), tint: on ? Theme.primary : nil, interactive: true)
        }
        .accessibilityLabel(label)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// The title block under the player: name, kind and the figures of the playlist, like the web's.
struct PlaylistTitleBlock: View {
    let detail: PlaylistDetail

    private var kind: String {
        detail.source == "url" ? "Playlist YouTube" : detail.source == "csv" ? "Playlist CSV Takeout" : "Playlist manuelle"
    }

    private var figures: String {
        guard let stats = detail.stats else { return "" }
        let minutes = Int((Double(stats.totalDurationSeconds) / 60).rounded())
        let duration = minutes >= 60 ? "\(minutes / 60) h \(String(format: "%02d", minutes % 60))" : "\(minutes) min"
        let seen = detail.freeListening ? "écoute libre" : "\(stats.seenCount) vue\(stats.seenCount > 1 ? "s" : "") sur \(stats.count)"
        return "\(duration) · \(stats.count) vidéo\(stats.count > 1 ? "s" : "") · \(seen)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(detail.title).font(.raton(30, .bold)).foregroundStyle(Theme.text)
            Text(kind).font(.raton(16)).foregroundStyle(Theme.textMuted)
            if !figures.isEmpty { Text(figures).font(.raton(16)).foregroundStyle(Theme.textMuted) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20).padding(.vertical, 12)
    }
}
