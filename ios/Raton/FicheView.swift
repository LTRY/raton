import AVKit
import SwiftUI

/// A fiche: `GET /api/videos/{id}`, then `POST .../open` (what clears the Nouveau label), with the
/// Vu / Indésirée buttons, the stars and the player.
struct FicheView: View {
    let videoID: Int

    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @State private var detail: VideoDetail?
    @State private var errorMessage: String?
    @State private var busy = false

    private var isLoaded: Bool { player.track?.videoID == videoID }

    var body: some View {
        ScrollView {
            if let detail, let api = state.api {
                VStack(alignment: .leading, spacing: 16) {
                    media(detail, api: api)
                    Text(detail.title).font(.title3).bold()
                    if let channel = detail.channel {
                        Text(channel.name).foregroundStyle(.secondary)
                    }
                    playButtons(detail, api: api)
                    actions(detail, api: api)
                    if let message = errorMessage {
                        Text(message).foregroundStyle(.red)
                    }
                    if let description = detail.metadata.description, !description.isEmpty {
                        Text(description).font(.callout)
                    }
                }
                .padding()
            } else if let message = errorMessage {
                Text(message).foregroundStyle(.red).padding()
            } else {
                ProgressView().padding(.top, 80).frame(maxWidth: .infinity)
            }
        }
        .navigationTitle("Fiche")
        .navigationBarTitleDisplayMode(.inline)
        .task { await open() }
        // The video is tied to this screen; audio goes on.
        .onDisappear {
            if player.track?.videoID == videoID && player.track?.kind == .video { player.stop() }
        }
    }

    // MARK: Parts

    @ViewBuilder
    private func media(_ detail: VideoDetail, api: RatonAPI) -> some View {
        if isLoaded, player.track?.kind == .video, let avPlayer = player.player {
            VideoPlayer(player: avPlayer)
                .aspectRatio(16 / 9, contentMode: .fit)
        } else {
            Thumbnail(videoID: detail.id, hasThumbnail: detail.mediaUrls.thumbnail != nil, api: api)
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    @ViewBuilder
    private func playButtons(_ detail: VideoDetail, api: RatonAPI) -> some View {
        // The two files can coexist: offer each one the fiche has.
        if detail.mediaUrls.video == nil && detail.mediaUrls.audio == nil {
            Text(detail.filesPurged
                ? "Les fichiers ont été supprimés (purge après le Vu)."
                : "Cette fiche n'a pas de fichier vidéo ou audio.")
                .foregroundStyle(.secondary)
        } else {
            HStack {
                if detail.mediaUrls.video != nil {
                    Button {
                        player.play(detail: detail, kind: .video, api: api)
                    } label: {
                        Label("Lire la vidéo", systemImage: "play.rectangle.fill")
                    }
                    .buttonStyle(.borderedProminent)
                }
                if detail.mediaUrls.audio != nil {
                    Button {
                        player.play(detail: detail, kind: .audio, api: api)
                    } label: {
                        Label("Écouter l'audio", systemImage: "headphones")
                    }
                    .buttonStyle(.bordered)
                }
            }
            if isLoaded, player.track?.kind == .audio {
                AudioControls()
            }
        }
    }

    private func actions(_ detail: VideoDetail, api: RatonAPI) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                // Same toggles as the front: Vu <-> unwatched, Indésirée <-> back to automatic.
                Button {
                    send(api, "/api/videos/\(detail.id)/list-state",
                         ["state": detail.shownState == "watched" ? "unwatched" : "watched"])
                } label: {
                    Label("Vu", systemImage: detail.shownState == "watched" ? "checkmark.circle.fill" : "checkmark.circle")
                }
                .buttonStyle(.bordered)
                Button {
                    send(api, "/api/videos/\(detail.id)/list-state",
                         ["state": detail.shownState == "hidden" ? "clear" : "hidden"])
                } label: {
                    Label("Indésirée", systemImage: detail.shownState == "hidden" ? "eye.slash.fill" : "eye.slash")
                }
                .buttonStyle(.bordered)
            }
            .disabled(busy)
            HStack(spacing: 4) {
                ForEach(1...5, id: \.self) { star in
                    Button {
                        send(api, "/api/videos/\(detail.id)/rating",
                             ["rating": detail.rating == star ? 0 : star])
                    } label: {
                        Image(systemName: star <= detail.rating ? "star.fill" : "star")
                            .foregroundStyle(.yellow)
                            .font(.title3)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(star) étoile\(star > 1 ? "s" : "")")
                }
            }
            .disabled(busy)
        }
    }

    // MARK: Calls

    private func open() async {
        guard let api = state.api else { return }
        do {
            detail = try await api.get("/api/videos/\(videoID)")
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

/// Play/pause, ±15 s and a position slider for the audio of the loaded fiche.
struct AudioControls: View {
    @EnvironmentObject private var player: PlayerController
    @State private var dragging = false
    @State private var dragPosition = 0.0

    var body: some View {
        VStack(spacing: 8) {
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
            HStack {
                Text(Format.clock(player.position)).font(.caption).monospacedDigit()
                Spacer()
                Text(Format.clock(player.duration)).font(.caption).monospacedDigit()
            }
            .foregroundStyle(.secondary)
            HStack(spacing: 32) {
                Button { player.skip(by: -15) } label: { Image(systemName: "gobackward.15") }
                Button { player.togglePlayPause() } label: {
                    Image(systemName: player.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 44))
                }
                Button { player.skip(by: 15) } label: { Image(systemName: "goforward.15") }
            }
            .font(.title2)
        }
    }
}

/// The bar shown above the tabs while audio is loaded, so it can be paused after leaving its fiche.
struct NowPlayingBar: View {
    @EnvironmentObject private var player: PlayerController

    var body: some View {
        if player.track?.kind == .audio {
            HStack {
                Text(player.title).lineLimit(1).font(.subheadline)
                Spacer()
                Button { player.togglePlayPause() } label: {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                }
                Button { player.stop() } label: { Image(systemName: "xmark") }
                    .padding(.leading, 8)
            }
            .padding(.horizontal)
            .padding(.vertical, 10)
            .background(.regularMaterial)
        }
    }
}
