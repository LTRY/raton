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
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        if state.serverURL == nil {
            NavigationStack {
                ServerURLView(onSaved: {})
                    .navigationTitle("Raton")
            }
        } else if state.userID == nil {
            NavigationStack {
                UserPickerView()
                    .navigationTitle("Qui es-tu ?")
            }
        } else {
            TabView {
                NavigationStack { NouveautesView() }
                    .tabItem { Label("Nouveautés", systemImage: "sparkles.tv") }
                NavigationStack { SettingsView() }
                    .tabItem { Label("Réglages", systemImage: "gearshape") }
            }
            .safeAreaInset(edge: .bottom) { NowPlayingBar() }
        }
    }
}
