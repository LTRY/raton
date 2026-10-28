import SwiftUI

/// The server URL form: first launch, and Réglages. The URL is validated by `GET {url}/api/users`
/// before it is stored.
struct ServerURLView: View {
    @EnvironmentObject private var state: AppState
    let title: String
    var back = false
    let onSaved: () -> Void

    @State private var text = ""
    @State private var checking = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                PageHeader(title: title, back: back).padding(.horizontal, -16)
                if !back, let mascot = UIImage(named: "raccoon-empty") {
                    Image(uiImage: mascot)
                        .resizable().scaledToFit()
                        .frame(height: 200)
                        .frame(maxWidth: .infinity)
                }
                Text("Adresse du serveur Raton")
                    .font(.raton(15, .semibold)).foregroundStyle(Theme.textSoft)
                TextField("http://192.168.1.20:8000", text: $text)
                    .font(.raton(17))
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .onSubmit { Task { await connect() } }
                    .padding(.horizontal, 18).padding(.vertical, 14)
                    .background(Capsule().fill(Color.white))
                    .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
                Text("L'adresse de la page Raton ouverte dans le navigateur, avec son port.")
                    .font(.raton(14)).foregroundStyle(Theme.textMuted)
                if let errorMessage {
                    Text(errorMessage).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
                }
                Button {
                    Task { await connect() }
                } label: {
                    if checking { ProgressView() } else { Text("Se connecter") }
                }
                .buttonStyle(PillButtonStyle())
                .disabled(checking || text.trimmingCharacters(in: .whitespaces).isEmpty)
                .frame(maxWidth: .infinity)
                .padding(.top, 8)
            }
            .padding(.horizontal, 16)
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
        .onAppear {
            if text.isEmpty { text = state.serverURL?.absoluteString ?? "" }
        }
    }

    private func connect() async {
        errorMessage = nil
        guard let url = RatonAPI.parseServerURL(text) else {
            errorMessage = "Adresse invalide. Exemple : http://192.168.1.20:8000"
            return
        }
        checking = true
        defer { checking = false }
        do {
            _ = try await RatonAPI.checkServer(url)
            state.setServer(url)
            onSaved()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
