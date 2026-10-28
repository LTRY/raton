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
    }

    private var modePicker: some View {
        HStack(spacing: 8) {
            ForEach([MediaKind.video, MediaKind.audio], id: \.self) { kind in
                Button(kind == .video ? "Vidéo" : "Audio") { player.setQueueMode(kind) }
                    .buttonStyle(SandButtonStyle(active: player.queueMode == kind))
            }
        }
    }

    @ViewBuilder
    private var stage: some View {
        if owns, player.track?.kind == .video, let avPlayer = player.player {
            VideoPlayer(player: avPlayer).aspectRatio(16 / 9, contentMode: .fit)
        } else {
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
                } else {
                    Text("\(playable) piste\(playable > 1 ? "s" : "") à lire").font(.raton(18, .bold))
                        .foregroundStyle(Theme.text)
                }
            }
            .frame(maxWidth: .infinity).padding(.vertical, 10)
        }
    }

    private var controls: some View {
        HStack(spacing: 26) {
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
                    .font(.system(size: 26)).foregroundStyle(.white)
                    .frame(width: 60, height: 60).background(Circle().fill(Theme.primary))
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
            Image(systemName: icon).foregroundStyle(on ? Theme.primary : Theme.textMuted)
                .frame(width: 38, height: 38)
                .background(Circle().fill(on ? Theme.tint : Color.clear))
        }
        .accessibilityLabel(label)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
