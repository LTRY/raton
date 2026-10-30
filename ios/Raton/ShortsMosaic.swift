import AVKit
import SwiftUI

/// The shorts of a channel page as a mosaic of portrait tiles, like the web's `.channel-video-grid-shorts`
/// on a phone: three columns, 200pt rows, dense flow, a big 2×2 tile for a new or 5-star short.
struct ShortsMosaic: View {
    let cards: [VideoCard]
    let api: RatonAPI
    let onAppear: (VideoCard) async -> Void

    @EnvironmentObject private var player: PlayerController
    // Shorts whose file is being downloaded (the tile shows a spinner), and the one playing fullscreen.
    @State private var downloading: Set<Int> = []
    @State private var failure: String?

    // Mirrors `shorts_feature_flags` (`front/library.py`): a big tile every `rhythm` tiles,
    // never closer than `minGap` positions to another one.
    private static let rhythm = 7
    private static let minGap = 6

    private var featured: [Bool] {
        var flags = [Bool](repeating: false, count: cards.count)
        func fits(_ index: Int) -> Bool {
            !flags.indices.contains { flags[$0] && abs(index - $0) < Self.minGap }
        }
        for (index, card) in cards.enumerated() where (card.isNew || card.rating >= 5) && fits(index) {
            flags[index] = true
        }
        for index in stride(from: 0, to: cards.count, by: Self.rhythm) where fits(index) {
            flags[index] = true
        }
        return flags
    }

    var body: some View {
        let flags = featured
        MosaicLayout {
            ForEach(Array(cards.enumerated()), id: \.element.id) { index, card in
                ZStack(alignment: .bottomTrailing) {
                    Button { tap(card) } label: {
                        ShortTile(card: card, api: api, feature: flags[index], loading: downloading.contains(card.id))
                    }
                    .buttonStyle(.plain)
                    // The fiche stays one tap away, like the web tile's arrow.
                    NavigationLink(value: card.id) {
                        Image(systemName: "arrow.up.right")
                            .font(.system(size: 11, weight: .bold)).foregroundStyle(.white)
                            .frame(width: 26, height: 26)
                            .background(Circle().fill(Color(hex: 0x140C06).opacity(0.8)))
                            .padding(8)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Voir la fiche de \(card.title)")
                }
                .layoutValue(key: FeatureKey.self, value: flags[index])
                .task { await onAppear(card) }
            }
        }
        .padding(12)
        .alert("Short indisponible", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(failure ?? "")
        }
    }

    /// A tap plays the short fullscreen; a short without a file is downloaded first (1080p, or the best below).
    private func tap(_ card: VideoCard) {
        guard !downloading.contains(card.id) else { return }
        Task {
            do {
                if !card.hasVideo {
                    downloading.insert(card.id)
                    defer { downloading.remove(card.id) }
                    let _: QueuedJob = try await api.post("/api/videos/\(card.id)/media/video/download",
                                                         body: ["video_quality": "1080"])
                    var ready = false
                    for _ in 0..<100 where !ready {
                        try await Task.sleep(nanoseconds: 3_000_000_000)
                        let fresh: VideoDetail = try await api.get("/api/videos/\(card.id)")
                        ready = fresh.mediaUrls.video != nil
                    }
                    guard ready else { throw ShortError.notDownloaded }
                }
                let detail: VideoDetail = try await api.get("/api/videos/\(card.id)")
                player.play(detail: detail, kind: .video, api: api)
                if let avPlayer = player.player {
                    ShortPlayerPresenter.present(avPlayer) { player.stop() }
                }
            } catch {
                failure = error.localizedDescription
            }
        }
    }
}

private struct FeatureKey: LayoutValueKey {
    static let defaultValue = false
}

/// Places tiles in reading order on the first free cell of a 3-column grid (CSS `grid-auto-flow: dense`).
private struct MosaicLayout: Layout {
    let columns = 3
    let gap: CGFloat = 6
    let rowHeight: CGFloat = 200

    private func placements(_ subviews: Subviews) -> (cells: [(column: Int, row: Int, span: Int)], rows: Int) {
        var taken: [[Bool]] = []
        var cells: [(column: Int, row: Int, span: Int)] = []
        func isFree(_ column: Int, _ row: Int, _ span: Int) -> Bool {
            guard column + span <= columns else { return false }
            for r in row..<(row + span) where r < taken.count {
                for c in column..<(column + span) where taken[r][c] { return false }
            }
            return true
        }
        for subview in subviews {
            let span = subview[FeatureKey.self] ? 2 : 1
            var row = 0
            search: while true {
                for column in 0..<columns where isFree(column, row, span) {
                    while taken.count < row + span { taken.append([Bool](repeating: false, count: columns)) }
                    for r in row..<(row + span) { for c in column..<(column + span) { taken[r][c] = true } }
                    cells.append((column, row, span))
                    break search
                }
                row += 1
            }
        }
        return (cells, taken.count)
    }

    private func cellWidth(_ width: CGFloat) -> CGFloat {
        (width - gap * CGFloat(columns - 1)) / CGFloat(columns)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = placements(subviews).rows
        let height = rows == 0 ? 0 : CGFloat(rows) * rowHeight + CGFloat(rows - 1) * gap
        return CGSize(width: proposal.width ?? 0, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let width = cellWidth(bounds.width)
        for (subview, cell) in zip(subviews, placements(subviews).cells) {
            let span = CGFloat(cell.span)
            subview.place(
                at: CGPoint(x: bounds.minX + CGFloat(cell.column) * (width + gap),
                            y: bounds.minY + CGFloat(cell.row) * (rowHeight + gap)),
                proposal: ProposedViewSize(width: width * span + gap * (span - 1),
                                           height: rowHeight * span + gap * (span - 1)))
        }
    }
}

private enum ShortError: LocalizedError {
    case notDownloaded
    var errorDescription: String? { "Le téléchargement n'a pas abouti." }
}

/// Presents the system player fullscreen, with its own close button, and tells when it is dismissed.
private enum ShortPlayerPresenter {
    private final class Controller: AVPlayerViewController {
        var onDismiss: (() -> Void)?
        override func viewDidDisappear(_ animated: Bool) {
            super.viewDidDisappear(animated)
            if isBeingDismissed { onDismiss?() }
        }
    }

    static func present(_ player: AVPlayer, onDismiss: @escaping () -> Void) {
        let controller = Controller()
        controller.player = player
        controller.modalPresentationStyle = .fullScreen
        controller.onDismiss = onDismiss
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              var top = scene.windows.first(where: \.isKeyWindow)?.rootViewController else { return }
        while let presented = top.presentedViewController { top = presented }
        top.present(controller, animated: true)
    }
}

private struct ShortTile: View {
    let card: VideoCard
    let api: RatonAPI
    let feature: Bool
    let loading: Bool

    var body: some View {
        Color.clear
            .overlay { Thumbnail(videoID: card.id, hasThumbnail: card.hasThumbnail, api: api) }
            .clipped()
            .overlay {
                LinearGradient(colors: [.clear, Color(hex: 0x0A0603).opacity(0.8)],
                               startPoint: UnitPoint(x: 0.5, y: 0.5), endPoint: .bottom)
            }
            .overlay(alignment: .topLeading) {
                if card.isNew {
                    Text("Nouveau").font(.raton(11, .bold)).foregroundStyle(Theme.primary)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Capsule().fill(Theme.tint))
                        .padding(8)
                }
            }
            .overlay(alignment: .topTrailing) {
                if let seconds = card.durationSeconds {
                    Text(Format.clock(Double(seconds)))
                        .font(.raton(10, .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(Color(hex: 0x2B3340)))
                        .padding(8)
                }
            }
            .overlay(alignment: .bottomLeading) {
                VStack(alignment: .leading, spacing: 8) {
                    if feature {
                        Text(card.title)
                            .font(.raton(17, .heavy)).foregroundStyle(.white).lineLimit(3)
                            .multilineTextAlignment(.leading)
                            .shadow(color: .black.opacity(0.4), radius: 4, y: 1)
                    }
                    if card.rating > 0 {
                        Text(String(repeating: "★", count: card.rating))
                            .font(.system(size: 11)).foregroundStyle(Theme.amber)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(RoundedRectangle(cornerRadius: 4).fill(Color(hex: 0x140C06).opacity(0.8)))
                    }
                }
                .padding(feature ? 14 : 8)
            }
            .overlay(alignment: .bottom) {
                if let playback = card.playback, !playback.isCompleted, playback.progressPercent > 0 {
                    GeometryReader { proxy in
                        Theme.primary
                            .frame(width: proxy.size.width * min(playback.progressPercent, 100) / 100, height: 3)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    }
                }
            }
            .overlay {
                if loading {
                    // The download has no text: a spinner on the tile says it is on its way.
                    ZStack {
                        Color.black.opacity(0.45)
                        ProgressView().tint(.white).scaleEffect(1.3)
                    }
                }
            }
            .background(Theme.surfaceMuted)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .opacity(card.shownState == "normal" ? 1 : 0.55)
            .accessibilityLabel(card.title)
    }
}
