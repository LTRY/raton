import SwiftUI
import WidgetKit

/// The Nouveautés widget: Raton and the number of new fiches on the followed channels
/// (`GET /api/library?followed=true`, the same list as the app's Nouveautés screen). The server
/// address and the user come from the App Group the app writes them to.
struct NouveautesEntry: TimelineEntry {
    let date: Date
    /// nil when no server is chosen yet, or when it cannot be reached.
    let count: Int?
    let configured: Bool
}

struct NouveautesProvider: TimelineProvider {
    private static let group = "group.fr.raton.app"

    func placeholder(in context: Context) -> NouveautesEntry {
        NouveautesEntry(date: .now, count: 12, configured: true)
    }

    func getSnapshot(in context: Context, completion: @escaping (NouveautesEntry) -> Void) {
        if context.isPreview { completion(placeholder(in: context)) } else {
            Task { completion(await load()) }
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NouveautesEntry>) -> Void) {
        Task {
            let entry = await load()
            // The system decides when to actually refresh; the app also asks for a reload when it opens.
            completion(Timeline(entries: [entry], policy: .after(.now.addingTimeInterval(30 * 60))))
        }
    }

    private func load() async -> NouveautesEntry {
        let defaults = UserDefaults(suiteName: Self.group)
        guard let server = defaults?.string(forKey: "serverURL"),
              let url = URL(string: server + "/api/library?followed=true&page=1") else {
            return NouveautesEntry(date: .now, count: nil, configured: false)
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        if let user = defaults?.object(forKey: "userID") as? Int {
            request.setValue(String(user), forHTTPHeaderField: "X-Raton-User")
        }
        let total = try? await URLSession.shared.data(for: request).0
        let count = total.flatMap { (try? JSONSerialization.jsonObject(with: $0) as? [String: Any])?["total"] as? Int }
        return NouveautesEntry(date: .now, count: count, configured: true)
    }
}

struct NouveautesWidgetView: View {
    let entry: NouveautesEntry
    @Environment(\.widgetFamily) private var family

    private var cream: Color { Color(red: 0xFB / 255, green: 0xF6 / 255, blue: 0xEE / 255) }
    private var ink: Color { Color(red: 0x2B / 255, green: 0x20 / 255, blue: 0x18 / 255) }
    private var terracotta: Color { Color(red: 0xC2 / 255, green: 0x41 / 255, blue: 0x0C / 255) }

    var body: some View {
        Group {
            if family == .systemSmall {
                VStack(spacing: 4) { image; text }
            } else {
                HStack(spacing: 16) { image; text }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .containerBackground(cream, for: .widget)
    }

    private var image: some View {
        Image("Raton").resizable().scaledToFit().frame(maxHeight: family == .systemSmall ? 62 : 100)
    }

    private var text: some View {
        VStack(spacing: 2) {
            if !entry.configured {
                Text("Ouvrez Raton").font(.system(size: 15, weight: .bold)).foregroundStyle(ink)
            } else if let count = entry.count {
                Text("\(count)").font(.system(size: family == .systemSmall ? 32 : 44, weight: .heavy))
                    .foregroundStyle(terracotta).lineLimit(1).minimumScaleFactor(0.6)
                Text(count > 1 ? "Nouveautés" : "Nouveauté").font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(ink).lineLimit(1).minimumScaleFactor(0.7)
            } else {
                Text("Hors ligne").font(.system(size: 15, weight: .bold)).foregroundStyle(ink)
            }
        }
    }
}

@main
struct RatonWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "RatonNouveautes", provider: NouveautesProvider()) { entry in
            NouveautesWidgetView(entry: entry)
        }
        .configurationDisplayName("Nouveautés")
        .description("Le nombre de nouvelles fiches sur vos chaînes suivies.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}
