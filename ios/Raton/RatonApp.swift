import SwiftUI
import WidgetKit

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
    // The height of the mini player and the tab bar together, measured, so the pages can leave room.
    @State private var barHeight: CGFloat = 0
    // The pages pushed on the Bibliothèque and Playlists tabs, kept here so that the mini player can open one.
    @State private var libraryPath = NavigationPath()
    @State private var playlistsPath = NavigationPath()
    @EnvironmentObject private var player: PlayerController
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if state.serverURL == nil {
                NavigationStack { ServerURLView(title: "Raton", onSaved: {}) }
            } else if state.userID == nil {
                NavigationStack { UserPickerView(title: "Qui es-tu ?") }
            } else {
                ZStack(alignment: .bottom) {
                    Group {
                        switch tab {
                        case 0: AccueilView()
                        case 1: NavigationStack { ChannelsView() }
                        case 2: NavigationStack(path: $libraryPath) { LibraryView() }
                        case 3: PlaylistsView(path: $playlistsPath)
                        default: NavigationStack { SettingsView() }
                        }
                    }
                    .id(tab)
                    .transition(.opacity)
                    .animation(.easeInOut(duration: 0.15), value: tab)
                    // Room under the pages for the bar, which floats over them.
                    .safeAreaInset(edge: .bottom, spacing: 0) {
                        Color.clear.frame(height: barHeight + (keyboardUp ? 0 : TabPill.bottomGap))
                    }

                    VStack(spacing: 6) {
                        NowPlayingBar(open: openPlayer)
                        // The web hides the bar while a text field has the keyboard.
                        if !keyboardUp { TabPill(tab: $tab) }
                    }
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { barHeight = $0 }
                    .padding(.bottom, keyboardUp ? 0 : TabPill.bottomGap)
                }
                // The bar's gap is measured from the screen's bottom edge, not from the home indicator's
                // safe area: Apple's own floating bars sit about 21 pt from it, closer than the safe area.
                .ignoresSafeArea(.container, edges: .bottom)
            }
        }
        .ratonPage()
        .tint(Theme.primary)
        // Past this size the fixed-height rows and pills of the screens no longer fit.
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        .sensoryFeedback(.selection, trigger: tab)
        // The Nouveautés widget counts what the app has just shown.
        .onChange(of: scenePhase) { phase in if phase == .background { WidgetCenter.shared.reloadAllTimelines() } }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in keyboardUp = true }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in keyboardUp = false }
    }
}

extension RootView {
    /// A tap on the mini player's title: the playlist page when a playlist is playing, else the fiche.
    fileprivate func openPlayer() {
        if let queue = player.queue {
            let playlist = PlaylistSummary(id: queue.playlistID, title: queue.title, source: "", categories: [],
                                           freeListening: queue.free, itemCount: queue.tracks.count,
                                           coverVideoId: nil, coverHasThumbnail: false)
            playlistsPath = NavigationPath([playlist])
            tab = 3
        } else if let videoID = player.track?.videoID {
            libraryPath = NavigationPath([videoID])
            tab = 2
        }
    }
}

/// The floating bar at the bottom, in Liquid Glass like iOS 26's own tab bars: a glass capsule, and a glass
/// bubble under the current tab that glides to the one tapped. Icons only, as on the web; they are the web's
/// own, and each plays its animation when tapped.
struct TabPill: View {
    @Binding var tab: Int
    /// The gap to the phone's sides, and to the bottom edge of the screen (Apple's floating bars: about 14 and 21 pt).
    static let margin: CGFloat = 14
    static let bottomGap: CGFloat = 21
    /// Concentric with the phone's rounded corners, down to a full capsule.
    static let shape = ConcentricRectangle(corners: .concentric(minimum: 31), isUniform: true)
    @State private var plays = [0, 0, 0, 0, 0]
    private let items: [(kind: TabIconKind, label: String)] = [
        (.home, "Accueil"), (.channels, "Chaînes"), (.library, "Bibliothèque"), (.playlists, "Playlists"), (.settings, "Paramètres"),
    ]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(items.indices, id: \.self) { index in
                Button {
                    tab = index
                    plays[index] += 1
                } label: {
                    TabIcon(kind: items[index].kind, color: tab == index ? Theme.primary : Theme.textMuted,
                            knob: Color(hex: 0xF6EFE6), trigger: plays[index], size: 28)
                        .frame(maxWidth: .infinity).frame(height: 52)
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(items[index].label)
                .accessibilityAddTraits(tab == index ? .isSelected : [])
            }
        }
        .background {
            // The bubble: one glass capsule under the current tab, sliding between tabs.
            GeometryReader { proxy in
                let width = proxy.size.width / CGFloat(items.count)
                Color.clear
                    .frame(width: width, height: proxy.size.height)
                    .glassEffect(.regular.tint(Theme.primary.opacity(0.16)).interactive(), in: Capsule())
                    .offset(x: CGFloat(tab) * width)
                    .animation(.spring(response: 0.35, dampingFraction: 0.78), value: tab)
            }
        }
        .padding(5)
        .glassEffect(.regular, in: Self.shape)
        .shadow(color: Theme.shadow.opacity(0.10), radius: 12, y: 8)
        .padding(.horizontal, Self.margin)
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
