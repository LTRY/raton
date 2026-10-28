import SwiftUI

struct PlaylistsView: View {
    @EnvironmentObject private var state: AppState
    @State private var playlists: [PlaylistSummary] = []
    @State private var loaded = false
    @State private var errorMessage: String?
    @State private var showNew = false
    @State private var showImport = false

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Playlists") {
                            Menu {
                                Button { showNew = true } label: { Label("Nouvelle playlist", systemImage: "plus") }
                                Button { showImport = true } label: { Label("Importer depuis YouTube", systemImage: "square.and.arrow.down") }
                            } label: { Image(systemName: "plus") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Ajouter une playlist")
                        }
                        ErrorMessage(text: errorMessage)
                        ForEach(playlists) { playlist in
                            NavigationLink(value: playlist) {
                                ListRow {
                                    HStack(spacing: 14) {
                                        if let cover = playlist.coverVideoId {
                                            Thumbnail(videoID: cover, hasThumbnail: playlist.coverHasThumbnail, api: api)
                                                .frame(width: 96, height: 54).clipped()
                                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                        }
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(playlist.title)
                                                .font(.raton(17, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                                            Text("\(playlist.itemCount) fiche\(playlist.itemCount > 1 ? "s" : "")")
                                                .font(.raton(14)).foregroundStyle(Theme.textMuted)
                                        }
                                        Spacer(minLength: 0)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
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

/// A playlist: its fiches in order, with the queue player on top; a tap on a row plays it, the
/// "i" opens its fiche.
struct PlaylistView: View {
    let playlist: PlaylistSummary
    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @State private var detail: PlaylistDetail?
    @State private var errorMessage: String?
    @State private var showRename = false
    @State private var showCategories = false
    @State private var confirmDelete = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: detail?.title ?? playlist.title, back: true) {
                            Menu {
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
                        ErrorMessage(text: errorMessage)
                        if let detail { PlaylistPlayerPanel(detail: detail, api: api) }
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
                    .glass(in: Capsule())
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
