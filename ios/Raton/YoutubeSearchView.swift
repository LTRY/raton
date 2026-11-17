import SwiftUI

/// The Recherche: YouTube videos and channels matching a query (`GET /api/youtube/videos|channels`),
/// to open a video or add a channel (`POST /api/channels`).
/// A video opens its fiche when the library has it, else the same page without the index: touching a
/// control there adds it. The last searches are listed while the field is being edited.
struct YoutubeSearchView: View {
    @EnvironmentObject private var state: AppState
    @State private var scope = 0
    @State private var query = ""
    @State private var videos: [YoutubeVideo] = []
    @State private var channels: [YoutubeChannel] = []
    // The text each scope's results answer, so a switch of scope only searches when they are out of date.
    @State private var videosFor: String?
    @State private var channelsFor: String?
    @State private var searching = false
    @State private var errorMessage: String?
    // Bumped by every search: an answer that comes back after a newer search started is dropped.
    @State private var generation = 0
    @FocusState private var fieldFocused: Bool
    @State private var history = SearchHistory.load()

    private var currentText: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Recherche", back: true)
                        SearchField(placeholder: "Rechercher sur YouTube", text: $query, live: false, focus: $fieldFocused) {
                            Task { await search(api) }
                        }
                        if fieldFocused {
                            historyList(api)
                        } else {
                        Picker("", selection: $scope) {
                            Text("Vidéos").tag(0)
                            Text("Chaînes").tag(1)
                        }
                        .pickerStyle(.segmented)
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        .onChange(of: scope) {
                            if currentText != (scope == 0 ? videosFor : channelsFor) { Task { await search(api) } }
                        }
                        ErrorMessage(text: errorMessage)
                        results(api)
                        }
                    }
                }
                .scrollDismissesKeyboard(.interactively)
                .barClearance()
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
                .navigationDestination(for: YoutubeVideo.self) { FicheView(candidate: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    @ViewBuilder
    private func results(_ api: RatonAPI) -> some View {
        if searching { ProgressView().frame(maxWidth: .infinity).padding(.top, 30) }
        if scope == 0 {
            ForEach(videos) { video in videoRow(video) }
        } else {
            ForEach(channels) { channel in channelRow(channel, api) }
        }
        let answered = scope == 0 ? videosFor : channelsFor
        if !searching, answered != nil, answered == currentText, scope == 0 ? videos.isEmpty : channels.isEmpty {
            EmptyMessage(text: "Aucun résultat.")
        }
    }

    // MARK: History

    /// The earlier searches (those that contain the typed text), shown while the field is edited.
    @ViewBuilder
    private func historyList(_ api: RatonAPI) -> some View {
        let typed = currentText.lowercased()
        let shown = history.filter { typed.isEmpty || $0.lowercased().contains(typed) }
        ForEach(shown, id: \.self) { item in
            ListRow {
                HStack(spacing: 12) {
                    Button {
                        query = item
                        fieldFocused = false
                        Task { await search(api) }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "clock.arrow.circlepath").foregroundStyle(Theme.textMuted)
                            Text(item).font(.raton(16, .semibold)).foregroundStyle(Theme.text).lineLimit(1)
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Button { history = SearchHistory.remove(item) } label: {
                        Image(systemName: "xmark").font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(Theme.textFaint).frame(width: 36, height: 36)
                    }
                    .accessibilityLabel("Retirer « \(item) » de l'historique")
                }
            }
        }
        if !history.isEmpty && typed.isEmpty {
            Button("Effacer l'historique") { history = SearchHistory.clear() }
                .font(.raton(14, .semibold)).foregroundStyle(Theme.primary).padding(16)
        }
    }

    // MARK: Rows

    private func videoRow(_ video: YoutubeVideo) -> some View {
        ListRow {
            if let existing = video.existing {
                NavigationLink(value: existing.id) { rowHead(video) }.buttonStyle(.plain)
            } else {
                NavigationLink(value: video) { rowHead(video) }.buttonStyle(.plain)
            }
        }
    }

    private func rowHead(_ video: YoutubeVideo) -> some View {
        HStack(alignment: .top, spacing: 12) {
            thumbnail(video)
            VStack(alignment: .leading, spacing: 4) {
                Text(video.title).font(.raton(15, .bold)).foregroundStyle(Theme.text)
                    .lineLimit(3).multilineTextAlignment(.leading)
                if let channel = video.channelName {
                    Text(channel).font(.raton(13, .semibold)).foregroundStyle(Theme.textMuted).lineLimit(1)
                }
                let facts = [Format.views(video.viewCount), Format.age(video.publishedAt)].compactMap { $0 }
                if !facts.isEmpty {
                    Text(facts.joined(separator: " · ")).font(.raton(13)).foregroundStyle(Theme.textMuted)
                        .lineLimit(1)
                }
                if video.existing != nil {
                    Label("Dans la bibliothèque", systemImage: "checkmark.circle.fill")
                        .font(.raton(13, .semibold)).foregroundStyle(Theme.primary)
                }
            }
        }
    }

    private func thumbnail(_ video: YoutubeVideo) -> some View {
        ZStack(alignment: .bottomTrailing) {
            CachedImage(url: URL(string: video.thumbnailUrl)) { image in
                image.resizable().scaledToFill()
            } placeholder: { Theme.surfaceMuted }
            .frame(width: 128, height: 72).clipped()
            if let seconds = video.durationSeconds {
                Text(Format.clock(Double(seconds)))
                    .font(.raton(12, .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(RoundedRectangle(cornerRadius: 4).fill(Color(hex: 0x2B3340)))
                    .padding(4)
            }
        }
        .overlay(alignment: .topLeading) {
            if video.isShort == true {
                Text("Short").font(.raton(11, .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Capsule().fill(Theme.primary))
                    .padding(4)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func channelRow(_ channel: YoutubeChannel, _ api: RatonAPI) -> some View {
        ListRow {
            HStack(spacing: 12) {
                CachedImage(url: channel.thumbnailUrl.flatMap { URL(string: $0) }) { image in
                    image.resizable().scaledToFill()
                } placeholder: { Theme.surfaceMuted }
                .frame(width: 52, height: 52).clipShape(Circle())
                VStack(alignment: .leading, spacing: 3) {
                    Text(channel.name).font(.raton(16, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                    if let handle = channel.handle {
                        Text(handle).font(.raton(13)).foregroundStyle(Theme.textMuted)
                    }
                }
                Spacer(minLength: 0)
                if channel.existing != nil {
                    Text("Déjà ajoutée").font(.raton(13)).foregroundStyle(Theme.textMuted)
                } else {
                    Button("Ajouter") { Task { await addChannel(api, channel) } }
                        .buttonStyle(.bordered).font(.raton(14, .semibold)).tint(Theme.primary)
                        .controlSize(.large)
                }
            }
        }
    }

    // MARK: Calls

    private func search(_ api: RatonAPI) async {
        let text = currentText
        generation += 1
        let mine = generation
        errorMessage = nil
        guard !text.isEmpty else {
            videos = []; channels = []; videosFor = nil; channelsFor = nil; searching = false
            return
        }
        searching = true
        history = SearchHistory.add(text)
        let inScope = scope
        do {
            if inScope == 0 {
                let found: [YoutubeVideo] = try await api.get("/api/youtube/videos", query: ["q": text])
                guard mine == generation else { return }
                videos = found
                videosFor = text
            } else {
                let found: [YoutubeChannel] = try await api.get("/api/youtube/channels", query: ["q": text])
                guard mine == generation else { return }
                channels = found
                channelsFor = text
            }
        } catch {
            guard mine == generation, !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
        if mine == generation { searching = false }
    }

    private func addChannel(_ api: RatonAPI, _ channel: YoutubeChannel) async {
        do {
            let _: ChannelItem = try await api.post("/api/channels", body: ["url": channel.url, "rating": 1])
            Toasts.shared.show("Chaîne ajoutée : \(channel.name).")
            await search(api)
        } catch {
            Toasts.shared.show(error)
        }
    }
}

/// The searches typed in the YouTube search, newest first, kept on the phone.
enum SearchHistory {
    private static let key = "youtubeSearchHistory"
    private static let limit = 12

    static func load() -> [String] { UserDefaults.standard.stringArray(forKey: key) ?? [] }

    static func add(_ text: String) -> [String] {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return load() }
        return save([value] + load().filter { $0.caseInsensitiveCompare(value) != .orderedSame })
    }

    static func remove(_ text: String) -> [String] { save(load().filter { $0 != text }) }

    static func clear() -> [String] { save([]) }

    private static func save(_ items: [String]) -> [String] {
        let kept = Array(items.prefix(limit))
        UserDefaults.standard.set(kept, forKey: key)
        return kept
    }
}
