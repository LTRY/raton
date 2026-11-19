import SwiftUI

/// Where the Accueil's buttons lead; the API gives web paths, the app maps the ones it has screens for.
enum Route: Hashable {
    case nouveautes
    case historique
}

private struct OpenRouteKey: EnvironmentKey {
    static let defaultValue: (Route) -> Void = { _ in }
}

extension EnvironmentValues {
    /// Pushes a page on the tab's stack (set by the root, which owns the stacks' paths). The page is a
    /// value in the path like a fiche: a page shown by a Bool (`navigationDestination(isPresented:)`)
    /// was rebuilt in place of a fiche pushed over it.
    var openRoute: (Route) -> Void {
        get { self[OpenRouteKey.self] }
        set { self[OpenRouteKey.self] = newValue }
    }
}

/// The home: Raton and his line of this visit (`POST /api/raton/visit`) and the way to the Nouveautés
/// and the Historique.
struct AccueilView: View {
    @EnvironmentObject private var state: AppState
    @State private var line: RatonLine?
    // Why Raton has no line (server unreachable): the audios kept on the phone are then offered.
    @State private var errorMessage: String?
    @EnvironmentObject private var offline: OfflineStore
    @State private var path = NavigationPath()

    var body: some View {
        NavigationStack(path: $path) {
            content
        }
    }

    private var content: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(spacing: 20) {
                        Spacer(minLength: 30)
                        CachedImage(url: api.url("/static/img/raton/\(line?.art ?? "popcorn.webp")")) { image in
                            image.resizable().scaledToFit()
                        } placeholder: { Color.clear }
                        .frame(height: 260)
                        Text(line?.line ?? " ")
                            .font(.raton(30, .bold)).foregroundStyle(Theme.text)
                            .multilineTextAlignment(.center).padding(.horizontal, 24)
                        if let line, !line.ctaLabel.isEmpty, let route = Self.route(for: line.ctaHref) {
                            NavigationLink(value: route) { Text(line.ctaLabel) }
                                .buttonStyle(PillButtonStyle())
                        }
                        if line == nil, let errorMessage {
                            Text(errorMessage).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
                                .multilineTextAlignment(.center).padding(.horizontal, 24)
                            if !offline.items.isEmpty {
                                NavigationLink { OfflineView() } label: {
                                    Text("Écouter hors ligne (\(offline.items.count))")
                                }
                                .buttonStyle(PillButtonStyle())
                            }
                        }
                        Spacer(minLength: 30)
                    }
                    .frame(maxWidth: .infinity, minHeight: 640)
                }
                .barClearance()
                .task { await visit(api) }
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .nouveautes: NouveautesView(back: true)
                    case .historique: HistoriqueView()
                    }
                }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func visit(_ api: RatonAPI) async {
        guard line == nil else { return }
        do {
            line = try await api.post("/api/raton/visit")
            errorMessage = nil
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription }
        }
    }

    /// The paths the API gives for Raton's button (`/dashboard/nouveautes`, `/dashboard/historique`).
    static func route(for href: String) -> Route? {
        switch href {
        case "/dashboard/nouveautes": return .nouveautes
        case "/dashboard/historique": return .historique
        default: return nil
        }
    }
}
