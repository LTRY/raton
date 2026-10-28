import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                PageHeader(title: "Réglages")
                NavigationLink {
                    ServerURLView(title: "Serveur", back: true, onSaved: {})
                } label: {
                    row("Adresse du serveur", detail: state.serverURL?.absoluteString)
                }
                NavigationLink {
                    UserPickerView(title: "Utilisateur", back: true)
                } label: {
                    row("Changer d'utilisateur", detail: nil)
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private func row(_ title: String, detail: String?) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.raton(17, .semibold)).foregroundStyle(Theme.text)
                if let detail {
                    Text(detail).font(.raton(14)).foregroundStyle(Theme.textMuted)
                }
            }
            Spacer()
            Image(systemName: "chevron.right").font(.system(size: 14)).foregroundStyle(Theme.textFaint)
        }
        .padding(.horizontal, 16).padding(.vertical, 16)
        .background(Color.white)
        .overlay(alignment: .bottom) { Theme.border.frame(height: 1) }
    }
}
