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
                    if tab == 0 {
                        NavigationStack { NouveautesView() }
                    } else {
                        NavigationStack { SettingsView() }
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

/// The floating pill at the bottom, as on the web: icons only, the current one on a terracotta wash.
struct TabPill: View {
    @Binding var tab: Int
    private let items = [
        (icon: "books.vertical", label: "Nouveautés"),
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
                        .frame(width: 84, height: 48)
                        .background(Capsule().fill(tab == index ? Theme.tint : Color.clear))
                }
                .accessibilityLabel(items[index].label)
            }
        }
        .padding(5)
        .background(Capsule().fill(Color(hex: 0xFFF8EF)))
        .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
        .shadow(color: Theme.shadow.opacity(0.14), radius: 12, y: 6)
    }
}

/// The title row of a screen: an optional round back button, then the big bold title.
struct PageHeader: View {
    let title: String
    var back = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        HStack(spacing: 14) {
            if back {
                Button { dismiss() } label: { Image(systemName: "arrow.left") }
                    .buttonStyle(CircleButtonStyle())
                    .accessibilityLabel("Retour")
            }
            Text(title).font(.raton(30, .bold)).foregroundStyle(Theme.text)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 12)
    }
}
