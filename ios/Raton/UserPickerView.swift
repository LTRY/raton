import SwiftUI

/// Picks the user the app acts for (`GET /api/users`); also reachable from Réglages.
struct UserPickerView: View {
    @EnvironmentObject private var state: AppState
    let title: String
    var back = false
    // Réglages: also create, rename and delete users.
    var manage = false

    @State private var users: [RatonUser] = []
    @State private var loading = true
    @State private var errorMessage: String?
    @State private var showNew = false
    @State private var deleting: RatonUser?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                PageHeader(title: title, back: back) {
                    if manage {
                        Button { showNew = true } label: { Image(systemName: "plus") }
                            .buttonStyle(CircleButtonStyle())
                            .accessibilityLabel("Nouvel utilisateur")
                    }
                }
                if let errorMessage {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(errorMessage).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
                        Button("Réessayer") { Task { await load() } }
                            .buttonStyle(PillButtonStyle())
                        Button("Changer de serveur") { state.forgetServer() }
                            .font(.raton(15, .medium)).foregroundStyle(Theme.textMuted)
                    }
                    .padding(16)
                }
                ForEach(users) { user in
                    Button {
                        state.setUser(user.id)
                    } label: {
                        HStack {
                            Text(user.name).font(.raton(17, .semibold)).foregroundStyle(Theme.text)
                            Spacer()
                            if user.id == state.userID {
                                Image(systemName: "checkmark").foregroundStyle(Theme.primary)
                            }
                        }
                        .padding(.horizontal, 16).padding(.vertical, 18)
                        .background(Color.white)
                        .overlay(alignment: .bottom) { Theme.border.frame(height: 1) }
                    }
                    .contextMenu {
                        if manage {
                            Button(role: .destructive) { deleting = user } label: { Label("Supprimer", systemImage: "trash") }
                        }
                    }
                }
                if loading && users.isEmpty { ProgressView().frame(maxWidth: .infinity).padding(.top, 40) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
        .task { await load() }
        .sheet(isPresented: $showNew) {
            if let api = state.api {
                TextPromptSheet(title: "Nouvel utilisateur", placeholder: "Nom", action: "Créer") { name in
                    let _: RatonUser = try await api.post("/api/users", body: ["name": name])
                    await load()
                }
            }
        }
        .confirmationDialog("Supprimer cet utilisateur et ses données ?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Supprimer", role: .destructive) {
                if let user = deleting, let api = state.api {
                    Task {
                        do { try await api.delete("/api/users/\(user.id)") } catch { errorMessage = error.localizedDescription }
                        await load()
                    }
                }
            }
        }
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
