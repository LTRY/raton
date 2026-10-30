import SwiftUI

/// `GET /api/historique`: what the user played, newest first, grouped by day.
struct HistoriqueView: View {
    @EnvironmentObject private var state: AppState
    @State private var rows: [HistoryRow] = []
    @State private var page = 0
    @State private var totalPages = 1
    @State private var loaded = false
    @State private var loading = false
    @State private var errorMessage: String?

    private var days: [(day: String, rows: [HistoryRow])] {
        var result: [(day: String, rows: [HistoryRow])] = []
        for row in rows {
            if let last = result.last, last.day == row.day {
                result[result.count - 1].rows.append(row)
            } else {
                result.append((row.day, [row]))
            }
        }
        return result
    }

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        PageHeader(title: "Historique", back: true)
                        ErrorMessage(text: errorMessage) { Task { await reload(api) } }
                        if !loaded && errorMessage == nil { LoadingRow() }
                        ForEach(days, id: \.day) { group in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(Self.dayTitle(group.day))
                                    .font(.raton(18, .bold)).foregroundStyle(Theme.text)
                                Spacer(minLength: 0)
                                Text("\(group.rows.count) média\(group.rows.count > 1 ? "s" : "")")
                                    .font(.raton(13, .bold)).foregroundStyle(Theme.textSoft)
                                    .padding(.horizontal, 10).padding(.vertical, 4)
                                    .surface(in: Capsule())
                            }
                            .padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 6)
                            ForEach(group.rows) { row in
                                rowView(row)
                                    .task { await loadMore(api, after: row) }
                            }
                        }
                        if loaded && rows.isEmpty && errorMessage == nil {
                            EmptyMessage(text: "Rien n'a encore été lu.")
                        }
                    }
                }
                .barClearance()
                .refreshable { await reload(api) }
                .task { await reload(api) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    @ViewBuilder
    private func rowView(_ row: HistoryRow) -> some View {
        let content = ListRow {
            VStack(alignment: .leading, spacing: 4) {
                Text(row.video?.title ?? row.playback.title)
                    .font(.raton(16, .bold)).foregroundStyle(Theme.text).lineLimit(2)
                if let channel = row.channel {
                    Text(channel.name).font(.raton(14, .semibold)).foregroundStyle(Theme.textMuted).lineLimit(1)
                }
                Text("\(row.playback.action) · \(row.playback.mediaLabel) · \(Format.clock(row.watchedSeconds))")
                    .font(.raton(13)).foregroundStyle(Theme.textMuted)
                if !row.playback.isCompleted && row.playback.progressPercent > 0 {
                    ProgressView(value: min(row.playback.progressPercent, 100), total: 100).tint(Theme.primary)
                }
            }
        }
        .opacity(row.shownState == "normal" ? 1 : 0.55)
        // The fiche may have been deleted since: then there is nothing to open.
        if let video = row.video {
            NavigationLink(value: video.id) { content }.buttonStyle(.plain)
        } else {
            content
        }
    }

    private func reload(_ api: RatonAPI) async {
        do {
            let reply: HistoriqueReply = try await api.get("/api/historique", query: ["page": "1"])
            rows = reply.rows
            page = reply.page
            totalPages = reply.totalPages
            errorMessage = nil
        } catch {
            if !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
        loaded = true
    }

    private func loadMore(_ api: RatonAPI, after row: HistoryRow) async {
        guard row.id == rows.last?.id, page < totalPages, !loading else { return }
        loading = true
        defer { loading = false }
        if let reply: HistoriqueReply = try? await api.get("/api/historique", query: ["page": String(page + 1)]) {
            let known = Set(rows.map(\.id))
            rows += reply.rows.filter { !known.contains($0.id) }
            page = reply.page
            totalPages = reply.totalPages
        }
    }

    /// "2026-10-28" as "mercredi 28 octobre"; the API gives the day, the app only writes it in French.
    static func dayTitle(_ day: String) -> String {
        let parser = DateFormatter()
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: day) else { return day }
        let writer = DateFormatter()
        writer.locale = Locale(identifier: "fr_FR")
        writer.dateFormat = "EEEE d MMMM"
        let text = writer.string(from: date)
        return text.prefix(1).uppercased() + text.dropFirst()
    }
}
