import SwiftUI

/// The server URL form: first launch, and Réglages. The URL is validated by `GET {url}/api/users`
/// before it is stored.
struct ServerURLView: View {
    @EnvironmentObject private var state: AppState
    let onSaved: () -> Void

    @State private var text = ""
    @State private var checking = false
    @State private var errorMessage: String?

    var body: some View {
        Form {
            Section {
                TextField("http://192.168.1.20:8000", text: $text)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .onSubmit { Task { await connect() } }
            } header: {
                Text("Adresse du serveur Raton")
            } footer: {
                Text("L'adresse de la page Raton ouverte dans le navigateur, avec son port.")
            }
            if let errorMessage {
                Section { Text(errorMessage).foregroundStyle(.red) }
            }
            Section {
                Button {
                    Task { await connect() }
                } label: {
                    if checking {
                        ProgressView()
                    } else {
                        Text("Se connecter")
                    }
                }
                .disabled(checking || text.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
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
