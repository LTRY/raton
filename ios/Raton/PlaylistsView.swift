import SwiftUI

struct PlaylistsView: View {
    @EnvironmentObject private var state: AppState
    // The tiles open their playlist from code, after their press animation.
    @State private var path = NavigationPath()
    @State private var playlists: [PlaylistSummary] = []
    @State private var loaded = false
    @State private var errorMessage: String?
    @State private var showNew = false
    @State private var showImport = false
    @State private var search = ""

    private var shown: [PlaylistSummary] {
        let query = search.trimmingCharacters(in: .whitespaces).lowercased()
        return query.isEmpty ? playlists : playlists.filter { $0.title.lowercased().contains(query) }
    }

    var body: some View {
        NavigationStack(path: $path) { content }
    }

    private var content: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Playlists", badge: playlists.count) {
                            Menu {
                                Button { showNew = true } label: { Label("Nouvelle playlist", systemImage: "plus") }
                                Button { showImport = true } label: { Label("Importer depuis YouTube", systemImage: "square.and.arrow.down") }
                            } label: { Image(systemName: "plus") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Ajouter une playlist")
                        }
                        SearchField(placeholder: "Rechercher une playlist", text: $search) {}
                        ErrorMessage(text: errorMessage) { Task { await load(api) } }
                        if !loaded && errorMessage == nil { LoadingRow() }
                        LazyVGrid(columns: [GridItem(.flexible(), spacing: 20), GridItem(.flexible(), spacing: 20)], spacing: 28) {
                            ForEach(Array(shown.enumerated()), id: \.element.id) { index, playlist in
                                PlaylistTile(playlist: playlist, api: api, index: index, onOpen: { path.append($0) },
                                             onChange: { Task { await load(api) } })
                            }
                        }
                        // Room under the last row so it scrolls clear of the tab bar.
                        .padding(.horizontal, 16).padding(.top, 4).padding(.bottom, 130)
                        if loaded && playlists.isEmpty && errorMessage == nil {
                            EmptyMessage(text: "Aucune playlist.")
                        }
                    }
                }
                .refreshable { await load(api) }
                .task { await load(api) }
                .sheet(isPresented: $showNew) {
                    TextPromptSheet(title: "Nouvelle playlist", placeholder: "Titre", action: "Créer") { title in
                        let _: PlaylistSummary = try await api.post("/api/playlists", body: ["title": title])
                        await load(api)
                    }
                }
                .sheet(isPresented: $showImport) {
                    TextPromptSheet(title: "Importer une playlist YouTube", placeholder: "Adresse de la playlist", action: "Importer", keyboardURL: true) { url in
                        let _: QueuedJob? = try? await api.post("/api/playlists/import-url", body: ["url": url])
                        await load(api)
                    }
                }
                .navigationDestination(for: PlaylistSummary.self) { PlaylistView(playlist: $0) }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func load(_ api: RatonAPI) async {
        do {
            playlists = try await api.get("/api/playlists")
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
        loaded = true
    }
}

/// A plain button style that only reports whether the finger is down on it.
struct PressReportingStyle: ButtonStyle {
    @Binding var pressed: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .onChange(of: configuration.isPressed) { pressed = $0 }
    }
}

/// A playlist of the grid, like the web's `.pl-card`: two layers behind the cover (the stack), the
/// source chip, the "⋯" menu, the number of videos, then the title.
struct PlaylistTile: View {
    let playlist: PlaylistSummary
    let api: RatonAPI
    // Rank in the grid: the entrance of the web's `pl-card-in` is staggered by 50 ms, up to the sixth.
    var index = 0
    let onOpen: (PlaylistSummary) -> Void
    let onChange: () -> Void
    @State private var confirmDelete = false
    @State private var appeared = false
    // The finger is down on the tile: the web's hover (`.pl-card:hover`), played on touch.
    @State private var pressed = false
    @State private var raised = false
    @State private var opening = false
    @State private var holdTask: Task<Void, Never>?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var lifted: Bool { raised && !reduceMotion }

    private var chip: String {
        playlist.source == "url" ? "URL YouTube" : playlist.source == "csv" ? "CSV Takeout" : "Manuelle"
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Button { open() } label: {
                VStack(alignment: .leading, spacing: 10) {
                    ZStack(alignment: .bottomTrailing) {
                        cover
                        // The web's dark scrim badge: 82 % slate, white text, 6 pt corners.
                        Text("\(playlist.itemCount) vidéo\(playlist.itemCount == 1 ? "" : "s")")
                            .font(.raton(12, .bold)).foregroundStyle(.white)
                            .padding(.horizontal, 8).padding(.vertical, 2)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: 0x0F172A).opacity(0.82)))
                            .padding(8)
                    }
                    .overlay(alignment: .topLeading) {
                        Text(chip).font(.raton(12, .semibold)).foregroundStyle(Theme.text)
                            .padding(.horizontal, 10).padding(.vertical, 3)
                            .background(Capsule().fill(Color.white.opacity(0.92))).padding(8)
                    }
                    .background(stackLayers)
                    .padding(.top, 12)
                    // `.pl-card-link:hover .pl-card-title`: the title turns terracotta.
                    Text(playlist.title).font(.raton(15, .bold)).foregroundStyle(lifted ? Theme.primary : Theme.text)
                        .animation(.easeOut(duration: 0.2), value: lifted)
                        .lineLimit(2, reservesSpace: true).multilineTextAlignment(.leading)
                }
                // translateY(-4px), 200 ms
                .offset(y: lifted ? -4 : 0)
                .animation(.easeOut(duration: 0.2), value: lifted)
            }
            .buttonStyle(PressReportingStyle(pressed: $pressed))
            // A finger resting on the tile lifts it; one that moves to scroll never does, because the
            // scroll cancels the press before the short wait is over.
            .onChange(of: pressed) { down in
                holdTask?.cancel()
                if down {
                    holdTask = Task {
                        try? await Task.sleep(nanoseconds: 90_000_000)
                        if !Task.isCancelled { raised = true }
                    }
                } else if !opening {
                    raised = false
                }
            }
            Menu {
                Button(role: .destructive) { confirmDelete = true } label: { Label("Supprimer", systemImage: "trash") }
                Button { Task { await duplicate() } } label: { Label("Dupliquer", systemImage: "plus.square.on.square") }
            } label: {
                Image(systemName: "ellipsis").font(.system(size: 14, weight: .bold)).foregroundStyle(Theme.textSoft)
                    .frame(width: 34, height: 34).background(Circle().fill(Color.white.opacity(0.92)))
            }
            .padding(.trailing, 8).padding(.top, 20)
            .accessibilityLabel("Actions sur \(playlist.title)")
        }
        .confirmationDialog("Supprimer « \(playlist.title) » ? Les vidéos sont conservées.",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Supprimer", role: .destructive) { Task { await delete() } }
        }
        // pl-card-in: 260 ms ease-out, from 14 pt lower and transparent.
        .opacity(appeared || reduceMotion ? 1 : 0)
        .offset(y: appeared || reduceMotion ? 0 : 14)
        .onAppear {
            withAnimation(.easeOut(duration: 0.26).delay(Double(min(index, 6)) * 0.05)) { appeared = true }
        }
    }

    @ViewBuilder
    private var cover: some View {
        // The 16:9 frame is fixed first and the picture only fills it: a thumbnail with another ratio
        // (4:3 with black bars) must never change the tile's height.
        Color.clear
            .aspectRatio(16 / 9, contentMode: .fit)
            .frame(maxWidth: .infinity)
            .overlay {
                if let id = playlist.coverVideoId, playlist.coverHasThumbnail {
                    AsyncImage(url: api.url("/api/videos/\(id)/thumbnail?w=320")) { image in
                        image.resizable().scaledToFill()
                    } placeholder: { Theme.surfaceMuted }
                } else {
                    // The web's empty cover: sand to the warm shadow tint, at 135°.
                    LinearGradient(colors: [Color(hex: 0xE9B98A), Color(hex: 0x7C2D12)], startPoint: .topLeading, endPoint: .bottomTrailing)
                }
            }
            .clipped()
            .clipShape(RoundedRectangle(cornerRadius: 14))
            // brightness(1.06) saturate(1.08)
            .brightness(lifted ? 0.04 : 0).saturation(lifted ? 1.08 : 1)
            .animation(.easeOut(duration: 0.2), value: lifted)
    }

    /// The two cards peeking out above the cover.
    private var stackLayers: some View {
        ZStack {
            // The two layers fan out when lifted: translateY(-5px) rotate(-1.5deg) and translateY(-3px) rotate(1deg), 250 ms.
            RoundedRectangle(cornerRadius: 14).fill(Theme.borderStrong)
                .padding(.horizontal, 16).offset(y: lifted ? -15 : -10)
                .rotationEffect(.degrees(lifted ? -1.5 : 0))
            RoundedRectangle(cornerRadius: 14).fill(Theme.surfaceMuted)
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.border, lineWidth: 1))
                .padding(.horizontal, 8).offset(y: lifted ? -8 : -5)
                .rotationEffect(.degrees(lifted ? 1 : 0))
        }
        .animation(.easeOut(duration: 0.25), value: lifted)
    }

    /// A tap plays the lift first, then opens the playlist.
    private func open() {
        holdTask?.cancel()
        guard !reduceMotion else { onOpen(playlist); return }
        opening = true
        raised = true
        Task {
            try? await Task.sleep(nanoseconds: 260_000_000)
            onOpen(playlist)
            try? await Task.sleep(nanoseconds: 500_000_000)
            opening = false
            raised = false
        }
    }

    private func duplicate() async {
        let _: PlaylistSummary? = try? await api.post("/api/playlists/\(playlist.id)/duplicate")
        onChange()
    }

    private func delete() async {
        try? await api.delete("/api/playlists/\(playlist.id)")
        onChange()
    }
}

/// A playlist: its fiches in order, with the queue player on top; a tap on a row plays it, the
/// "i" opens its fiche.
struct PlaylistView: View {
    let playlist: PlaylistSummary
    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @State private var detail: PlaylistDetail?
    @State private var errorMessage: String?
    @State private var notice: String?
    @State private var defaultMode: MediaKind?
    @State private var showRename = false
    @State private var showCategories = false
    @State private var confirmDelete = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        topBar(api)
                        ErrorMessage(text: errorMessage)
                        if let notice {
                            Text(notice).font(.raton(14, .medium)).foregroundStyle(Theme.textSoft)
                                .padding(.horizontal, 16).padding(.bottom, 8)
                        }
                        if let detail {
                            PlaylistPlayerPanel(detail: detail, api: api)
                            PlaylistTitleBlock(detail: detail)
                        }
                        ForEach(detail?.items ?? []) { item in
                            let playable = item.hasFile(player.queueMode)
                            let isCurrent = player.queue?.playlistID == playlist.id && player.track?.videoID == item.videoId
                            Button {
                                if player.queue?.playlistID == playlist.id {
                                    player.playQueueTrack(item.videoId)
                                } else if let detail {
                                    player.playQueue(playlistID: detail.id, title: detail.title, free: detail.freeListening,
                                                     tracks: detail.items.map(\.queueTrack), startID: item.videoId, api: api)
                                }
                            } label: {
                                ListRow(tint: isCurrent ? Theme.primary : nil) {
                                    HStack(spacing: 12) {
                                        Thumbnail(videoID: item.videoId, hasThumbnail: item.hasThumbnail, api: api)
                                            .frame(width: 96, height: 54).clipped()
                                            .clipShape(RoundedRectangle(cornerRadius: 6))
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(item.title)
                                                .font(.raton(16, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                                            if let channel = item.channelName {
                                                Text(channel).font(.raton(14, .semibold))
                                                    .foregroundStyle(Theme.textMuted).lineLimit(1)
                                            }
                                            Text(playable
                                                 ? Format.clock(Double(item.durationSeconds))
                                                 : "Ignorée : \(player.queueMode == .audio ? "audio" : "vidéo") non téléchargé\(player.queueMode == .audio ? "" : "e")")
                                                .font(.raton(13)).foregroundStyle(Theme.textMuted)
                                        }
                                        Spacer(minLength: 0)
                                        if isCurrent {
                                            Image(systemName: player.isPlaying ? "speaker.wave.2.fill" : "pause.fill")
                                                .foregroundStyle(Theme.primary)
                                        } else if item.seen && !(detail?.freeListening ?? false) {
                                            Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.textFaint)
                                        }
                                        NavigationLink(value: item.videoId) {
                                            Image(systemName: "info.circle").font(.system(size: 22))
                                                .foregroundStyle(Theme.textMuted).frame(width: 36, height: 44)
                                        }
                                        .accessibilityLabel("Ouvrir la fiche")
                                    }
                                }
                                .opacity(playable ? 1 : 0.5)
                            }
                            .buttonStyle(.plain)
                            .contextMenu {
                                Button { Task { await move(api, item, "up") } } label: { Label("Monter", systemImage: "arrow.up") }
                                Button { Task { await move(api, item, "down") } } label: { Label("Descendre", systemImage: "arrow.down") }
                                Button(role: .destructive) { Task { await remove(api, item) } } label: {
                                    Label("Retirer de la playlist", systemImage: "minus.circle")
                                }
                            }
                        }
                        if let detail, detail.items.isEmpty {
                            EmptyMessage(text: "Cette playlist est vide.")
                        }
                    }
                }
                .refreshable { await load(api) }
                .task { await load(api) }
                .onAppear {
                    defaultMode = PlaylistDefaultMode.get(playlist.id)
                    // The page opens on the playlist's own format, unless something else is already playing.
                    if player.queue == nil, let defaultMode { player.queueMode = defaultMode }
                }
                // The next track ends up Vu: read the rows again to show it.
                .onChange(of: player.track) { _ in Task { await load(api) } }
                .sheet(isPresented: $showRename) {
                    TextPromptSheet(title: "Renommer", placeholder: "Titre", action: "Enregistrer", initial: detail?.title ?? playlist.title) { title in
                        let _: PlaylistSummary = try await api.put("/api/playlists/\(playlist.id)/title", body: ["title": title])
                        await load(api)
                    }
                }
                .sheet(isPresented: $showCategories) {
                    CategoryPickerSheet(api: api, selected: detail?.categories ?? []) { chosen in
                        await act(api) { let _: PlaylistCategoriesReply = try await api.put(
                            "/api/playlists/\(playlist.id)/categories", body: ["categories": chosen]) }
                    }
                }
                .confirmationDialog("Supprimer cette playlist ? Les fiches restent.", isPresented: $confirmDelete, titleVisibility: .visible) {
                    Button("Supprimer", role: .destructive) {
                        Task { await act(api) { try await api.delete("/api/playlists/\(playlist.id)") }; dismiss() }
                    }
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    /// The top bar of a fiche: back, the Vidéo / Audio switch in the middle, the "⋯" menu.
    private func topBar(_ api: RatonAPI) -> some View {
        ZStack {
            HStack {
                Button { dismiss() } label: { Image(systemName: "arrow.left") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Retour")
                Spacer()
                moreMenu(api)
            }
            MediaModePill(mode: player.queueMode, onSelect: { player.setQueueMode($0) })
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
    }

    private func moreMenu(_ api: RatonAPI) -> some View {
        Menu {
                        Menu {
                ForEach([MediaKind.video, MediaKind.audio], id: \.self) { kind in
                    Button {
                        PlaylistDefaultMode.set(playlist.id, kind)
                        defaultMode = kind
                        // Nothing else is playing: the player switches now, not only the next time.
                        if player.queue == nil { player.queueMode = kind }
                    } label: {
                        Label(kind == .video ? "Vidéo" : "Audio",
                              systemImage: defaultMode == kind ? "checkmark" : (kind == .video ? "video" : "waveform"))
                    }
                }
            } label: { Label("Format par défaut", systemImage: "play.rectangle") }
            Button { Task { await downloadAll(api, "audio") } } label: {
                Label("Télécharger tout l'audio", systemImage: "arrow.down.circle")
            }
            Button { Task { await downloadAll(api, "video") } } label: {
                Label("Télécharger toute la vidéo", systemImage: "arrow.down.circle")
            }
            Divider()
            Button { showRename = true } label: { Label("Renommer", systemImage: "pencil") }
                        Button { showCategories = true } label: { Label("Catégories", systemImage: "tag") }
                        Button {
                            Task { await act(api) { let _: PlaylistSummary = try await api.put(
                                "/api/playlists/\(playlist.id)/free-listening",
                                body: ["enabled": !(detail?.freeListening ?? false)]) } }
                        } label: {
                            Label(detail?.freeListening == true ? "Désactiver l'écoute libre" : "Activer l'écoute libre",
                                  systemImage: "infinity")
                        }
                        Menu("Trier") {
                            ForEach([("added", "Date d'ajout"), ("duration", "Durée"), ("title", "Titre"), ("reverse", "Inverser")], id: \.0) { sort in
                                Button(sort.1) {
                                    Task { await act(api) { let _: PlaylistDetail = try await api.post(
                                        "/api/playlists/\(playlist.id)/sort", body: ["by": sort.0]) } }
                                }
                            }
                        }
                        Button {
                            Task { await act(api) { let _: PlaylistSummary = try await api.post(
                                "/api/playlists/\(playlist.id)/duplicate") } }
                        } label: { Label("Dupliquer", systemImage: "plus.square.on.square") }
                        Button(role: .destructive) { confirmDelete = true } label: {
                            Label("Supprimer la playlist", systemImage: "trash")
                        }
        } label: { Image(systemName: "ellipsis") }
        .buttonStyle(CircleButtonStyle())
        .accessibilityLabel("Plus d'options")
    }

    /// Queues the download of the files the videos of the playlist still lack (`audio` or `video`).
    private func downloadAll(_ api: RatonAPI, _ type: String) async {
        errorMessage = nil
        do {
            let queued: PlaylistDownloads = try await api.post("/api/playlists/\(playlist.id)/download/\(type)")
            let count = queued.jobs.count
            if type == "audio" {
                notice = count == 0 ? "Tout l'audio est déjà téléchargé."
                    : "\(count) téléchargement\(count > 1 ? "s" : "") audio lancé\(count > 1 ? "s" : "")."
            } else {
                notice = count == 0 ? "Toute la vidéo est déjà téléchargée."
                    : "\(count) téléchargement\(count > 1 ? "s" : "") vidéo lancé\(count > 1 ? "s" : "")."
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Runs a change on the playlist, then reads it back.
    private func act(_ api: RatonAPI, _ change: () async throws -> Void) async {
        do {
            try await change()
            await load(api)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func move(_ api: RatonAPI, _ item: PlaylistItem, _ direction: String) async {
        await act(api) {
            let _: PlaylistDetail = try await api.post(
                "/api/playlists/\(playlist.id)/items/\(item.itemId)/move", body: ["direction": direction])
        }
    }

    private func remove(_ api: RatonAPI, _ item: PlaylistItem) async {
        await act(api) { try await api.delete("/api/playlists/\(playlist.id)/items/\(item.itemId)") }
    }

    private func load(_ api: RatonAPI) async {
        do {
            let fresh: PlaylistDetail = try await api.get("/api/playlists/\(playlist.id)")
            detail = fresh
            // A move, a removal or a download changes what the playing queue holds.
            player.updateQueue(playlistID: fresh.id, free: fresh.freeListening, tracks: fresh.items.map(\.queueTrack))
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
    }
}

/// Only the status of a categories update matters.
struct PlaylistCategoriesReply: Codable {
    let labelledCount: Int
}

/// A one-field sheet (a title, an address) with its action; a refusal stays in the sheet.
struct TextPromptSheet: View {
    let title: String
    let placeholder: String
    let action: String
    var keyboardURL = false
    var initial = ""
    let run: (String) async throws -> Void
    @State private var text = ""
    @State private var errorMessage: String?
    @State private var busy = false
    @Environment(\.dismiss) private var dismiss

    init(title: String, placeholder: String, action: String, keyboardURL: Bool = false, initial: String = "",
         run: @escaping (String) async throws -> Void) {
        self.title = title
        self.placeholder = placeholder
        self.action = action
        self.keyboardURL = keyboardURL
        self.initial = initial
        self.run = run
        _text = State(initialValue: initial)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                TextField(placeholder, text: $text)
                    .font(.raton(17))
                    .keyboardType(keyboardURL ? .URL : .default)
                    .textInputAutocapitalization(keyboardURL ? .never : .sentences)
                    .autocorrectionDisabled(keyboardURL)
                    .padding(.horizontal, 18).padding(.vertical, 14)
                    .surface(in: Capsule())
                ErrorMessage(text: errorMessage)
                Button(busy ? "…" : action) {
                    busy = true
                    Task {
                        do {
                            try await run(text)
                            dismiss()
                        } catch {
                            errorMessage = error.localizedDescription
                        }
                        busy = false
                    }
                }
                .buttonStyle(PillButtonStyle())
                .disabled(busy || text.trimmingCharacters(in: .whitespaces).isEmpty)
                Spacer()
            }
            .padding(16)
            .ratonPage()
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } } }
        }
    }
}

/// What the playlist player opens on, remembered for each playlist on this iPhone.
enum PlaylistDefaultMode {
    private static func key(_ id: Int) -> String { "playlistDefaultMode.\(id)" }

    static func get(_ id: Int) -> MediaKind? {
        UserDefaults.standard.string(forKey: key(id)).flatMap(MediaKind.init(rawValue:))
    }

    static func set(_ id: Int, _ kind: MediaKind) {
        UserDefaults.standard.set(kind.rawValue, forKey: key(id))
    }
}

/// `POST /api/playlists/{id}/download/{type}`: one job per video that lacks that file.
struct PlaylistDownloads: Codable {
    let jobs: [QueuedJob]
}
