import AVKit
import SwiftUI

enum FicheTab: String, CaseIterable {
    case info = "Plus d'informations"
    case notes = "Notes structurées"
    case chat = "Discussion"
}

/// A fiche: `GET /api/videos/{id}`, then `POST .../open` (what clears the Nouveau label), with the
/// player, the stars, the categories and the tabs under the player. Laid out like the web's fiche page.
struct FicheView: View {
    let videoID: Int

    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @EnvironmentObject private var offline: OfflineStore
    @Environment(\.dismiss) private var dismiss
    @State private var detail: VideoDetail?
    @State private var mode: MediaKind = .video
    @State private var errorMessage: String?
    @State private var notice: String?
    @State private var busy = false
    @State private var downloading = false
    @State private var choosingQuality = false
    @State private var showCategories = false
    @State private var showPlaylists = false
    @State private var showComment = false
    @State private var generating = false

    private var isLoaded: Bool { player.track?.videoID == videoID }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                topBar
                if let detail, let api = state.api {
                    mediaPager(detail, api: api)
                    if mode == .audio {
                        AudioSeekBar(videoID: detail.id).transition(.opacity)
                    }
                    infoBlock(detail, api: api)
                } else if let message = errorMessage {
                    Text(message).font(.raton(15, .medium)).foregroundStyle(Theme.danger).padding()
                } else {
                    ProgressView().padding(.top, 80)
                }
            }
            // Room under the last block so it can scroll clear of the tab bar.
            .padding(.bottom, 130)
        }
        // Dragging the page down dismisses the keyboard instead of leaving it over the chat.
        .scrollDismissesKeyboard(.interactively)
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
        .sheet(isPresented: $showComment) {
            if let detail, let api = state.api {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Commentaire personnel").font(.raton(20, .bold)).foregroundStyle(Theme.text)
                    CommentPanel(initial: detail.comment ?? "") { text in
                        await save(api, "/api/videos/\(detail.id)/comment", ["comment": text])
                        showComment = false
                    }
                    Spacer(minLength: 0)
                }
                .padding(20)
                .ratonPage()
                .presentationDetents([.medium, .large])
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
            if detail != nil { MediaModePill(mode: mode, onSelect: select) }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    /// The "⋮" menu: playlists, notes by the LLM, files, link to the source.
    private func moreMenu(_ detail: VideoDetail, api: RatonAPI) -> some View {
        Menu {
            // The same two toggles as the front: Vu <-> unwatched, Indésirée <-> back to automatic.
            Button {
                Task { await save(api, "/api/videos/\(detail.id)/list-state",
                                  ["state": detail.shownState == "watched" ? "unwatched" : "watched"]) }
            } label: {
                Label(detail.shownState == "watched" ? "Marquer comme non vu" : "Marquer comme vu",
                      systemImage: detail.shownState == "watched" ? "eye.slash" : "checkmark.circle")
            }
            Button {
                Task { await save(api, "/api/videos/\(detail.id)/list-state",
                                  ["state": detail.shownState == "hidden" ? "clear" : "hidden"]) }
            } label: {
                Label(detail.shownState == "hidden" ? "Ne plus masquer" : "Marquer indésirée", systemImage: "eye.slash")
            }
            Divider()
            Button { showPlaylists = true } label: { Label("Playlists", systemImage: "text.badge.plus") }
            Button { showComment = true } label: { Label("Écrire un commentaire personnel", systemImage: "square.and.pencil") }
            Button { generateNotes(api) } label: {
                Label("Générer notes et résumé", systemImage: "sparkles")
            }
            .disabled(generating || !detail.hasTranscript)
            if detail.mediaUrls.audio != nil {
                Button { toggleOffline(detail, api: api) } label: {
                    if offline.item(detail.id) != nil {
                        Label("Retirer de l'écoute hors ligne", systemImage: "icloud.slash")
                    } else if offline.downloading.contains(detail.id) {
                        Label("Téléchargement hors ligne…", systemImage: "arrow.down.circle")
                    } else {
                        Label("Écouter hors ligne", systemImage: "arrow.down.circle")
                    }
                }
                .disabled(offline.downloading.contains(detail.id))
            }
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

    /// Keeps the fiche's audio on the phone, or lets it go.
    private func toggleOffline(_ detail: VideoDetail, api: RatonAPI) {
        if offline.item(detail.id) != nil {
            offline.remove(detail.id)
            return
        }
        Task {
            do { try await offline.download(detail: detail, api: api) } catch { errorMessage = error.localizedDescription }
        }
    }

    private func mediaPager(_ detail: VideoDetail, api: RatonAPI) -> some View {
        MediaPager(mode: mode, onSelect: select) {
            playerArea(detail, api: api)
        } audio: {
            AudioSlide(detail: detail, api: api, downloading: downloading,
                       onDownload: { download(api, .audio, quality: nil) })
        }
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
            // The thumbnail fills the player until the video plays (audio keeps it behind the controls).
            if detail.mediaUrls.thumbnail != nil {
                Color.clear
                    .overlay { Thumbnail(videoID: detail.id, hasThumbnail: true, api: api) }
                    .clipped()
                    .overlay(Color.black.opacity(0.25))
            }
            if isLoaded, player.track?.kind == .video, mode == .video, let avPlayer = player.player {
                NativeVideoPlayer(player: avPlayer)
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
            Text(detail.title).font(.raton(21, .bold)).foregroundStyle(Theme.text)
            if let channel = detail.channel {
                Text(channel.name).font(.raton(18)).foregroundStyle(Theme.primary)
            }
            HStack(alignment: .center, spacing: 6) {
                CategoryChips(categories: detail.categories, api: api)
                // Same size as the labels on its line.
                Button { showCategories = true } label: {
                    Text("+ Catégories")
                        .font(.raton(9, .semibold)).foregroundStyle(Theme.textFaint)
                        .padding(.horizontal, 10).padding(.vertical, 5)
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
                            .foregroundStyle(star <= detail.rating ? Theme.amber : Theme.textFaint.opacity(0.55))
                    }
                    .accessibilityLabel("\(star) étoile\(star > 1 ? "s" : "")")
                }
            }
            .disabled(busy)
            Theme.border.frame(height: 1)
            if let notice { Text(notice).font(.raton(14, .medium)).foregroundStyle(Theme.textSoft) }
            if let message = errorMessage {
                Text(message).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
            }
            sections(detail, api: api)
        }
        .padding(16)
        .padding(.top, 8)
    }

    private func tabs(_ detail: VideoDetail) -> [FicheTab] {
        FicheTab.allCases.filter { item in
            switch item {
            case .notes: return detail.documents.notes != nil || detail.documents.shortSummary != nil
            default: return true
            }
        }
    }

    private func sectionTitle(_ item: FicheTab, _ detail: VideoDetail) -> String {
        item.rawValue
    }

    /// The sections one under the other, in the order of `FicheTab`: no tabs to switch between.
    private func sections(_ detail: VideoDetail, api: RatonAPI) -> some View {
        VStack(alignment: .leading, spacing: 26) {
            ForEach(tabs(detail), id: \.self) { item in
                VStack(alignment: .leading, spacing: 10) {
                    // The description (behind its own chevron) and the chat (a plain input) have no title.
                    if item != .info && item != .chat {
                        Text(sectionTitle(item, detail)).font(.raton(20, .bold)).foregroundStyle(Theme.text)
                    }
                    section(item, detail, api: api)
                }
            }
        }
        .padding(.top, 6)
    }

    @ViewBuilder
    private func section(_ item: FicheTab, _ detail: VideoDetail, api: RatonAPI) -> some View {
        switch item {
        case .info: InfoPanel(detail: detail, seek: { seek($0, detail, api) })
        case .notes: NotesPanel(detail: detail, generating: generating) { generateNotes(api) }
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

/// The mini player above the tab bar while audio is loaded, so it can be paused after leaving its fiche:
/// a smoked-glass pill of the tab bar's width and shape, play-pause on the left, the title over its
/// channel, then next (in a playlist) and close.
struct NowPlayingBar: View {
    @EnvironmentObject private var player: PlayerController

    var body: some View {
        if player.track?.kind == .audio || player.queue != nil {
            HStack(spacing: 6) {
                Button { player.togglePlayPause() } label: {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                        .font(.system(size: 24)).frame(width: 52, height: 52).contentShape(Rectangle())
                }
                .accessibilityLabel(player.isPlaying ? "Pause" : "Lecture")
                VStack(alignment: .leading, spacing: 1) {
                    Text(player.title).font(.raton(16, .bold)).lineLimit(1)
                    if let artist = player.artist {
                        Text(artist).font(.raton(14)).lineLimit(1).opacity(0.7)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if player.queue != nil {
                    Button { player.next() } label: {
                        Image(systemName: "forward.end.fill").font(.system(size: 22))
                            .frame(width: 48, height: 52).contentShape(Rectangle())
                    }
                    .accessibilityLabel("Piste suivante")
                }
                Button { player.stop() } label: {
                    Image(systemName: "xmark").font(.system(size: 17, weight: .semibold))
                        .frame(width: 44, height: 52).contentShape(Rectangle())
                }
                .accessibilityLabel("Fermer le lecteur")
            }
            .foregroundStyle(Color(hex: 0xF3E8D9))
            .padding(.leading, 8).padding(.trailing, 6)
            // The first background is the one on top: the smoke over the blur of the page behind.
            .background(TabPill.shape.fill(Theme.player.opacity(0.9)))
            .background(TabPill.shape.fill(.ultraThinMaterial))
            .overlay(TabPill.shape.stroke(Color.white.opacity(0.16), lineWidth: 1))
            .shadow(color: Theme.shadow.opacity(0.18), radius: 12, y: 6)
            .padding(.horizontal, TabPill.margin)
        }
    }
}
