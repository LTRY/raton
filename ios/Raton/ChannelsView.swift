import SwiftUI

final class ChannelsModel: ObservableObject {
    @Published var items: [ChannelItem] = []
    @Published var count = 0
    @Published var errorMessage: String?
    @Published var loaded = false
    private var page = 0
    private var totalPages = 1
    private var loading = false

    // The web's defaults: only the rated channels, by last media played.
    @Published var ratedOnly = true
    @Published var sort = "activity"

    private func query(page: Int, search: String) -> [String: String] {
        var query = ["page": String(page), "sort": sort, "rated": ratedOnly ? "true" : "false"]
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
    @StateObject fileprivate var model = ChannelsModel()
    @State private var search = ""
    @State private var showAdd = false
    // A NavigationLink inside a Menu does nothing when tapped, so the "+" entry sets this instead.
    @State private var showYoutubeSearch = false

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Chaînes", badge: model.count) {
                            Menu {
                                Button { showAdd = true } label: { Label("Ajouter par adresse", systemImage: "link") }
                                Button { showYoutubeSearch = true } label: {
                                    Label("Chercher sur YouTube", systemImage: "magnifyingglass")
                                }
                            } label: { Image(systemName: "plus") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Ajouter une chaîne")
                        }
                        SearchField(placeholder: "Rechercher une chaîne", text: $search) {
                            Task { await model.reload(api: api, search: search) }
                        }
                        filterRow(api)
                        ErrorMessage(text: model.errorMessage)
                        ForEach(model.items) { channel in
                            ChannelCard(channel: channel, api: api)
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
                .navigationDestination(isPresented: $showYoutubeSearch) { YoutubeSearchView() }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }
}

extension ChannelsView {
    private static let sorts = [
        ("activity", "Dernier média joué"), ("rating", "Note"), ("alpha", "A-Z"), ("added", "Ajoutées récemment"),
    ]

    /// "★ Notées" and the sort, the two controls under the search of the web page.
    fileprivate func filterRow(_ api: RatonAPI) -> some View {
        HStack(spacing: 14) {
            Button {
                model.ratedOnly.toggle()
                Task { await model.reload(api: api, search: search) }
            } label: {
                Label("Notées", systemImage: "star.fill")
                    .font(.raton(15, .bold))
                    .foregroundStyle(model.ratedOnly ? Theme.primary : Theme.textSoft)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .surface(in: Capsule(), tint: model.ratedOnly ? Theme.primary : nil, interactive: true)
            }
            Menu {
                ForEach(Self.sorts, id: \.0) { sort in
                    Button {
                        model.sort = sort.0
                        Task { await model.reload(api: api, search: search) }
                    } label: {
                        if model.sort == sort.0 { Label(sort.1, systemImage: "checkmark") } else { Text(sort.1) }
                    }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "line.3.horizontal.decrease").font(.system(size: 13))
                    Text(Self.sorts.first { $0.0 == model.sort }?.1 ?? "").font(.raton(15, .bold))
                    Image(systemName: "chevron.down").font(.system(size: 10, weight: .bold))
                }
                .foregroundStyle(Theme.textSoft)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.bottom, 8)
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
                    .surface(in: Capsule())
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
