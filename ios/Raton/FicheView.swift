import AVKit
import SwiftUI

/// A fiche: `GET /api/videos/{id}`, then `POST .../open` (what clears the Nouveau label), with the
/// player, the Vu / Indésirée buttons and the stars. Laid out like the web's fiche page.
struct FicheView: View {
    let videoID: Int

    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @Environment(\.dismiss) private var dismiss
    @State private var detail: VideoDetail?
    @State private var mode: MediaKind = .video
    @State private var showInfo = false
    @State private var errorMessage: String?
    @State private var busy = false

    private var isLoaded: Bool { player.track?.videoID == videoID }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                topBar
                if let detail, let api = state.api {
                    playerArea(detail, api: api)
                    if isLoaded, player.track?.kind == .audio, mode == .audio {
                        AudioControls().padding(.horizontal, 16).padding(.top, 12)
                    }
                    infoBlock(detail, api: api)
                } else if let message = errorMessage {
                    Text(message).font(.raton(15, .medium)).foregroundStyle(Theme.danger).padding()
                } else {
                    ProgressView().padding(.top, 80)
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
        .task { await open() }
        // The video is tied to this screen; audio goes on.
        .onDisappear {
            if player.track?.videoID == videoID && player.track?.kind == .video { player.stop() }
        }
    }

    // MARK: Parts

    private var topBar: some View {
        ZStack {
            HStack {
                Button { dismiss() } label: { Image(systemName: "arrow.left") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Retour")
                Spacer()
            }
            if let detail { modePill(detail) }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    /// Video / audio switch; each side is available only when the fiche has that file (they can coexist).
    private func modePill(_ detail: VideoDetail) -> some View {
        HStack(spacing: 4) {
            ForEach([MediaKind.video, MediaKind.audio], id: \.self) { kind in
                let available = (kind == .video ? detail.mediaUrls.video : detail.mediaUrls.audio) != nil
                Button {
                    select(kind)
                } label: {
                    Image(systemName: kind == .video ? "video" : "waveform")
                        .font(.system(size: 18))
                        .foregroundStyle(mode == kind ? Theme.primary : Theme.textMuted)
                        .frame(width: 58, height: 38)
                        .background(Capsule().fill(mode == kind ? Color.white : Color.clear))
                }
                .disabled(!available)
                .opacity(available ? 1 : 0.35)
                .accessibilityLabel(kind == .video ? "Vidéo" : "Audio")
            }
        }
        .padding(4)
        .background(Capsule().fill(Theme.surfaceMuted))
        .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
    }

    private func select(_ kind: MediaKind) {
        mode = kind
        if isLoaded, player.track?.kind != kind { player.stop() }
    }

    @ViewBuilder
    private func playerArea(_ detail: VideoDetail, api: RatonAPI) -> some View {
        let hasFile = (mode == .video ? detail.mediaUrls.video : detail.mediaUrls.audio) != nil
        ZStack {
            Theme.player
            if isLoaded, player.track?.kind == .video, mode == .video, let avPlayer = player.player {
                VideoPlayer(player: avPlayer)
            } else if hasFile {
                let playing = isLoaded && player.track?.kind == mode && player.isPlaying
                Button {
                    if isLoaded, player.track?.kind == mode {
                        player.togglePlayPause()
                    } else {
                        player.play(detail: detail, kind: mode, api: api)
                    }
                } label: {
                    Image(systemName: playing ? "pause.fill" : "play.fill")
                        .font(.system(size: 34)).foregroundStyle(.white)
                        .frame(width: 72, height: 72)
                        .background(Circle().fill(Theme.primary))
                }
                .accessibilityLabel(playing ? "Pause" : "Lecture")
            } else {
                Text(detail.filesPurged
                    ? "Les fichiers ont été supprimés (purge après le Vu)."
                    : "Cette fiche n'a pas de fichier vidéo ou audio.")
                    .font(.raton(15)).foregroundStyle(Color(hex: 0xC2AF98))
                    .multilineTextAlignment(.center).padding(24)
            }
        }
        .aspectRatio(16 / 9, contentMode: .fit)
    }

    private func infoBlock(_ detail: VideoDetail, api: RatonAPI) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(detail.title).font(.raton(28, .bold)).foregroundStyle(Theme.text)
            if let channel = detail.channel {
                Text(channel.name).font(.raton(18)).foregroundStyle(Theme.primary)
            }
            HStack(spacing: 6) {
                Spacer()
                ForEach(1...5, id: \.self) { star in
                    Button {
                        send(api, "/api/videos/\(detail.id)/rating",
                             ["rating": detail.rating == star ? 0 : star])
                    } label: {
                        Image(systemName: "star.fill")
                            .font(.system(size: 24))
                            .foregroundStyle(star <= detail.rating ? Theme.amber : Color(hex: 0xF6E4DD))
                    }
                    .accessibilityLabel("\(star) étoile\(star > 1 ? "s" : "")")
                }
            }
            .disabled(busy)
            Theme.border.frame(height: 1)
            // Same toggles as the front: Vu <-> unwatched, Indésirée <-> back to automatic.
            HStack(spacing: 8) {
                Button {
                    send(api, "/api/videos/\(detail.id)/list-state",
                         ["state": detail.shownState == "watched" ? "unwatched" : "watched"])
                } label: {
                    Label("Vu", systemImage: detail.shownState == "watched" ? "checkmark.circle.fill" : "checkmark.circle")
                }
                .buttonStyle(SandButtonStyle(active: detail.shownState == "watched"))
                Button {
                    send(api, "/api/videos/\(detail.id)/list-state",
                         ["state": detail.shownState == "hidden" ? "clear" : "hidden"])
                } label: {
                    Label("Indésirée", systemImage: detail.shownState == "hidden" ? "eye.slash.fill" : "eye.slash")
                }
                .buttonStyle(SandButtonStyle(active: detail.shownState == "hidden"))
            }
            .disabled(busy)
            Button("Plus d'informations") { showInfo.toggle() }
                .buttonStyle(SandButtonStyle(active: showInfo))
            if showInfo {
                VStack(alignment: .leading, spacing: 8) {
                    if let uploader = detail.metadata.uploader {
                        Text(uploader).font(.raton(15, .semibold)).foregroundStyle(Theme.textSoft)
                    }
                    Text(detail.metadata.description ?? "Pas de description.")
                        .font(.raton(15)).foregroundStyle(Theme.textSoft)
                }
            }
            if let message = errorMessage {
                Text(message).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
            }
        }
        .padding(16)
        .padding(.top, 8)
    }

    // MARK: Calls

    private func open() async {
        guard let api = state.api else { return }
        do {
            let loaded: VideoDetail = try await api.get("/api/videos/\(videoID)")
            detail = loaded
            mode = loaded.mediaUrls.video != nil ? .video : .audio
            // Opening the fiche is what takes it out of the Nouveautés.
            let _: VideoState? = try? await api.post("/api/videos/\(videoID)/open")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func send(_ api: RatonAPI, _ path: String, _ body: [String: Any]) {
        busy = true
        errorMessage = nil
        Task {
            do {
                let _: VideoState = try await api.put(path, body: body)
                // The back decides what the new state looks like: read it back.
                detail = try await api.get("/api/videos/\(videoID)")
            } catch {
                errorMessage = error.localizedDescription
            }
            busy = false
        }
    }
}

/// Seek bar, times and ±15 s for the audio of the loaded fiche.
struct AudioControls: View {
    @EnvironmentObject private var player: PlayerController
    @State private var dragging = false
    @State private var dragPosition = 0.0

    var body: some View {
        VStack(spacing: 4) {
            Slider(
                value: Binding(
                    get: { dragging ? dragPosition : player.position },
                    set: { dragPosition = $0 }
                ),
                in: 0...max(player.duration, 1),
                onEditingChanged: { editing in
                    dragging = editing
                    if !editing { player.seek(to: dragPosition) }
                }
            )
            .tint(Theme.primary)
            HStack {
                Text(Format.clock(player.position))
                Spacer()
                Text(Format.clock(player.duration))
            }
            .font(.raton(14, .semibold)).monospacedDigit()
            .foregroundStyle(Theme.textMuted)
            HStack(spacing: 40) {
                Button { player.skip(by: -15) } label: { Image(systemName: "gobackward.15") }
                Button { player.skip(by: 15) } label: { Image(systemName: "goforward.15") }
            }
            .font(.system(size: 24)).foregroundStyle(Theme.textSoft)
        }
    }
}

/// The bar shown above the tabs while audio is loaded, so it can be paused after leaving its fiche.
struct NowPlayingBar: View {
    @EnvironmentObject private var player: PlayerController

    var body: some View {
        if player.track?.kind == .audio {
            HStack(spacing: 16) {
                Text(player.title).font(.raton(14, .semibold)).lineLimit(1)
                    .foregroundStyle(Color(hex: 0xF3E8D9))
                Spacer()
                Button { player.togglePlayPause() } label: {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                }
                Button { player.stop() } label: { Image(systemName: "xmark") }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 18).padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 16).fill(Theme.player))
            .padding(.horizontal, 12)
        }
    }
}
