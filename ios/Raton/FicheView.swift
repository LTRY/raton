import AVKit
import SwiftUI

enum FicheTab: String, CaseIterable {
    case info = "Plus d'informations"
    case segments = "Segments"
    case transcript = "Transcript"
    case notes = "Notes structurées"
    case comment = "Commentaire"
    case chat = "Discussion"
}

/// A fiche: `GET /api/videos/{id}`, then `POST .../open` (what clears the Nouveau label), with the
/// player, the stars, the categories and the tabs under the player. Laid out like the web's fiche page.
struct FicheView: View {
    let videoID: Int

    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @Environment(\.dismiss) private var dismiss
    @State private var detail: VideoDetail?
    @State private var mode: MediaKind = .video
    @State private var tab: FicheTab = .info
    @State private var errorMessage: String?
    @State private var notice: String?
    @State private var busy = false
    @State private var downloading = false
    @State private var choosingQuality = false
    @State private var showCategories = false
    @State private var showPlaylists = false
    @State private var generating = false

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
        .sheet(isPresented: $showCategories) {
            if let detail, let api = state.api {
                CategoryPickerSheet(api: api, selected: detail.categories) { chosen in
                    await save(api, "/api/videos/\(detail.id)/categories", ["categories": chosen])
                }
            }
        }
        .sheet(isPresented: $showPlaylists) {
            if let detail, let api = state.api {
                PlaylistsSheet(api: api, detail: detail) { await reload(api) }
            }
        }
        .confirmationDialog("Qualité de la vidéo", isPresented: $choosingQuality, titleVisibility: .visible) {
            ForEach(Self.qualities, id: \.0) { quality in
                Button(quality.1) { if let api = state.api { download(api, .video, quality: quality.0) } }
            }
        }
    }

    private static let qualities = [
        ("360", "360p"), ("480", "480p"), ("720", "720p"), ("1080", "1080p"),
        ("1440", "1440p"), ("2160", "2160p (4K)"), ("best", "Meilleure disponible"),
    ]

    // MARK: Header and player

    private var topBar: some View {
        ZStack {
            HStack {
                Button { dismiss() } label: { Image(systemName: "arrow.left") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Retour")
                Spacer()
                if let detail, let api = state.api { moreMenu(detail, api: api) }
            }
            if let detail { modePill(detail) }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    /// The "⋮" menu: playlists, notes by the LLM, files, link to the source.
    private func moreMenu(_ detail: VideoDetail, api: RatonAPI) -> some View {
        Menu {
            Button { showPlaylists = true } label: { Label("Playlists", systemImage: "text.badge.plus") }
            Button { generateNotes(api) } label: {
                Label("Générer notes et résumé", systemImage: "sparkles")
            }
            .disabled(generating || !detail.hasTranscript)
            if detail.mediaUrls.video != nil {
                Button(role: .destructive) { deleteMedia(api, .video) } label: {
                    Label("Supprimer la vidéo", systemImage: "trash")
                }
            }
            if detail.mediaUrls.audio != nil {
                Button(role: .destructive) { deleteMedia(api, .audio) } label: {
                    Label("Supprimer l'audio", systemImage: "trash")
                }
            }
            if !detail.hasTranscript {
                Button { Task { await queue(api, "/api/videos/\(detail.id)/transcript/download", "Transcript demandé.") } } label: {
                    Label("Télécharger le transcript", systemImage: "text.alignleft")
                }
            }
            if let url = URL(string: detail.url) {
                Link(destination: url) { Label("Ouvrir sur YouTube", systemImage: "arrow.up.right.square") }
            }
        } label: {
            Image(systemName: "ellipsis")
        }
        .buttonStyle(CircleButtonStyle())
        .accessibilityLabel("Plus d'options")
    }

    /// Video / audio switch, as on the web (the two files can coexist).
    private func modePill(_ detail: VideoDetail) -> some View {
        HStack(spacing: 4) {
            ForEach([MediaKind.video, MediaKind.audio], id: \.self) { kind in
                Button {
                    select(kind)
                } label: {
                    Image(systemName: kind == .video ? "video" : "waveform")
                        .font(.system(size: 18))
                        .foregroundStyle(mode == kind ? Theme.primary : Theme.textMuted)
                        .frame(width: 58, height: 38)
                        .background(Capsule().fill(mode == kind ? Color.white : Color.clear))
                }
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

    private func filePath(_ detail: VideoDetail) -> String? {
        mode == .video ? detail.mediaUrls.video : detail.mediaUrls.audio
    }

    @ViewBuilder
    private func playerArea(_ detail: VideoDetail, api: RatonAPI) -> some View {
        ZStack {
            Theme.player
            if isLoaded, player.track?.kind == .video, mode == .video, let avPlayer = player.player {
                VideoPlayer(player: avPlayer)
            } else if filePath(detail) != nil {
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
            } else if downloading {
                VStack(spacing: 10) {
                    ProgressView().tint(.white)
                    Text("Téléchargement en cours…").font(.raton(14)).foregroundStyle(Color(hex: 0xC2AF98))
                }
            } else if detail.filesPurged {
                Text("Les fichiers ont été supprimés (purge après le Vu).")
                    .font(.raton(15)).foregroundStyle(Color(hex: 0xC2AF98))
                    .multilineTextAlignment(.center).padding(24)
            } else {
                Button {
                    if mode == .video { choosingQuality = true } else { download(api, .audio, quality: nil) }
                } label: {
                    Image(systemName: "arrow.down.to.line")
                        .font(.system(size: 30, weight: .semibold)).foregroundStyle(.white)
                        .frame(width: 72, height: 72)
                        .background(Circle().fill(Theme.primary))
                }
                .accessibilityLabel(mode == .video ? "Télécharger la vidéo" : "Télécharger l'audio")
            }
        }
        .aspectRatio(16 / 9, contentMode: .fit)
    }

    // MARK: Info block

    private func infoBlock(_ detail: VideoDetail, api: RatonAPI) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(detail.title).font(.raton(28, .bold)).foregroundStyle(Theme.text)
            if let channel = detail.channel {
                Text(channel.name).font(.raton(18)).foregroundStyle(Theme.primary)
            }
            HStack(alignment: .top) {
                CategoryChips(categories: detail.categories, api: api)
                Button { showCategories = true } label: {
                    Text("+ Catégories")
                        .font(.raton(14, .semibold)).foregroundStyle(Theme.textFaint)
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .overlay(Capsule().strokeBorder(Theme.borderStrong, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
                }
                Spacer(minLength: 0)
            }
            HStack(spacing: 6) {
                Spacer()
                ForEach(1...5, id: \.self) { star in
                    Button {
                        Task { await save(api, "/api/videos/\(detail.id)/rating", ["rating": detail.rating == star ? 0 : star]) }
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
                    Task { await save(api, "/api/videos/\(detail.id)/list-state",
                                      ["state": detail.shownState == "watched" ? "unwatched" : "watched"]) }
                } label: {
                    Label("Vu", systemImage: detail.shownState == "watched" ? "checkmark.circle.fill" : "checkmark.circle")
                }
                .buttonStyle(SandButtonStyle(active: detail.shownState == "watched"))
                Button {
                    Task { await save(api, "/api/videos/\(detail.id)/list-state",
                                      ["state": detail.shownState == "hidden" ? "clear" : "hidden"]) }
                } label: {
                    Label("Indésirée", systemImage: detail.shownState == "hidden" ? "eye.slash.fill" : "eye.slash")
                }
                .buttonStyle(SandButtonStyle(active: detail.shownState == "hidden"))
            }
            .disabled(busy)
            if let notice { Text(notice).font(.raton(14, .medium)).foregroundStyle(Theme.textSoft) }
            if let message = errorMessage {
                Text(message).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
            }
            tabBar(detail)
            panel(detail, api: api)
        }
        .padding(16)
        .padding(.top, 8)
    }

    private func tabs(_ detail: VideoDetail) -> [FicheTab] {
        FicheTab.allCases.filter { item in
            switch item {
            case .transcript: return detail.hasTranscript || !detail.transcriptLines.isEmpty
            case .notes: return detail.documents.notes != nil || detail.documents.shortSummary != nil
            default: return true
            }
        }
    }

    private func tabBar(_ detail: VideoDetail) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(tabs(detail), id: \.self) { item in
                    let title = item == .segments && !detail.sponsorSegments.isEmpty
                        ? "Segments (\(detail.sponsorSegments.count))" : item.rawValue
                    Button(title) { tab = item }
                        .buttonStyle(SandButtonStyle(active: tab == item, fill: false))
                }
            }
        }
    }

    @ViewBuilder
    private func panel(_ detail: VideoDetail, api: RatonAPI) -> some View {
        switch tab {
        case .info: InfoPanel(detail: detail, seek: { seek($0, detail, api) })
        case .segments: SegmentsPanel(detail: detail, seek: { seek($0, detail, api) })
        case .transcript: TranscriptPanel(detail: detail, seek: { seek($0, detail, api) })
        case .notes: NotesPanel(detail: detail, generating: generating) { generateNotes(api) }
        case .comment:
            CommentPanel(initial: detail.comment ?? "") { text in
                await save(api, "/api/videos/\(detail.id)/comment", ["comment": text])
            }
        case .chat: ChatPanel(api: api, detail: detail) { await reload(api) }
        }
    }

    // MARK: Calls

    private func seek(_ seconds: Double, _ detail: VideoDetail, _ api: RatonAPI) {
        if isLoaded, player.track?.kind == mode {
            player.seek(to: seconds)
            player.resume()
        } else if filePath(detail) != nil {
            player.play(detail: detail, kind: mode, api: api, startAt: seconds)
        }
    }

    private func open() async {
        guard let api = state.api else { return }
        do {
            let loaded: VideoDetail = try await api.get("/api/videos/\(videoID)")
            detail = loaded
            mode = loaded.mediaUrls.video != nil || loaded.mediaUrls.audio == nil ? .video : .audio
            // Opening the fiche is what takes it out of the Nouveautés.
            let _: VideoState? = try? await api.post("/api/videos/\(videoID)/open")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func reload(_ api: RatonAPI) async {
        if let fresh: VideoDetail = try? await api.get("/api/videos/\(videoID)") { detail = fresh }
    }

    /// A PUT on the fiche, then a read back: the back decides what the new state looks like.
    private func save(_ api: RatonAPI, _ path: String, _ body: [String: Any]) async {
        busy = true
        errorMessage = nil
        do {
            let _: VideoState = try await api.put(path, body: body)
            await reload(api)
        } catch {
            errorMessage = error.localizedDescription
        }
        busy = false
    }

    private func queue(_ api: RatonAPI, _ path: String, _ message: String) async {
        do {
            let _: QueuedJob = try await api.post(path)
            notice = message
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func download(_ api: RatonAPI, _ kind: MediaKind, quality: String?) {
        downloading = true
        errorMessage = nil
        Task {
            do {
                var body: [String: Any] = [:]
                if let quality { body["video_quality"] = quality }
                let _: QueuedJob = try await api.post("/api/videos/\(videoID)/media/\(kind.rawValue)/download", body: body)
                // The download runs on the server: read the fiche until its file shows up.
                for _ in 0..<150 {
                    try await Task.sleep(nanoseconds: 4_000_000_000)
                    await reload(api)
                    if let detail, (kind == .video ? detail.mediaUrls.video : detail.mediaUrls.audio) != nil { break }
                }
            } catch {
                errorMessage = error.localizedDescription
            }
            downloading = false
        }
    }

    private func deleteMedia(_ api: RatonAPI, _ kind: MediaKind) {
        if isLoaded, player.track?.kind == kind { player.stop() }
        Task {
            do {
                try await api.delete("/api/videos/\(videoID)/media/\(kind.rawValue)")
                await reload(api)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func generateNotes(_ api: RatonAPI) {
        generating = true
        notice = "Génération des notes en cours…"
        Task {
            do {
                let job: QueuedJob = try await api.post("/api/videos/\(videoID)/notes/generate")
                _ = try await api.waitForLLMJob(job.jobId)
                await reload(api)
                notice = nil
                tab = .notes
            } catch {
                notice = nil
                errorMessage = error.localizedDescription
            }
            generating = false
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
