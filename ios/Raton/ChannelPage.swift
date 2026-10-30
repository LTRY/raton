import SwiftUI

/// A channel page, laid out like the web's (`front/templates/channel_videos.html`): the banner with the
/// avatar over it, the name, the cloches, the stars and the "⋯" menu, then the section switch, the search,
/// the sort and the filters, the fiches and "Explorer la suite".
struct ChannelView: View {
    let channel: ChannelItem
    @EnvironmentObject private var state: AppState
    @StateObject private var model: LibraryModel
    @State private var detail: ChannelDetail?
    @State private var videosBell: Bool
    @State private var shortsBell: Bool
    @State private var rating: Int
    @State private var categories: [String]
    @State private var search = ""
    @State private var busy = false
    @State private var exploring = false
    @State private var errorMessage: String?
    @State private var notice: String?
    @State private var showCategories = false
    @State private var showFilters = false
    @State private var confirmDelete = false
    @State private var descriptionOpen = false
    @State private var keywordsOpen = false
    @Environment(\.dismiss) private var dismiss

    private static let sorts = [
        ("imported", "Import récent"), ("published", "Publication récente"),
        ("views", "Les plus vues"), ("rated", "Les mieux notées"),
    ]

    init(channel: ChannelItem) {
        self.channel = channel
        let model = LibraryModel(channelID: channel.id)
        model.filters = Self.defaultFilters
        _model = StateObject(wrappedValue: model)
        _videosBell = State(initialValue: channel.autoMetadataEnabled)
        _shortsBell = State(initialValue: channel.autoShortsEnabled)
        _rating = State(initialValue: channel.rating)
        _categories = State(initialValue: channel.categories)
    }

    /// A channel page opens on the latest publications, like the web's.
    private static var defaultFilters: LibraryFilters {
        var filters = LibraryFilters()
        filters.sort = "published"
        return filters
    }

    private var inShorts: Bool { model.filters.section == "shorts" }

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        hero(api)
                        actions(api)
                        about
                        Theme.border.frame(height: 1).padding(.horizontal, 16).padding(.top, 4)
                        toolbar(api)
                        if let message = errorMessage { ErrorMessage(text: message) }
                        if let notice {
                            Text(notice).font(.raton(14, .medium)).foregroundStyle(Theme.textSoft)
                                .padding(.horizontal, 16).padding(.bottom, 8)
                        }
                        if model.loaded {
                            Text("\(model.total) fiche\(model.total > 1 ? "s" : "")")
                                .font(.raton(15, .bold)).foregroundStyle(Theme.textSoft)
                                .padding(.horizontal, 16).padding(.bottom, 8)
                        }
                        VideoList(model: model, api: api, search: search, dateLine: true, shorts: inShorts)
                        if model.loaded && model.items.isEmpty { emptyState(api) }
                        explore(api)
                    }
                }
                .refreshable { await reload(api) }
                .task {
                    await loadDetail(api)
                    await reload(api)
                }
                .onChange(of: model.filters) { _ in Task { await reload(api) } }
                .sheet(isPresented: $showCategories) {
                    CategoryPickerSheet(api: api, selected: categories) { chosen in
                        do {
                            let _: ChannelState = try await api.put(
                                "/api/channels/\(channel.id)/categories", body: ["categories": chosen])
                            categories = chosen
                        } catch { errorMessage = error.localizedDescription }
                    }
                }
                .sheet(isPresented: $showFilters) {
                    LibraryFiltersSheet(api: api, filters: model.filters) { model.filters = $0 }
                }
                .confirmationDialog("Supprimer cette chaîne et ses fiches ? C'est définitif.",
                                    isPresented: $confirmDelete, titleVisibility: .visible) {
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

    // MARK: Hero

    private func hero(_ api: RatonAPI) -> some View {
        VStack(spacing: 0) {
            banner(api)
                .frame(height: 124)
                .frame(maxWidth: .infinity)
                .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
                .overlay(alignment: .topLeading) {
                    Button { dismiss() } label: { Image(systemName: "arrow.left") }
                        .buttonStyle(CircleButtonStyle())
                        .accessibilityLabel("Retour")
                        .padding(12)
                }
                .padding(.horizontal, 14).padding(.top, 8)
            HStack(alignment: .top, spacing: 14) {
                avatar(api)
                    .padding(.top, -40)
                nameLink.padding(.top, 8)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 24)
        }
    }

    @ViewBuilder
    private func banner(_ api: RatonAPI) -> some View {
        if let path = detail?.bannerUrl {
            AsyncImage(url: api.url(path)) { image in
                image.resizable().scaledToFill()
            } placeholder: { bannerFallback }
        } else {
            bannerFallback
        }
    }

    /// The web's fallback when a channel has no banner: a terracotta gradient.
    private var bannerFallback: some View {
        LinearGradient(colors: [Color(hex: 0xE8A07A), Color(hex: 0xC2410C), Color(hex: 0x8A2C10)],
                       startPoint: .leading, endPoint: .trailing)
    }

    private func avatar(_ api: RatonAPI) -> some View {
        let name = detail?.name ?? channel.name
        return ZStack {
            Circle().fill(Theme.text)
            if let path = detail?.avatarUrl ?? channel.avatarUrl {
                AsyncImage(url: api.url(path)) { image in
                    image.resizable().scaledToFill()
                } placeholder: { Color.clear }
                .clipShape(Circle())
            } else {
                Text(String(name.prefix(1)).uppercased())
                    .font(.raton(34, .bold)).foregroundStyle(.white)
            }
        }
        .frame(width: 76, height: 76)
        .overlay(Circle().stroke(Color.white, lineWidth: 4))
        .shadow(color: Theme.shadow.opacity(0.18), radius: 8, y: 4)
    }

    /// The name opens the channel on YouTube, with the little arrow of the web.
    @ViewBuilder
    private var nameLink: some View {
        let name = detail?.name ?? channel.name
        let label = HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(name).font(.raton(28, .bold)).foregroundStyle(Theme.text)
                .lineLimit(2).multilineTextAlignment(.leading)
            Image(systemName: "arrow.up.right").font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.textMuted)
        }
        if let url = detail.flatMap({ URL(string: $0.url) }) {
            Link(destination: url) { label }.accessibilityHint("Ouvre la chaîne sur YouTube")
        } else {
            label
        }
    }

    // MARK: Cloches, stars, menu

    private func actions(_ api: RatonAPI) -> some View {
        HStack(spacing: 10) {
            bell(api, section: "videos", isOn: videosBell)
            bell(api, section: "shorts", isOn: shortsBell)
            ratingControl(api)
            moreMenu(api)
        }
        .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 14)
    }

    /// A cloche is the user's follow switch; its badge tells the videos' cloche (▶) from the shorts' one.
    private func bell(_ api: RatonAPI, section: String, isOn: Bool) -> some View {
        Button { toggle(api, section) } label: {
            Image(systemName: isOn ? "bell.fill" : "bell.slash")
                .font(.system(size: 20))
                .foregroundStyle(isOn ? Theme.primary : Theme.textMuted)
                .frame(width: 48, height: 48)
                .surface(in: RoundedRectangle(cornerRadius: 16, style: .continuous),
                       tint: isOn ? Theme.primary : nil, interactive: true)
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(isOn ? Theme.primary : Color.clear, lineWidth: 1.5))
                .overlay(alignment: .bottomTrailing) {
                    Image(systemName: section == "videos" ? "play.fill" : "rectangle.portrait")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(isOn ? Theme.primary : Theme.textSoft)
                        .frame(width: 22, height: 22)
                        .background(Circle().fill(Color.white))
                        .overlay(Circle().stroke(isOn ? Theme.primary : Theme.textSoft, lineWidth: 1.5))
                        .offset(x: 6, y: 6)
                }
        }
        .padding(.trailing, 4)
        .disabled(busy)
        .accessibilityLabel("Suivi quotidien des \(section == "videos" ? "vidéos" : "shorts")")
        .accessibilityValue(isOn ? "activé" : "désactivé")
    }

    private func ratingControl(_ api: RatonAPI) -> some View {
        HStack(spacing: 4) {
            ForEach(1...5, id: \.self) { star in
                Button { Task { await setRating(api, star) } } label: {
                    Image(systemName: "star.fill").font(.system(size: 22))
                        .foregroundStyle(star <= rating ? Theme.amber : Theme.textFaint.opacity(0.55))
                }
                .accessibilityLabel("\(star) étoile\(star > 1 ? "s" : "")")
            }
        }
        .frame(maxWidth: .infinity).frame(height: 48)
        .surface(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func moreMenu(_ api: RatonAPI) -> some View {
        Menu {
            Section("Statistiques") {
                Text("Vidéos téléchargées : \(model.counts["downloaded_regular_video_count"] ?? 0)")
                Text("Shorts téléchargés : \(model.counts["downloaded_short_count"] ?? 0)")
                Text("Fiches : \(model.counts["local_video_count"] ?? 0)")
            }
            Button { showCategories = true } label: {
                Label("Labels catégories (\(categories.count))", systemImage: "tag")
            }
            Button { Task { await refreshProfile(api) } } label: {
                Label("Rafraîchir le profil", systemImage: "arrow.clockwise")
            }
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Supprimer la chaîne", systemImage: "trash")
            }
        } label: {
            Image(systemName: "ellipsis").font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Theme.text)
                .frame(width: 48, height: 48)
                .surface(in: RoundedRectangle(cornerRadius: 16, style: .continuous), interactive: true)
        }
        .accessibilityLabel("Plus d'actions")
    }

    // MARK: Description and keywords

    @ViewBuilder
    private var about: some View {
        if let text = detail?.description, !text.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(text).font(.raton(15)).foregroundStyle(Theme.textSoft)
                    .lineLimit(descriptionOpen ? nil : 3)
                if text.count > 200 {
                    Button(descriptionOpen ? "Voir moins" : "Voir plus") { descriptionOpen.toggle() }
                        .font(.raton(14, .semibold)).foregroundStyle(Theme.primary)
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 10)
        }
        if let keywords = detail?.keywords, !keywords.isEmpty {
            let shown = keywordsOpen ? keywords : Array(keywords.prefix(5))
            FlowLayout(spacing: 6) {
                ForEach(shown, id: \.self) { keyword in
                    Text(keyword).font(.raton(13, .semibold)).foregroundStyle(Theme.textSoft)
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .surface(in: Capsule())
                }
                if keywords.count > 5 {
                    Button(keywordsOpen ? "Moins" : "+\(keywords.count - 5)") { keywordsOpen.toggle() }
                        .font(.raton(13, .semibold)).foregroundStyle(Theme.primary)
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .surface(in: Capsule(), tint: Theme.primary, interactive: true)
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 10)
        }
    }

    // MARK: Toolbar

    private func toolbar(_ api: RatonAPI) -> some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                segmented
                Button { Task { await explore(api, page: 1) } } label: {
                    Group {
                        if exploring { ProgressView().tint(.white) } else {
                            Image(systemName: "arrow.clockwise").font(.system(size: 18, weight: .bold))
                        }
                    }
                    .foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .background(Circle().fill(Theme.primary))
                    .shadow(color: Theme.shadow.opacity(0.25), radius: 8, y: 4)
                }
                .disabled(exploring)
                .accessibilityLabel(inShorts ? "Chercher les nouveaux shorts" : "Chercher les nouvelles vidéos")
            }
            HStack(spacing: 10) {
                searchField(api)
                hideToggle
            }
            HStack(spacing: 10) {
                Menu {
                    ForEach(Self.sorts, id: \.0) { sort in
                        Button {
                            model.filters.sort = sort.0
                        } label: {
                            if model.filters.sort == sort.0 { Label(sort.1, systemImage: "checkmark") } else { Text(sort.1) }
                        }
                    }
                } label: {
                    pill(Self.sorts.first { $0.0 == model.filters.sort }?.1 ?? "Trier", trailing: "▾")
                }
                Button { showFilters = true } label: {
                    pill("Filtres", trailing: nil, active: model.filters != Self.defaultFilters)
                }
            }
        }
        .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 12)
    }

    private func pill(_ title: String, trailing: String?, active: Bool = false) -> some View {
        HStack(spacing: 6) {
            Text(title).font(.raton(16, .semibold)).lineLimit(1)
            if let trailing { Text(trailing).font(.raton(12)) }
        }
        .foregroundStyle(active ? Theme.primary : Theme.text)
        .frame(maxWidth: .infinity).frame(height: 46)
        .surface(in: Capsule(), tint: active ? Theme.primary : nil, interactive: true)
    }

    private var segmented: some View {
        HStack(spacing: 4) {
            ForEach([("videos", "Vidéos"), ("shorts", "Shorts")], id: \.0) { section in
                let active = model.filters.section == section.0
                Button { model.filters.section = section.0 } label: {
                    Text(section.1).font(.raton(16, .bold))
                        .foregroundStyle(active ? Theme.text : Theme.textMuted)
                        .frame(maxWidth: .infinity).frame(height: 38)
                        .background(Capsule().fill(active ? Color.white : Color.clear))
                }
            }
        }
        .padding(4)
        .sandTrack()
    }

    private func searchField(_ api: RatonAPI) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(Theme.textMuted)
            TextField("Rechercher dans la chaîne", text: $search)
                .font(.raton(16, .medium)).submitLabel(.search)
                .autocorrectionDisabled()
                .onSubmit { Task { await reload(api) } }
            if !search.isEmpty {
                Button { search = ""; Task { await reload(api) } } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.textFaint)
                }
            }
        }
        .padding(.horizontal, 14).frame(height: 46)
        .surface(in: Capsule())
    }

    private var hideToggle: some View { HideToggle(showAll: $model.filters.showAll) }

    // MARK: Empty state and exploration

    @ViewBuilder
    private func emptyState(_ api: RatonAPI) -> some View {
        if !search.isEmpty {
            EmptyMessage(text: "Aucun résultat pour « \(search) ».")
        } else {
            VStack(spacing: 12) {
                AsyncImage(url: api.url("/static/img/raccoon-empty.png")) { image in
                    image.resizable().scaledToFit()
                } placeholder: { Color.clear }
                .frame(width: 130, height: 175)
                Text("Rien ici pour l'instant.").font(.raton(16)).foregroundStyle(Theme.textMuted)
            }
            .frame(maxWidth: .infinity).padding(.top, 30)
        }
    }

    private func explore(_ api: RatonAPI) -> some View {
        let empty = model.loaded && model.items.isEmpty && search.isEmpty
        return VStack(spacing: 10) {
            Button { Task { await explore(api, page: model.exploreNextPage) } } label: {
                HStack(spacing: 8) {
                    Text(exploring ? "Exploration…" : (empty ? "Commencer l'exploration" : "Explorer la suite"))
                    Image(systemName: "arrow.down")
                }
                .font(.raton(17, .bold)).foregroundStyle(Theme.primary)
                .frame(maxWidth: .infinity).frame(height: 54)
                .surface(in: Capsule(), tint: Theme.primary, interactive: true)
                .overlay(Capsule().stroke(Theme.primary, lineWidth: 1.5))
            }
            .disabled(exploring)
            Text("Récupère les \(model.explorePageSize) \(empty ? "premières" : "suivantes") fiches depuis YouTube")
                .font(.raton(15)).foregroundStyle(Theme.textMuted).multilineTextAlignment(.center)
        }
        .padding(.horizontal, 16).padding(.top, 24).padding(.bottom, 24)
    }

    // MARK: Calls

    private func reload(_ api: RatonAPI) async {
        await model.reload(api: api, search: search)
    }

    private func loadDetail(_ api: RatonAPI) async {
        if let loaded: ChannelDetail = try? await api.get("/api/channels/\(channel.id)") {
            detail = loaded
        }
    }

    private func setRating(_ api: RatonAPI, _ value: Int) async {
        let next = rating == value ? 0 : value
        do {
            let _: ChannelState = try await api.put("/api/channels/\(channel.id)/rating", body: ["rating": next])
            rating = next
        } catch { errorMessage = error.localizedDescription }
    }

    private func refreshProfile(_ api: RatonAPI) async {
        let _: QueuedJob? = try? await api.post("/api/channels/\(channel.id)/refresh-profile")
        notice = "Rafraîchissement du profil lancé."
        try? await Task.sleep(nanoseconds: 6_000_000_000)
        await loadDetail(api)
        notice = nil
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

    /// One page of the channel's YouTube listing, imported by the back; the fiches are read again when it is done.
    private func explore(_ api: RatonAPI, page: Int) async {
        exploring = true
        errorMessage = nil
        defer { exploring = false }
        do {
            let job: QueuedJob = try await api.post(
                "/api/channels/\(channel.id)/import-metadata",
                body: ["page": page, "section": model.filters.section])
            for _ in 0..<80 {
                try await Task.sleep(nanoseconds: 3_000_000_000)
                let progress: JobProgress = try await api.get("/api/jobs/\(job.jobId)")
                if progress.done {
                    if progress.status == "failed" { errorMessage = progress.message }
                    break
                }
            }
            await reload(api)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
