import SwiftUI

/// Picks the user the app acts for (`GET /api/users`); also reachable from Réglages.
struct UserPickerView: View {
    @EnvironmentObject private var state: AppState
    var onPicked: () -> Void = {}

    @State private var users: [RatonUser] = []
    @State private var loading = true
    @State private var errorMessage: String?

    var body: some View {
        List {
            if let errorMessage {
                Section {
                    Text(errorMessage).foregroundStyle(.red)
                    Button("Réessayer") { Task { await load() } }
                    Button("Changer de serveur", role: .destructive) { state.forgetServer() }
                }
            }
            ForEach(users) { user in
                Button {
                    state.setUser(user.id)
                    onPicked()
                } label: {
                    HStack {
                        Text(user.name)
                        Spacer()
                        if user.id == state.userID {
                            Image(systemName: "checkmark").foregroundStyle(.tint)
                        }
                    }
                }
                .foregroundStyle(.primary)
            }
        }
        .overlay { if loading && users.isEmpty { ProgressView() } }
        .task { await load() }
    }

    private func load() async {
        guard let api = state.api else { return }
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            users = try await api.users().users
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
