import SwiftUI

/// The Nouveautés, as the web shows them: Exploration's list and filters on the fiches of the followed
/// channels (`GET /api/library?followed=true`), newest publication first, not grouped by channel.
struct NouveautesView: View {
    var back = false

    var body: some View {
        LibraryView(followed: true)
    }
}

/// A fiche as a row of a list: thumbnail with its duration and progress bar, then title, channel
/// and stars, like the web's video rows.
struct VideoRow: View {
    let card: VideoCard
    let api: RatonAPI
    var dateLine = false
    // Room for the "⋮" menu a list lays over the row's top right corner.
    var menu = false

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
                    .padding(.trailing, menu ? 26 : 0)
                if dateLine {
                    if let date = Format.frenchDate(card.publishedAt) {
                        Text(date).font(.raton(14)).foregroundStyle(Theme.textMuted).lineLimit(1)
                    }
                } else if let channel = card.channelName {
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
