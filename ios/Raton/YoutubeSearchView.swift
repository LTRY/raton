import SwiftUI

/// The Recherche: YouTube videos and channels matching a query (`GET /api/youtube/videos|channels`),
/// to import a video as a fiche (`POST /api/videos/import`) or add a channel (`POST /api/channels`).
struct YoutubeSearchView: View {
    @EnvironmentObject private var state: AppState
    @State private var scope = 0
    @State private var query = ""
    @State private var videos: [YoutubeVideo] = []
    @State private var channels: [YoutubeChannel] = []
    @State private var searching = false
    @State private var searched = false
    @State private var errorMessage: String?
    @State private var notice: String?

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Recherche", back: true)
                        SearchField(placeholder: "Rechercher sur YouTube", text: $query) {
                            Task { await search(api) }
                        }
                        Picker("", selection: $scope) {
                            Text("Vidéos").tag(0)
                            Text("Chaînes").tag(1)
                        }
                        .pickerStyle(.segmented)
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        .onChange(of: scope) { _ in Task { await search(api) } }
                        ErrorMessage(text: errorMessage)
                        if let notice {
                            Text(notice).font(.raton(15, .medium)).foregroundStyle(Theme.textSoft).padding(16)
                        }
                        if searching { ProgressView().frame(maxWidth: .infinity).padding(.top, 30) }
                        if scope == 0 {
                            ForEach(videos) { video in videoRow(video, api) }
                        } else {
                            ForEach(channels) { channel in channelRow(channel, api) }
                        }
                        if searched && !searching && (scope == 0 ? videos.isEmpty : channels.isEmpty) {
                            EmptyMessage(text: "Aucun résultat.")
                        }
                    }
                }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func videoRow(_ video: YoutubeVideo, _ api: RatonAPI) -> some View {
        ListRow {
            HStack(alignment: .top, spacing: 12) {
                AsyncImage(url: URL(string: video.thumbnailUrl)) { image in
                    image.resizable().scaledToFill()
                } placeholder: { Theme.surfaceMuted }
                .frame(width: 120, height: 68).clipped().clipShape(RoundedRectangle(cornerRadius: 6))
                VStack(alignment: .leading, spacing: 4) {
                    Text(video.title).font(.raton(15, .bold)).foregroundStyle(Theme.text).lineLimit(3)
                    if let channel = video.channelName {
                        Text(channel).font(.raton(13, .semibold)).foregroundStyle(Theme.textMuted).lineLimit(1)
                    }
                    if let existing = video.existing {
                        NavigationLink(value: existing.id) { Text("Voir la fiche").font(.raton(14, .semibold)) }
                    } else {
                        HStack(spacing: 8) {
                            Button("Importer la vidéo") { Task { await importVideo(api, video, ["video"]) } }
                            Button("Audio") { Task { await importVideo(api, video, ["audio"]) } }
                        }
                        .buttonStyle(.bordered).font(.raton(13, .semibold)).tint(Theme.primary)
                    }
                }
            }
        }
    }

    private func channelRow(_ channel: YoutubeChannel, _ api: RatonAPI) -> some View {
        ListRow {
            HStack(spacing: 12) {
                AsyncImage(url: channel.thumbnailUrl.flatMap { URL(string: $0) }) { image in
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
                        .buttonStyle(.bordered).font(.raton(13, .semibold)).tint(Theme.primary)
                }
            }
        }
    }

    private func search(_ api: RatonAPI) async {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        searching = true
        errorMessage = nil
        notice = nil
        defer { searching = false; searched = true }
        do {
            if scope == 0 {
                videos = try await api.get("/api/youtube/videos", query: ["q": text])
            } else {
                channels = try await api.get("/api/youtube/channels", query: ["q": text])
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func importVideo(_ api: RatonAPI, _ video: YoutubeVideo, _ types: [String]) async {
        do {
            let _: QueuedJob = try await api.post(
                "/api/videos/import",
                body: ["url": video.url, "media_types": types, "download_transcript": true,
                       "video_quality": "1080", "categories": [String]()])
            notice = "Import lancé : la fiche apparaîtra dans la Bibliothèque."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func addChannel(_ api: RatonAPI, _ channel: YoutubeChannel) async {
        do {
            let _: ChannelItem = try await api.post("/api/channels", body: ["url": channel.url, "rating": 1])
            notice = "Chaîne ajoutée : \(channel.name)."
            await search(api)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
