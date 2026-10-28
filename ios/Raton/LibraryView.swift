import SwiftUI

/// `GET /api/library`: the Bibliothèque (every fiche), or one channel's fiches, 50 per page, with the
/// search box; what the list leaves out (Vu, Indésirée) is the back's default.
final class LibraryModel: ObservableObject {
    @Published var items: [VideoCard] = []
    @Published var total = 0
    @Published var errorMessage: String?
    @Published var loaded = false
    private var page = 0
    private var totalPages = 1
    private var loading = false
    let channelID: Int?

    init(channelID: Int? = nil) { self.channelID = channelID }

    @Published var filters = LibraryFilters()

    private func query(page: Int, search: String) -> [URLQueryItem] {
        var items = [URLQueryItem(name: "page", value: String(page))]
        if !search.isEmpty { items.append(URLQueryItem(name: "q", value: search)) }
        if let channelID { items.append(URLQueryItem(name: "channel_id", value: String(channelID))) }
        return items + filters.queryItems
    }

    func reload(api: RatonAPI, search: String) async {
        do {
            let reply: LibraryReply = try await api.get("/api/library", items: query(page: 1, search: search))
            items = reply.items
            total = reply.total
            page = reply.page
            totalPages = reply.totalPages
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
        loaded = true
    }

    func loadMore(api: RatonAPI, search: String, after card: VideoCard) async {
        guard card.id == items.last?.id, page < totalPages, !loading else { return }
        loading = true
        defer { loading = false }
        do {
            let reply: LibraryReply = try await api.get(
                "/api/library", items: query(page: page + 1, search: search))
            let known = Set(items.map(\.id))
            items += reply.items.filter { !known.contains($0.id) }
            page = reply.page
            totalPages = reply.totalPages
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

/// A scrolling list of fiche rows with infinite paging; shared by the Bibliothèque and a channel page.
struct VideoList: View {
    @ObservedObject var model: LibraryModel
    let api: RatonAPI
    let search: String

    var body: some View {
        LazyVStack(spacing: 0) {
            ErrorMessage(text: model.errorMessage)
            ForEach(model.items) { card in
                NavigationLink(value: card.id) {
                    VideoRow(card: card, api: api)
                }
                .buttonStyle(.plain)
                .task { await model.loadMore(api: api, search: search, after: card) }
            }
            if model.loaded && model.items.isEmpty && model.errorMessage == nil {
                EmptyMessage(text: "Aucune fiche.")
            }
        }
    }
}

struct LibraryView: View {
    @EnvironmentObject private var state: AppState
    @StateObject private var model = LibraryModel()
    @State private var search = ""
    @State private var showFilters = false

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Bibliothèque")
                        SearchField(placeholder: "Rechercher une fiche", text: $search) {
                            Task { await model.reload(api: api, search: search) }
                        }
                        Button { showFilters = true } label: {
                            Label(model.filters.isDefault ? "Filtres" : "Filtres actifs", systemImage: "slider.horizontal.3")
                        }
                        .buttonStyle(SandButtonStyle(active: !model.filters.isDefault, fill: false))
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        if model.loaded {
                            Text("\(model.total) fiche\(model.total > 1 ? "s" : "")")
                                .font(.raton(15)).foregroundStyle(Theme.textMuted)
                                .padding(.horizontal, 16).padding(.bottom, 8)
                        }
                        VideoList(model: model, api: api, search: search)
                    }
                }
                .refreshable { await model.reload(api: api, search: search) }
                .task { await model.reload(api: api, search: search) }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
                .sheet(isPresented: $showFilters) {
                    LibraryFiltersSheet(api: api, filters: model.filters) { chosen in
                        model.filters = chosen
                        Task { await model.reload(api: api, search: search) }
                    }
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }
}
