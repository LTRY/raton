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

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Chaînes")
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

    init(channel: ChannelItem) {
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
                        PageHeader(title: channel.name, back: true)
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
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
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
