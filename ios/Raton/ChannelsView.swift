import SwiftUI

final class ChannelsModel: ObservableObject {
    @Published var items: [ChannelItem] = []
    @Published var count = 0
    @Published var errorMessage: String?
    @Published var loaded = false
    private var page = 0
    private var totalPages = 1
    private var loading = false

    private func query(page: Int, search: String) -> [String: String] {
        var query = ["page": String(page)]
        if !search.isEmpty { query["q"] = search }
        return query
    }

    func reload(api: RatonAPI, search: String) async {
        do {
            let reply: ChannelsReply = try await api.get("/api/channels", query: query(page: 1, search: search))
            items = reply.items
            count = reply.channelCount
            page = reply.page
            totalPages = reply.totalPages
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
        loaded = true
    }

    func loadMore(api: RatonAPI, search: String, after channel: ChannelItem) async {
        guard channel.id == items.last?.id, page < totalPages, !loading else { return }
        loading = true
        defer { loading = false }
        if let reply: ChannelsReply = try? await api.get(
            "/api/channels", query: query(page: page + 1, search: search)) {
            let known = Set(items.map(\.id))
            items += reply.items.filter { !known.contains($0.id) }
            page = reply.page
            totalPages = reply.totalPages
        }
    }
}

struct ChannelsView: View {
    @EnvironmentObject private var state: AppState
    @StateObject private var model = ChannelsModel()
    @State private var search = ""
    @State private var showAdd = false

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Chaînes") {
                            Menu {
                                Button { showAdd = true } label: { Label("Ajouter par adresse", systemImage: "link") }
                                NavigationLink { YoutubeSearchView() } label: {
                                    Label("Chercher sur YouTube", systemImage: "magnifyingglass")
                                }
                            } label: { Image(systemName: "plus") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Ajouter une chaîne")
                        }
                        SearchField(placeholder: "Rechercher une chaîne", text: $search) {
                            Task { await model.reload(api: api, search: search) }
                        }
                        ErrorMessage(text: model.errorMessage)
                        ForEach(model.items) { channel in
                            NavigationLink(value: channel) {
                                ListRow {
                                    HStack(spacing: 14) {
                                        AvatarView(path: channel.avatarUrl, name: channel.name, api: api)
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(channel.name)
                                                .font(.raton(17, .bold)).foregroundStyle(Theme.text)
                                                .lineLimit(2)
                                            Text("\(channel.videoCount) fiche\(channel.videoCount > 1 ? "s" : "")")
                                                .font(.raton(14)).foregroundStyle(Theme.textMuted)
                                        }
                                        Spacer(minLength: 0)
                                        if channel.autoMetadataEnabled || channel.autoShortsEnabled {
                                            Image(systemName: "bell.fill").foregroundStyle(Theme.primary)
                                        }
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                            .task { await model.loadMore(api: api, search: search, after: channel) }
                        }
                        if model.loaded && model.items.isEmpty && model.errorMessage == nil {
                            EmptyMessage(text: "Aucune chaîne.")
                        }
                    }
                }
                .refreshable { await model.reload(api: api, search: search) }
                .task { await model.reload(api: api, search: search) }
                .sheet(isPresented: $showAdd) {
                    AddChannelSheet(api: api) { Task { await model.reload(api: api, search: search) } }
                }
                .navigationDestination(for: ChannelItem.self) { ChannelView(channel: $0) }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }
}

/// A channel: its two cloches (vidéos, shorts) and its fiches.
struct ChannelView: View {
    let channel: ChannelItem
    @EnvironmentObject private var state: AppState
    @StateObject private var model: LibraryModel
    @State private var videosBell: Bool
    @State private var shortsBell: Bool
    @State private var busy = false
    @State private var errorMessage: String?
    @State private var rating: Int
    @State private var categories: [String]
    @State private var showCategories = false
    @State private var confirmDelete = false
    @Environment(\.dismiss) private var dismiss

    init(channel: ChannelItem) {
        _rating = State(initialValue: channel.rating)
        _categories = State(initialValue: channel.categories)
        self.channel = channel
        _model = StateObject(wrappedValue: LibraryModel(channelID: channel.id))
        _videosBell = State(initialValue: channel.autoMetadataEnabled)
        _shortsBell = State(initialValue: channel.autoShortsEnabled)
    }

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: channel.name, back: true) {
                            Menu {
                                Button { showCategories = true } label: { Label("Catégories", systemImage: "tag") }
                                Button { Task { await refreshProfile(api) } } label: {
                                    Label("Actualiser le profil", systemImage: "arrow.clockwise")
                                }
                                Button(role: .destructive) { confirmDelete = true } label: {
                                    Label("Supprimer la chaîne", systemImage: "trash")
                                }
                            } label: { Image(systemName: "ellipsis") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Plus d'options")
                        }
                        HStack(spacing: 6) {
                            CategoryChips(categories: categories, api: api)
                            Spacer()
                            ForEach(1...5, id: \.self) { star in
                                Button { Task { await setRating(api, rating == star ? 0 : star) } } label: {
                                    Image(systemName: "star.fill").font(.system(size: 22))
                                        .foregroundStyle(star <= rating ? Theme.amber : Color(hex: 0xF6E4DD))
                                }
                            }
                        }
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        HStack(spacing: 8) {
                            bellButton("Cloche vidéos", isOn: videosBell) { toggle(api, "videos") }
                            bellButton("Cloche shorts", isOn: shortsBell) { toggle(api, "shorts") }
                        }
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        ErrorMessage(text: errorMessage)
                        VideoList(model: model, api: api, search: "")
                    }
                }
                .refreshable { await model.reload(api: api, search: "") }
                .task { await model.reload(api: api, search: "") }
                .sheet(isPresented: $showCategories) {
                    CategoryPickerSheet(api: api, selected: categories) { chosen in
                        do {
                            let _: ChannelState = try await api.put(
                                "/api/channels/\(channel.id)/categories", body: ["categories": chosen])
                            categories = chosen
                        } catch { errorMessage = error.localizedDescription }
                    }
                }
                .confirmationDialog("Supprimer cette chaîne et ses fiches ?", isPresented: $confirmDelete, titleVisibility: .visible) {
                    Button("Supprimer", role: .destructive) {
                        Task {
                            do {
                                try await api.delete("/api/channels/\(channel.id)")
                                dismiss()
                            } catch { errorMessage = error.localizedDescription }
                        }
                    }
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func setRating(_ api: RatonAPI, _ value: Int) async {
        do {
            let _: ChannelState = try await api.put("/api/channels/\(channel.id)/rating", body: ["rating": value])
            rating = value
        } catch { errorMessage = error.localizedDescription }
    }

    private func refreshProfile(_ api: RatonAPI) async {
        let _: QueuedJob? = try? await api.post("/api/channels/\(channel.id)/refresh-profile")
    }

    private func bellButton(_ title: String, isOn: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: isOn ? "bell.fill" : "bell")
        }
        .buttonStyle(SandButtonStyle(active: isOn))
        .disabled(busy)
    }

    /// The cloche is the user's own follow switch; the back decides what turning it on imports.
    private func toggle(_ api: RatonAPI, _ section: String) {
        let enable = section == "videos" ? !videosBell : !shortsBell
        busy = true
        errorMessage = nil
        Task {
            do {
                let reply: ChannelBellReply = try await api.put(
                    "/api/channels/\(channel.id)/bells/\(section)", body: ["enabled": enable])
                videosBell = reply.channel.autoMetadataEnabled
                shortsBell = reply.channel.autoShortsEnabled
            } catch {
                errorMessage = error.localizedDescription
            }
            busy = false
        }
    }
}

/// Add a channel by its URL or @handle (`POST /api/channels`).
struct AddChannelSheet: View {
    let api: RatonAPI
    let onAdded: () -> Void
    @State private var url = ""
    @State private var errorMessage: String?
    @State private var busy = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                Text("Adresse de la chaîne ou @identifiant").font(.raton(15, .semibold)).foregroundStyle(Theme.textSoft)
                TextField("https://www.youtube.com/@…", text: $url)
                    .font(.raton(17)).keyboardType(.URL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .padding(.horizontal, 18).padding(.vertical, 14)
                    .background(Capsule().fill(Color.white))
                    .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
                ErrorMessage(text: errorMessage)
                Button(busy ? "Ajout…" : "Ajouter") { Task { await add() } }
                    .buttonStyle(PillButtonStyle())
                    .disabled(busy || url.trimmingCharacters(in: .whitespaces).isEmpty)
                Spacer()
            }
            .padding(16)
            .ratonPage()
            .navigationTitle("Ajouter une chaîne")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } } }
        }
    }

    private func add() async {
        busy = true
        defer { busy = false }
        do {
            let _: ChannelItem = try await api.post("/api/channels", body: ["url": url, "rating": 1])
            onAdded()
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
