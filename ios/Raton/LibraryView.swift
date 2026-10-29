import SwiftUI

/// `GET /api/library`: the Bibliothèque (every fiche), or one channel's fiches, 50 per page, with the
/// search box; what the list leaves out (Vu, Indésirée) is the back's default.
final class LibraryModel: ObservableObject {
    @Published var items: [VideoCard] = []
    @Published var total = 0
    @Published var errorMessage: String?
    @Published var loaded = false
    // Only a channel page uses these (see `LibraryReply`).
    @Published var counts: [String: Int] = [:]
    @Published var exploreNextPage = 1
    @Published var explorePageSize = 25
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
            counts = reply.counts ?? [:]
            exploreNextPage = reply.exploreNextPage ?? 1
            explorePageSize = reply.explorePageSize ?? 25
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
    // A channel page shows the publication date under the title, not the channel's name.
    var dateLine = false

    /// The "⋮" of a row: Vu and Indésirée, the same two toggles as the fiche, then the list is read again.
    private func rowMenu(_ card: VideoCard) -> some View {
        Menu {
            Button {
                Task { await setState(card, card.shownState == "watched" ? "unwatched" : "watched") }
            } label: {
                Label(card.shownState == "watched" ? "Marquer comme non vu" : "Marquer comme vu",
                      systemImage: card.shownState == "watched" ? "eye.slash" : "checkmark.circle")
            }
            Button {
                Task { await setState(card, card.shownState == "hidden" ? "clear" : "hidden") }
            } label: {
                Label(card.shownState == "hidden" ? "Ne plus masquer" : "Marquer indésirée", systemImage: "eye.slash")
            }
        } label: {
            Image(systemName: "ellipsis").rotationEffect(.degrees(90))
                .font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.textMuted)
                .frame(width: 40, height: 40).contentShape(Rectangle())
        }
        .padding(.top, 10).padding(.trailing, 16)
        .accessibilityLabel("Actions sur \(card.title)")
    }

    private func setState(_ card: VideoCard, _ state: String) async {
        let _: VideoState? = try? await api.put("/api/videos/\(card.id)/list-state", body: ["state": state])
        await model.reload(api: api, search: search)
    }

    var body: some View {
        LazyVStack(spacing: 0) {
            ErrorMessage(text: model.errorMessage)
            ForEach(model.items) { card in
                ZStack(alignment: .topTrailing) {
                    NavigationLink(value: card.id) {
                        VideoRow(card: card, api: api, dateLine: dateLine, menu: true)
                    }
                    .buttonStyle(.plain)
                    rowMenu(card)
                }
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
    @StateObject fileprivate var model = LibraryModel()
    @State fileprivate var search = ""
    @State fileprivate var showFilters = false
    @State fileprivate var views: [SavedView] = []
    @State fileprivate var viewName = "Exploration"

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        libraryHeader(api)
                        HStack(spacing: 10) {
                            HideToggle(showAll: $model.filters.showAll)
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        SearchField(placeholder: "Rechercher une fiche", text: $search) {
                            Task { await model.reload(api: api, search: search) }
                        }
                        filtersButton
                        activePills
                        HStack {
                            Text("Bibliothèque").font(.raton(22, .bold)).foregroundStyle(Theme.text)
                            Spacer()
                            if model.loaded {
                                Text("\(model.total) fiche\(model.total > 1 ? "s" : "")")
                                    .font(.raton(15)).foregroundStyle(Theme.textMuted)
                            }
                        }
                        .padding(.horizontal, 16).padding(.top, 6).padding(.bottom, 8)
                        VideoList(model: model, api: api, search: search)
                    }
                }
                .refreshable { await model.reload(api: api, search: search) }
                .task {
                    views = (try? await api.get("/api/library/views")) ?? []
                    await model.reload(api: api, search: search)
                }
                .onChange(of: model.filters) { _ in Task { await model.reload(api: api, search: search) } }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
                .sheet(isPresented: $showFilters) {
                    // Changing `filters` reloads the list (see `onChange` above).
                    LibraryFiltersSheet(api: api, filters: model.filters) { chosen in
                        model.filters = chosen
                    }
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }
}

extension LibraryView {
    /// The ☰ button lists the saved views; the title is the one in use ("Exploration" when none).
    fileprivate func libraryHeader(_ api: RatonAPI) -> some View {
        HStack(spacing: 14) {
            Menu {
                Button { viewName = "Exploration"; model.filters = LibraryFilters() } label: {
                    Label("Exploration", systemImage: viewName == "Exploration" ? "checkmark" : "magnifyingglass")
                }
                ForEach(views, id: \.name) { view in
                    Button {
                        viewName = view.name
                        var next = LibraryFilters()
                        next.apply(view)
                        model.filters = next
                    } label: {
                        Label(view.name, systemImage: viewName == view.name ? "checkmark" : "bookmark")
                    }
                }
                NavigationLink { NouveautesView(back: true) } label: { Label("Nouveautés", systemImage: "sparkles") }
                NavigationLink { HistoriqueView() } label: { Label("Historique", systemImage: "clock.arrow.circlepath") }
            } label: { Image(systemName: "line.3.horizontal") }
            .buttonStyle(CircleButtonStyle())
            .accessibilityLabel("Vues")
            Text(viewName).font(.raton(26, .bold)).foregroundStyle(Theme.text).lineLimit(1)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 12)
    }

    /// "Filtres" with the number of active filters, as the web's pill.
    fileprivate var filtersButton: some View {
        let count = model.filters.activePills.count
        return Button { showFilters = true } label: {
            HStack(spacing: 8) {
                Image(systemName: "slider.horizontal.3")
                Text("Filtres").font(.raton(17, .bold))
                if count > 0 {
                    Text("\(count)").font(.raton(13, .bold)).foregroundStyle(.white)
                        .frame(minWidth: 24, minHeight: 24)
                        .background(Circle().fill(Theme.primary))
                }
            }
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 20).frame(height: 48)
            .surface(in: Capsule(), interactive: true)
        }
        .padding(.horizontal, 16).padding(.bottom, 14)
    }

    /// The removable pills of the active filters, with "Tout effacer".
    @ViewBuilder
    fileprivate var activePills: some View {
        let pills = model.filters.activePills
        if !pills.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(pills.indices, id: \.self) { index in
                        let pill = pills[index]
                        Button { pill.remove(&model.filters) } label: {
                            HStack(spacing: 6) {
                                Text((pill.excluded ? "≠ " : "") + pill.label).font(.raton(14, .semibold))
                                Image(systemName: "xmark").font(.system(size: 10, weight: .bold))
                            }
                            .foregroundStyle(Theme.textSoft)
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .surface(in: Capsule(), interactive: true)
                        }
                    }
                    Button("Tout effacer") { model.filters = LibraryFilters() }
                        .font(.raton(14, .bold)).foregroundStyle(Theme.primary)
                }
                .padding(.horizontal, 16).padding(.vertical, 14)
            }
            .padding(.vertical, -14)
            .padding(.bottom, 6)
        }
    }
}
