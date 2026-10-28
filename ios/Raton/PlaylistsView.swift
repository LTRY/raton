import SwiftUI

struct PlaylistsView: View {
    @EnvironmentObject private var state: AppState
    @State private var playlists: [PlaylistSummary] = []
    @State private var loaded = false
    @State private var errorMessage: String?

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Playlists")
                        ErrorMessage(text: errorMessage)
                        ForEach(playlists) { playlist in
                            NavigationLink(value: playlist) {
                                ListRow {
                                    HStack(spacing: 14) {
                                        if let cover = playlist.coverVideoId {
                                            Thumbnail(videoID: cover, hasThumbnail: playlist.coverHasThumbnail, api: api)
                                                .frame(width: 96, height: 54).clipped()
                                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                        }
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(playlist.title)
                                                .font(.raton(17, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                                            Text("\(playlist.itemCount) fiche\(playlist.itemCount > 1 ? "s" : "")")
                                                .font(.raton(14)).foregroundStyle(Theme.textMuted)
                                        }
                                        Spacer(minLength: 0)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                        if loaded && playlists.isEmpty && errorMessage == nil {
                            EmptyMessage(text: "Aucune playlist.")
                        }
                    }
                }
                .refreshable { await load(api) }
                .task { await load(api) }
                .navigationDestination(for: PlaylistSummary.self) { PlaylistView(playlist: $0) }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func load(_ api: RatonAPI) async {
        do {
            playlists = try await api.get("/api/playlists")
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
        loaded = true
    }
}

/// A playlist: its fiches in order; a tap opens the fiche, where it is played.
struct PlaylistView: View {
    let playlist: PlaylistSummary
    @EnvironmentObject private var state: AppState
    @State private var detail: PlaylistDetail?
    @State private var errorMessage: String?

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: playlist.title, back: true)
                        ErrorMessage(text: errorMessage)
                        ForEach(detail?.items ?? []) { item in
                            NavigationLink(value: item.videoId) {
                                ListRow {
                                    HStack(spacing: 12) {
                                        Thumbnail(videoID: item.videoId, hasThumbnail: item.hasThumbnail, api: api)
                                            .frame(width: 96, height: 54).clipped()
                                            .clipShape(RoundedRectangle(cornerRadius: 6))
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(item.title)
                                                .font(.raton(16, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                                            if let channel = item.channelName {
                                                Text(channel).font(.raton(14, .semibold))
                                                    .foregroundStyle(Theme.textMuted).lineLimit(1)
                                            }
                                            Text(Format.clock(Double(item.durationSeconds)))
                                                .font(.raton(13)).foregroundStyle(Theme.textMuted)
                                        }
                                        Spacer(minLength: 0)
                                        if item.seen {
                                            Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.textFaint)
                                        }
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                        if let detail, detail.items.isEmpty {
                            EmptyMessage(text: "Cette playlist est vide.")
                        }
                    }
                }
                .refreshable { await load(api) }
                .task { await load(api) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func load(_ api: RatonAPI) async {
        do {
            detail = try await api.get("/api/playlists/\(playlist.id)")
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
    }
}
