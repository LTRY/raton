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
    // The Nouveautés: the fiches of the followed channels, newest publication first.
    let followed: Bool

    init(channelID: Int? = nil, followed: Bool = false) {
        self.channelID = channelID
        self.followed = followed
        if followed { filters.sort = "published" }
    }

    @Published var filters = LibraryFilters()

    private func query(page: Int, search: String) -> [URLQueryItem] {
        var items = [URLQueryItem(name: "page", value: String(page))]
        if !search.isEmpty { items.append(URLQueryItem(name: "q", value: search)) }
        if let channelID { items.append(URLQueryItem(name: "channel_id", value: String(channelID))) }
        if followed { items.append(URLQueryItem(name: "followed", value: "true")) }
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
    // The shorts of a channel page are tiles, not rows.
    var shorts = false

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
            ErrorMessage(text: model.errorMessage) { Task { await model.reload(api: api, search: search) } }
            if !model.loaded && model.errorMessage == nil { LoadingRow() }
            if shorts {
                ShortsMosaic(cards: model.items, api: api) { card in
                    await model.loadMore(api: api, search: search, after: card)
                }
            }
            ForEach(shorts ? [] : model.items) { card in
                ZStack(alignment: .topTrailing) {
                    NavigationLink(value: card.id) {
                        VideoRow(card: card, api: api, dateLine: dateLine, menu: true)
                    }
                    .buttonStyle(.plain)
                    rowMenu(card)
                }
                .swipeActions(edge: .trailing) {
                    Button { Task { await setState(card, card.shownState == "watched" ? "unwatched" : "watched") } } label: {
                        Label(card.shownState == "watched" ? "Non vu" : "Vu",
                              systemImage: card.shownState == "watched" ? "eye.slash" : "checkmark.circle")
                    }
                    .tint(Theme.primary)
                    Button { Task { await setState(card, card.shownState == "hidden" ? "clear" : "hidden") } } label: {
                        Label(card.shownState == "hidden" ? "Démasquer" : "Indésirée", systemImage: "eye.slash")
                    }
                    .tint(Theme.textSoft)
                }
                .task { await model.loadMore(api: api, search: search, after: card) }
            }
            if model.loaded && model.items.isEmpty && model.errorMessage == nil {
                EmptyMessage(text: "Aucune fiche.")
            }
        }
        .rowSwipeContainer()
    }
}

extension View {
    /// Lets the rows of a scrolling stack be swiped (iOS 27); before that the row's "⋮" menu is the only way.
    @ViewBuilder fileprivate func rowSwipeContainer() -> some View {
        if #available(iOS 27, *) { swipeActionsContainer() } else { self }
    }
}

struct LibraryView: View {
    @EnvironmentObject private var state: AppState
    @StateObject fileprivate var model: LibraryModel
    // True for the Nouveautés: the same list on the followed channels, with a back button.
    fileprivate let followed: Bool
    @State fileprivate var search = ""
    @State fileprivate var showFilters = false
    // A NavigationLink inside a Menu does nothing when tapped, so the ☰ entries set these instead.
    @State fileprivate var showNouveautes = false
    @State fileprivate var showHistorique = false

    init(followed: Bool = false) {
        self.followed = followed
        _model = StateObject(wrappedValue: LibraryModel(followed: followed))
    }

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        libraryHeader(api)
                        SearchField(placeholder: "Rechercher", text: $search) {
                            Task { await model.reload(api: api, search: search) }
                        }
                        // "Filtres" and the see-all / hide-seen switch share one line.
                        HStack(spacing: 10) {
                            filtersButton
                            Spacer(minLength: 0)
                            HideToggle(showAll: $model.filters.showAll)
                        }
                        .padding(.horizontal, 16).padding(.bottom, 14)
                        Color.clear.frame(height: 4)
                        VideoList(model: model, api: api, search: search)
                    }
                }
                .refreshable { await model.reload(api: api, search: search) }
                .task {
                    await model.reload(api: api, search: search)
                }
                .onChange(of: model.filters) { _ in Task { await model.reload(api: api, search: search) } }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
                .navigationDestination(isPresented: $showNouveautes) { NouveautesView(back: true) }
                .navigationDestination(isPresented: $showHistorique) { HistoriqueView() }
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
    /// The ☰ button goes to Exploration, the Nouveautés or the Historique; the saved views of the web are not listed.
    fileprivate func libraryHeader(_ api: RatonAPI) -> some View {
        HStack(spacing: 14) {
            if followed {
                NouveautesBackButton()
            } else {
                Menu {
                    Button { model.filters = LibraryFilters() } label: {
                        Label("Exploration", systemImage: "checkmark")
                    }
                    Button { showNouveautes = true } label: { Label("Nouveautés", systemImage: "sparkles") }
                    Button { showHistorique = true } label: { Label("Historique", systemImage: "clock.arrow.circlepath") }
                } label: { Image(systemName: "line.3.horizontal") }
                .buttonStyle(CircleButtonStyle())
                .accessibilityLabel("Vues")
            }
            Text(followed ? "Nouveautés" : "Exploration").font(.raton(26, .bold)).foregroundStyle(Theme.text).lineLimit(1)
            // The number of fiches, in the little pill of the other list pages.
            if model.loaded {
                Text("\(model.total)").font(.raton(13, .semibold)).foregroundStyle(Theme.textMuted)
                    .padding(.horizontal, 10).padding(.vertical, 3)
                    .background(Capsule().fill(Theme.surfaceMuted))
                    .accessibilityLabel("\(model.total) fiche\(model.total > 1 ? "s" : "")")
            }
            Spacer(minLength: 0)
            if followed {
                NavigationLink { HistoriqueView() } label: { Image(systemName: "clock.arrow.circlepath") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Historique")
            }
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
    }
}

/// The round back arrow of a pushed page.
struct NouveautesBackButton: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Button { dismiss() } label: { Image(systemName: "arrow.left") }
            .buttonStyle(CircleButtonStyle())
            .accessibilityLabel("Retour")
    }
}
