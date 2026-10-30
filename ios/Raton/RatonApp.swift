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
                .environmentObject(OfflineStore.shared)
                .preferredColorScheme(.light)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var state: AppState
    @State private var tab = 0
    @State private var keyboardUp = false

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
                    case 3: PlaylistsView()
                    default: NavigationStack { SettingsView() }
                    }
                }
                .id(tab)
                .transition(.opacity)
                .animation(.easeInOut(duration: 0.15), value: tab)
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    VStack(spacing: 8) {
                        NowPlayingBar()
                        // The web hides the bar while a text field has the keyboard.
                        if !keyboardUp { TabPill(tab: $tab) }
                    }
                    // The pill sits 14 pt from the screen's edge, following the phone's rounded corners
                    // (just above the home indicator): the inset reaches under the home indicator so the
                    // whole bar stays inside its own bounds and receives taps.
                    .padding(.bottom, 14)
                    .ignoresSafeArea(.container, edges: .bottom)
                }
            }
        }
        .ratonPage()
        .tint(Theme.primary)
        // Past this size the fixed-height rows and pills of the screens no longer fit.
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        .sensoryFeedback(.selection, trigger: tab)
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in keyboardUp = true }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in keyboardUp = false }
    }
}

/// The floating pill at the bottom, as on the web: icons only, the current one on a terracotta wash.
/// The icons are the web's own, and each plays its animation when tapped.
struct TabPill: View {
    @Binding var tab: Int
    @State private var plays = [0, 0, 0, 0, 0]
    private let items: [(kind: TabIconKind, label: String)] = [
        (.home, "Accueil"), (.channels, "Chaînes"), (.library, "Bibliothèque"), (.playlists, "Playlists"), (.settings, "Paramètres"),
    ]

    var body: some View {
        HStack(spacing: 4) {
            ForEach(items.indices, id: \.self) { index in
                let active = tab == index
                Button {
                    tab = index
                    plays[index] += 1
                } label: {
                    TabIcon(kind: items[index].kind, color: active ? Theme.primary : Theme.textMuted,
                            knob: active ? Color(hex: 0xFFF1E8) : Color(hex: 0xF6EFE6), trigger: plays[index], size: 28)
                        .frame(maxWidth: .infinity).frame(height: 48)
                        .background {
                            if active {
                                // The web's active tab: pale terracotta wash, white top highlight, warm shadow.
                                Capsule().fill(Color(hex: 0xFFF1E8).opacity(0.9))
                                    .overlay(Capsule().stroke(LinearGradient(colors: [.white.opacity(0.9), .clear],
                                                                             startPoint: .top, endPoint: .center), lineWidth: 1))
                                    .shadow(color: Theme.primary.opacity(0.15), radius: 4, y: 2)
                            }
                        }
                }
                .accessibilityLabel(items[index].label)
            }
        }
        .padding(5)
        // The web's bar is a light frosted glass (blur 8 px, 12 % white fill, light rim) over the page.
        .background(Capsule().fill(.ultraThinMaterial))
        .background(Capsule().fill(Color.white.opacity(0.12)))
        .overlay(Capsule().stroke(Color.white.opacity(0.5), lineWidth: 1))
        .overlay(Capsule().stroke(LinearGradient(colors: [.white.opacity(0.6), .clear], startPoint: .top, endPoint: .center), lineWidth: 1))
        .shadow(color: Theme.shadow.opacity(0.10), radius: 12, y: 8)
        .padding(.horizontal, 12)
        // The active tab plays its icon when the bar first shows.
        .onAppear { plays[tab] += 1 }
    }
}

/// The title row of a screen: an optional round back button, then the big bold title.
struct PageHeader<Trailing: View>: View {
    let title: String
    var back = false
    // The number next to the title, in the little pill of the web's list pages.
    var badge: Int? = nil
    @ViewBuilder var trailing: Trailing
    @Environment(\.dismiss) private var dismiss

    init(title: String, back: Bool = false, badge: Int? = nil, @ViewBuilder trailing: () -> Trailing = { EmptyView() }) {
        self.title = title
        self.back = back
        self.badge = badge
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: 14) {
            if back {
                Button { dismiss() } label: { Image(systemName: "arrow.left") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Retour")
            }
            Text(title).font(.raton(26, .bold)).foregroundStyle(Theme.text).lineLimit(2)
            if let badge {
                Text("\(badge)").font(.raton(13, .semibold)).foregroundStyle(Theme.textMuted)
                    .padding(.horizontal, 10).padding(.vertical, 3)
                    .background(Capsule().fill(Theme.surfaceMuted))
            }
            Spacer(minLength: 0)
            trailing
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 12)
    }
}

// Only vertical scrolling moves a page: the swipe from the left edge that carries the page back is
// switched off (every screen has its own back button).
extension UINavigationController {
    open override func viewDidLoad() {
        super.viewDidLoad()
        interactivePopGestureRecognizer?.isEnabled = false
    }
}
