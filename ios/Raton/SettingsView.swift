import SwiftUI

/// The user's own settings (the web shows only these on a phone): name, users, screen time,
/// couvre-feu, how Raton speaks, and the server this app talks to.
struct SettingsView: View {
    @EnvironmentObject private var state: AppState
    @State private var users: [RatonUser] = []
    @State private var name = ""
    @State private var settings: UserSettings?
    @State private var screenTime: ScreenTimeReply?
    @State private var dailyMinutes: [String: Int] = [:]
    @State private var curfewOn = false
    @State private var curfewStart = Date()
    @State private var curfewEnd = Date()
    @State private var address = "vous"
    @State private var nickname = ""
    @State private var notice: String?
    @State private var errorMessage: String?

    private static let kinds = [("video", "Vidéos"), ("short", "Shorts"), ("podcast", "Podcasts"), ("music", "Musique")]

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        PageHeader(title: "Paramètres")
                        HStack(spacing: 12) {
                            AvatarView(path: nil, name: currentName, api: api, size: 52)
                            Text(currentName).font(.raton(22, .bold)).foregroundStyle(Theme.text)
                        }
                        .padding(.horizontal, 16)
                        ErrorMessage(text: errorMessage)
                        if let notice { Text(notice).font(.raton(14, .medium)).foregroundStyle(Theme.textSoft).padding(.horizontal, 16) }
                        card("Nom") {
                            HStack(spacing: 10) {
                                TextField("Nom", text: $name).font(.raton(17)).webField()
                                Button("Renommer") { Task { await rename(api) } }
                                    .buttonStyle(SandButtonStyle(fill: false))
                                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || name == currentName)
                            }
                        }
                        card("Écoute hors ligne") {
                            NavigationLink { OfflineView() } label: {
                                HStack {
                                    Text("Audios sur ce téléphone").font(.raton(16, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    Image(systemName: "chevron.right").foregroundStyle(Theme.textFaint)
                                }
                            }
                        }
                        card("Changer d'utilisateur") {
                            NavigationLink {
                                UserPickerView(title: "Utilisateurs", back: true, manage: true)
                            } label: {
                                HStack {
                                    Text("Changer d'utilisateur").font(.raton(16, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    Image(systemName: "chevron.right").foregroundStyle(Theme.textFaint)
                                }
                            }
                        }
                        if settings != nil {
                            card("Temps d'écran (minutes par jour)") {
                                ForEach(Self.kinds, id: \.0) { kind in
                                    Stepper(value: Binding(get: { dailyMinutes[kind.0] ?? 1 }, set: { dailyMinutes[kind.0] = $0 }),
                                            in: 1...1440, step: 5) {
                                        HStack {
                                            Text(kind.1).font(.raton(16, .semibold))
                                            Spacer()
                                            Text("\(dailyMinutes[kind.0] ?? 1) min").font(.raton(15)).foregroundStyle(Theme.textMuted)
                                        }
                                    }
                                }
                                usage
                                Button("Enregistrer") {
                                    Task { await save(api, ["screen_time_today_minutes": dailyMinutes]) }
                                }
                                .buttonStyle(SandButtonStyle(fill: false))
                            }
                            card("Couvre-feu") {
                                Toggle("Activer le couvre-feu", isOn: $curfewOn).font(.raton(16, .semibold)).tint(Theme.primary)
                                DatePicker("De", selection: $curfewStart, displayedComponents: .hourAndMinute)
                                DatePicker("à", selection: $curfewEnd, displayedComponents: .hourAndMinute)
                                Button("Enregistrer") {
                                    Task {
                                        await save(api, ["curfew_enabled": curfewOn,
                                                         "curfew_start": Self.time(curfewStart),
                                                         "curfew_end": Self.time(curfewEnd)])
                                    }
                                }
                                .buttonStyle(SandButtonStyle(fill: false))
                            }
                            card("Raton et toi") {
                                Picker("", selection: $address) {
                                    Text("Vous").tag("vous")
                                    Text("Tu").tag("tu")
                                }
                                .pickerStyle(.segmented)
                                TextField("Comment il t'appelle", text: $nickname).font(.raton(17)).webField()
                                Button("Enregistrer") {
                                    Task { await save(api, ["raton_address": address, "raton_nickname": nickname]) }
                                }
                                .buttonStyle(SandButtonStyle(fill: false))
                            }
                        }
                        card("Serveur") {
                            NavigationLink {
                                ServerURLView(title: "Serveur", back: true, onSaved: {})
                            } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Adresse du serveur").font(.raton(16, .semibold)).foregroundStyle(Theme.text)
                                    Text(state.serverURL?.absoluteString ?? "").font(.raton(14)).foregroundStyle(Theme.textMuted)
                                }
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .task { await load(api) }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private var currentName: String { users.first { $0.id == state.userID }?.name ?? "" }

    /// What the user has watched against the limits: the back computes both.
    @ViewBuilder
    private var usage: some View {
        if let screenTime {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Self.kinds, id: \.0) { kind in
                    if let today = screenTime.periods["today"]?[kind.0] {
                        Text("\(kind.1) aujourd'hui : \(Int(today.seconds / 60)) / \(today.limitMinutes) min")
                            .font(.raton(13)).foregroundStyle(Theme.textMuted)
                    }
                }
            }
        }
    }

    private func card<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.raton(19, .bold)).foregroundStyle(Theme.text)
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surfaceCard(radius: 22)
        .padding(.horizontal, 16)
    }

    private static func time(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    private static func parse(_ time: String) -> Date {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.date(from: time) ?? Date()
    }

    private func load(_ api: RatonAPI) async {
        do {
            users = try await api.users().users
            name = currentName
            let loaded: UserSettings = try await api.get("/api/settings")
            settings = loaded
            dailyMinutes = loaded.screenTimeLimits.compactMapValues { $0["today"] }
            curfewOn = loaded.curfew.enabled
            curfewStart = Self.parse(loaded.curfew.start)
            curfewEnd = Self.parse(loaded.curfew.end)
            address = loaded.ratonLanguage.address
            nickname = loaded.ratonLanguage.nickname
            screenTime = try? await api.get("/api/screen-time")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func rename(_ api: RatonAPI) async {
        guard let id = state.userID else { return }
        do {
            let _: RatonUser = try await api.put("/api/users/\(id)", body: ["name": name])
            notice = "Nom enregistré."
            await load(api)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func save(_ api: RatonAPI, _ body: [String: Any]) async {
        errorMessage = nil
        do {
            let reply: UserSettings = try await api.put("/api/settings", body: body)
            settings = reply
            notice = "Réglages enregistrés."
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
