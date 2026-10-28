import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        Form {
            Section("Serveur") {
                NavigationLink {
                    ServerURLView(onSaved: {})
                        .navigationTitle("Serveur")
                        .navigationBarTitleDisplayMode(.inline)
                } label: {
                    VStack(alignment: .leading) {
                        Text("Adresse du serveur")
                        Text(state.serverURL?.absoluteString ?? "")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Section("Utilisateur") {
                NavigationLink("Changer d'utilisateur") {
                    UserPickerView()
                        .navigationTitle("Utilisateur")
                        .navigationBarTitleDisplayMode(.inline)
                }
            }
        }
        .navigationTitle("Réglages")
    }
}
