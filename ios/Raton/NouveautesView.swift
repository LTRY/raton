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
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Nouveautés")
                        if let message = model.errorMessage {
                            Text(message).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
                                .padding(16)
                        }
                        ForEach(model.stacks) { stack in
                            Text(stack.channel.name)
                                .font(.raton(20, .bold)).foregroundStyle(Theme.text)
                                .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 8)
                            ForEach(stack.items) { card in
                                NavigationLink(value: card.id) {
                                    VideoRow(card: card, api: api)
                                }
                                .buttonStyle(.plain)
                            }
                            Color.clear.frame(height: 0)
                                .task { await model.loadMoreIfNeeded(api: api, lastStack: stack) }
                        }
                        if firstLoadDone && model.stacks.isEmpty && model.errorMessage == nil {
                            Text("Aucune nouveauté")
                                .font(.raton(16)).foregroundStyle(Theme.textMuted)
                                .frame(maxWidth: .infinity).padding(.top, 60)
                        }
                    }
                }
                .refreshable { await model.reload(api: api) }
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
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }
}

/// A fiche as a row of a list: thumbnail with its duration and progress bar, then title, channel
/// and stars, like the web's video rows.
struct VideoRow: View {
    let card: VideoCard
    let api: RatonAPI

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            ZStack(alignment: .bottomTrailing) {
                Thumbnail(videoID: card.id, hasThumbnail: card.hasThumbnail, api: api)
                    .frame(width: 176, height: 100)
                    .clipped()
                if let seconds = card.durationSeconds {
                    Text(Format.clock(Double(seconds)))
                        .font(.raton(12, .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(Color(hex: 0x2B3340)))
                        .padding(6)
                }
            }
            .overlay(alignment: .bottomLeading) {
                if let playback = card.playback, !playback.isCompleted, playback.progressPercent > 0 {
                    GeometryReader { proxy in
                        Theme.primary
                            .frame(width: proxy.size.width * min(playback.progressPercent, 100) / 100, height: 3)
                            .frame(maxHeight: .infinity, alignment: .bottom)
                    }
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(card.title)
                    .font(.raton(16, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                if let channel = card.channelName {
                    Text(channel).font(.raton(14, .semibold)).foregroundStyle(Theme.textMuted).lineLimit(1)
                }
                Spacer(minLength: 0)
                HStack {
                    if card.isNew {
                        Text("Nouveau").font(.raton(12, .bold)).foregroundStyle(Theme.primary)
                            .padding(.horizontal, 8).padding(.vertical, 2)
                            .background(Capsule().fill(Theme.tint))
                    }
                    Spacer(minLength: 0)
                    StarsView(rating: card.rating, size: 13)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .frame(height: 100)
        }
        .background(Color.white)
        .overlay(alignment: .bottom) { Theme.border.frame(height: 1) }
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
                Theme.surfaceMuted
            }
        } else {
            Theme.surfaceMuted
        }
    }
}
