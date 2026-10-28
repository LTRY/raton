import SwiftUI

/// `GET /api/nouveautes`: the user's Nouveautés, one stack of fiches per channel, ten channels per page.
final class NouveautesModel: ObservableObject {
    @Published var stacks: [NouveautesStack] = []
    @Published var loading = false
    @Published var errorMessage: String?
    private var page = 0
    private var totalPages = 1

    /// Reloads from the first page; the current list stays on screen until the answer comes.
    func reload(api: RatonAPI) async {
        do {
            let reply: NouveautesReply = try await api.get("/api/nouveautes", query: ["page": "1"])
            stacks = reply.stacks
            page = reply.page
            totalPages = reply.totalPages
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
    }

    func loadMoreIfNeeded(api: RatonAPI, lastStack: NouveautesStack) async {
        guard lastStack.id == stacks.last?.id, page < totalPages, !loading else { return }
        loading = true
        defer { loading = false }
        do {
            let reply: NouveautesReply = try await api.get(
                "/api/nouveautes", query: ["page": String(page + 1)])
            let known = Set(stacks.map(\.id))
            stacks += reply.stacks.filter { !known.contains($0.id) }
            page = reply.page
            totalPages = reply.totalPages
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct NouveautesView: View {
    @EnvironmentObject private var state: AppState
    @StateObject private var model = NouveautesModel()
    @State private var firstLoadDone = false

    var body: some View {
        Group {
            if let api = state.api {
                List {
                    if let message = model.errorMessage {
                        Text(message).foregroundStyle(.red)
                    }
                    ForEach(model.stacks) { stack in
                        Section(stack.channel.name) {
                            ForEach(stack.items) { card in
                                NavigationLink(value: card.id) {
                                    VideoRow(card: card, api: api)
                                }
                            }
                        }
                        .task { await model.loadMoreIfNeeded(api: api, lastStack: stack) }
                    }
                }
                .refreshable { await model.reload(api: api) }
                .overlay {
                    if firstLoadDone && model.stacks.isEmpty && model.errorMessage == nil {
                        Text("Aucune nouveauté").foregroundStyle(.secondary)
                    } else if !firstLoadDone {
                        ProgressView()
                    }
                }
                // Also runs when coming back from a fiche, which left the Nouveautés.
                .task {
                    await model.reload(api: api)
                    firstLoadDone = true
                }
                .navigationDestination(for: Int.self) { videoID in
                    FicheView(videoID: videoID)
                }
            }
        }
        .navigationTitle("Nouveautés")
    }
}

struct VideoRow: View {
    let card: VideoCard
    let api: RatonAPI

    var body: some View {
        HStack(spacing: 12) {
            Thumbnail(videoID: card.id, hasThumbnail: card.hasThumbnail, api: api)
                .frame(width: 120, height: 68)
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 4) {
                Text(card.title).font(.subheadline).lineLimit(3)
                HStack(spacing: 6) {
                    if card.isNew { Text("Nouveau").font(.caption2).bold().foregroundStyle(.tint) }
                    if let seconds = card.durationSeconds {
                        Text(Format.clock(Double(seconds))).font(.caption).foregroundStyle(.secondary)
                    }
                    if card.shownState == "watched" {
                        Text("Vu").font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let playback = card.playback, !playback.isCompleted, playback.progressPercent > 0 {
                    ProgressView(value: min(playback.progressPercent, 100), total: 100)
                }
            }
        }
        .opacity(card.shownState == "normal" ? 1 : 0.55)
    }
}

struct Thumbnail: View {
    let videoID: Int
    let hasThumbnail: Bool
    let api: RatonAPI

    var body: some View {
        if hasThumbnail {
            AsyncImage(url: api.url("/api/videos/\(videoID)/thumbnail")) { image in
                image.resizable().scaledToFill()
            } placeholder: {
                Color.gray.opacity(0.2)
            }
        } else {
            ZStack {
                Color.gray.opacity(0.2)
                Image(systemName: "film").foregroundStyle(.secondary)
            }
        }
    }
}
