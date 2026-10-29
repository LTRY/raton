import SwiftUI

/// Where the Accueil's buttons lead; the API gives web paths, the app maps the ones it has screens for.
enum Route: Hashable {
    case nouveautes
    case historique
    case chat(question: String)
    case search
}

/// The home: Raton and his line of this visit (`POST /api/raton/visit`), the way to the Nouveautés
/// and the Historique, and the bar to question the library.
struct AccueilView: View {
    @EnvironmentObject private var state: AppState
    @State private var line: RatonLine?
    @State private var question = ""
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
                        HStack {
                            Menu {
                                NavigationLink(value: Route.nouveautes) { Label("Nouveautés", systemImage: "sparkles") }
                                NavigationLink(value: Route.historique) { Label("Historique", systemImage: "clock.arrow.circlepath") }
                                NavigationLink(value: Route.search) { Label("Recherche YouTube", systemImage: "magnifyingglass") }
                            } label: { Image(systemName: "line.3.horizontal") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Menu")
                            Spacer()
                        }
                        .padding(.horizontal, 16).padding(.top, 8)
                        Spacer(minLength: 30)
                        AsyncImage(url: api.url("/static/img/raton/\(line?.art ?? "popcorn.webp")")) { image in
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
                        Spacer(minLength: 30)
                        HStack {
                            TextField("Pose une question à ta bibliothèque", text: $question)
                                .font(.raton(16)).submitLabel(.send)
                                .onSubmit(ask)
                            Button(action: ask) {
                                Image(systemName: "arrow.up.circle.fill")
                                    .font(.system(size: 30)).foregroundStyle(Theme.primary)
                            }
                            .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                        .padding(.horizontal, 18).padding(.vertical, 10)
                        .surface(in: Capsule())
                        .padding(.horizontal, 16).padding(.bottom, 16)
                    }
                    .frame(minHeight: 640)
                }
                .task { await visit(api) }
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .nouveautes: NouveautesView(back: true)
                    case .historique: HistoriqueView()
                    case .chat(let question): ChatView(initialQuestion: question)
                    case .search: YoutubeSearchView()
                    }
                }
                .navigationDestination(for: Int.self) { FicheView(videoID: $0) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func ask() {
        let asked = question.trimmingCharacters(in: .whitespaces)
        guard !asked.isEmpty else { return }
        question = ""
        // The bar only starts the discussion: ChatView sends it.
        path.append(Route.chat(question: asked))
    }

    private func visit(_ api: RatonAPI) async {
        if line == nil { line = try? await api.post("/api/raton/visit") }
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
