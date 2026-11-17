import SwiftUI

/// The Recherche: YouTube videos and channels matching a query (`GET /api/youtube/videos|channels`),
/// to import a video as a fiche (`POST /api/videos/import`) or add a channel (`POST /api/channels`).
/// A YouTube video link pasted in the field is offered for import without any search.
struct YoutubeSearchView: View {
    /// Where a video's import stands on its row, by video link.
    private enum ImportState { case running, queued }

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
    @State private var imports: [String: ImportState] = [:]
    // Bumped by every search: an answer that comes back after a newer search started is dropped.
    @State private var generation = 0

    private var pastedLink: URL? { Format.youtubeVideoLink(query) }
    private var currentText: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Recherche", back: true)
                        SearchField(placeholder: "Rechercher ou coller un lien YouTube", text: $query, live: false) {
                            Task { await search(api) }
                        }
                        if pastedLink == nil {
                            Picker("", selection: $scope) {
                                Text("Vidéos").tag(0)
                                Text("Chaînes").tag(1)
                            }
                            .pickerStyle(.segmented)
                            .padding(.horizontal, 16).padding(.bottom, 12)
                            .onChange(of: scope) {
                                if currentText != (scope == 0 ? videosFor : channelsFor) { Task { await search(api) } }
                            }
                        }
                        ErrorMessage(text: errorMessage)
                        if let link = pastedLink {
                            pastedRow(link, api)
                        } else {
                            results(api)
                        }
                    }
                }
                .scrollDismissesKeyboard(.interactively)
                .barClearance()
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    @ViewBuilder
    private func results(_ api: RatonAPI) -> some View {
        if searching { ProgressView().frame(maxWidth: .infinity).padding(.top, 30) }
        if scope == 0 {
            ForEach(videos) { video in videoRow(video, api) }
        } else {
            ForEach(channels) { channel in channelRow(channel, api) }
        }
        let answered = scope == 0 ? videosFor : channelsFor
        if !searching, answered != nil, answered == currentText, scope == 0 ? videos.isEmpty : channels.isEmpty {
            EmptyMessage(text: "Aucun résultat.")
        }
    }

    // MARK: Rows

    private func pastedRow(_ link: URL, _ api: RatonAPI) -> some View {
        ListRow {
            VStack(alignment: .leading, spacing: 10) {
                Text("Lien YouTube détecté").font(.raton(15, .bold)).foregroundStyle(Theme.text)
                Text(link.absoluteString).font(.raton(13)).foregroundStyle(Theme.textMuted)
                    .lineLimit(2).truncationMode(.middle)
                importControl(link.absoluteString, title: "cette vidéo", api)
            }
        }
    }

    private func videoRow(_ video: YoutubeVideo, _ api: RatonAPI) -> some View {
        ListRow {
            VStack(alignment: .leading, spacing: 10) {
                opener(video) {
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
                        }
                    }
                }
                if let existing = video.existing {
                    NavigationLink(value: existing.id) {
                        Label("Voir la fiche", systemImage: "checkmark.circle.fill")
                            .font(.raton(14, .semibold))
                    }
                } else {
                    importControl(video.url, title: nil, api)
                }
            }
        }
    }

    /// The row's head opens the fiche when the library has the video, else the video on YouTube.
    @ViewBuilder
    private func opener<Content: View>(_ video: YoutubeVideo, @ViewBuilder _ content: () -> Content) -> some View {
        if let existing = video.existing {
            NavigationLink(value: existing.id) { content() }
                .buttonStyle(.plain)
                .accessibilityHint("Ouvre la fiche")
        } else if let url = URL(string: video.url) {
            Link(destination: url) { content() }
                .buttonStyle(.plain)
                .accessibilityHint("Ouvre la vidéo sur YouTube")
        } else {
            content()
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

    /// "Importer" with the choice of a video or an audio fiche; once chosen it shows where the import stands.
    @ViewBuilder
    private func importControl(_ url: String, title: String?, _ api: RatonAPI) -> some View {
        switch imports[url] {
        case .running:
            HStack(spacing: 8) {
                ProgressView()
                Text("Import en cours…").font(.raton(14, .semibold)).foregroundStyle(Theme.textMuted)
            }
            .frame(minHeight: 44)
        case .queued:
            Label("Import lancé", systemImage: "checkmark.circle.fill")
                .font(.raton(14, .semibold)).foregroundStyle(Theme.primary)
                .frame(minHeight: 44)
        case nil:
            Menu {
                Button("Vidéo", systemImage: "play.rectangle") { Task { await importVideo(api, url, ["video"]) } }
                Button("Audio", systemImage: "waveform") { Task { await importVideo(api, url, ["audio"]) } }
            } label: {
                Label(title.map { "Importer \($0)" } ?? "Importer", systemImage: "arrow.down.circle")
                    .font(.raton(14, .semibold))
                    .padding(.horizontal, 14).frame(minHeight: 44)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Theme.tint))
                    .foregroundStyle(Theme.primary)
            }
        }
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
        // A pasted link is offered for import, not searched.
        guard Format.youtubeVideoLink(text) == nil else { searching = false; return }
        searching = true
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

    private func importVideo(_ api: RatonAPI, _ url: String, _ types: [String]) async {
        imports[url] = .running
        do {
            let _: QueuedJob = try await api.post(
                "/api/videos/import",
                body: ["url": url, "media_types": types, "download_transcript": true,
                       "video_quality": "1080", "categories": [String]()])
            imports[url] = .queued
            Toasts.shared.show("Import lancé : la fiche apparaîtra dans la Bibliothèque.")
        } catch {
            imports[url] = nil
            Toasts.shared.show(error)
        }
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
