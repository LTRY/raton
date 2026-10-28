import SwiftUI

@main
struct RatonApp: App {
    @StateObject private var state = AppState()
    @StateObject private var player = PlayerController()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .environmentObject(player)
                .preferredColorScheme(.light)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var state: AppState
    @State private var tab = 0

    var body: some View {
        Group {
            if state.serverURL == nil {
                NavigationStack { ServerURLView(title: "Raton", onSaved: {}) }
            } else if state.userID == nil {
                NavigationStack { UserPickerView(title: "Qui es-tu ?") }
            } else {
                Group {
                    switch tab {
                    case 0: AccueilView()
                    case 1: NavigationStack { ChannelsView() }
                    case 2: NavigationStack { LibraryView() }
                    case 3: NavigationStack { PlaylistsView() }
                    default: NavigationStack { SettingsView() }
                    }
                }
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    VStack(spacing: 8) {
                        NowPlayingBar()
                        TabPill(tab: $tab)
                    }
                    .padding(.bottom, 4)
                }
            }
        }
        .ratonPage()
        .tint(Theme.primary)
    }
}

/// The floating glass pill at the bottom: icons only, the current one on a terracotta wash.
struct TabPill: View {
    @Binding var tab: Int
    private let items = [
        (icon: "house", label: "Accueil"),
        (icon: "tv", label: "Chaînes"),
        (icon: "books.vertical", label: "Bibliothèque"),
        (icon: "text.line.first.and.arrowtriangle.forward", label: "Playlists"),
        (icon: "slider.horizontal.3", label: "Réglages"),
    ]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(items.indices, id: \.self) { index in
                Button {
                    tab = index
                } label: {
                    Image(systemName: items[index].icon)
                        .font(.system(size: 22, weight: .regular))
                        .foregroundStyle(tab == index ? Theme.primary : Theme.textMuted)
                        .frame(maxWidth: .infinity).frame(height: 48)
                        .background(Capsule().fill(tab == index ? Theme.primary.opacity(0.16) : Color.clear))
                }
                .accessibilityLabel(items[index].label)
            }
        }
        .padding(5)
        .glass(in: Capsule(), interactive: true)
        .padding(.horizontal, 12)
    }
}

/// The title row of a screen: an optional round back button, then the big bold title.
struct PageHeader<Trailing: View>: View {
    let title: String
    var back = false
    @ViewBuilder var trailing: Trailing
    @Environment(\.dismiss) private var dismiss

    init(title: String, back: Bool = false, @ViewBuilder trailing: () -> Trailing = { EmptyView() }) {
        self.title = title
        self.back = back
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: 14) {
            if back {
                Button { dismiss() } label: { Image(systemName: "arrow.left") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Retour")
            }
            Text(title).font(.raton(30, .bold)).foregroundStyle(Theme.text).lineLimit(2)
            Spacer(minLength: 0)
            trailing
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 12)
    }
}
