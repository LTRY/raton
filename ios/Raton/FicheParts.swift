import SwiftUI

// The panels under a fiche's player, the category chips and the sheets (categories, playlists).

/// Minimal Markdown for the notes the LLM writes: headings, bullets, and inline styles.
struct MarkdownText: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { _, line in
                if line.hasPrefix("#") {
                    Text(inline(line.drop(while: { $0 == "#" || $0 == " " })))
                        .font(.raton(18, .bold)).foregroundStyle(Theme.text).padding(.top, 8)
                } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                    HStack(alignment: .top, spacing: 8) {
                        Text("•")
                        Text(inline(line.dropFirst(2)))
                    }
                    .font(.raton(15)).foregroundStyle(Theme.textSoft)
                } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(inline(Substring(line))).font(.raton(15)).foregroundStyle(Theme.textSoft)
                }
            }
        }
    }

    private func inline(_ text: Substring) -> AttributedString {
        (try? AttributedString(
            markdown: String(text),
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(String(text))
    }
}

/// Colored category labels; the colors come from `GET /api/categories`.
struct CategoryChips: View {
    let categories: [String]
    let api: RatonAPI
    @State private var styles: [CategoryStyle] = []

    var body: some View {
        HStack(spacing: 6) {
            ForEach(categories, id: \.self) { label in
                let color = styles.first { $0.label == label }.map { Color(hexString: $0.color) } ?? Theme.textMuted
                Text(label)
                    .font(.raton(9, .semibold)).foregroundStyle(color)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(Capsule().fill(color.opacity(0.12)))
            }
        }
        .task { styles = (try? await api.get("/api/categories")) ?? [] }
    }
}

/// Pick the categories of a fiche (or a channel, a playlist) among the user's labels.
struct CategoryPickerSheet: View {
    let api: RatonAPI
    @State var selected: [String]
    let onSave: ([String]) async -> Void
    @State private var styles: [CategoryStyle] = []
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(styles, id: \.label) { style in
                        Button {
                            if let index = selected.firstIndex(of: style.label) {
                                selected.remove(at: index)
                            } else {
                                selected.append(style.label)
                            }
                        } label: {
                            ListRow {
                                HStack {
                                    Circle().fill(Color(hexString: style.color)).frame(width: 12, height: 12)
                                    Text(style.label).font(.raton(17, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    if selected.contains(style.label) {
                                        Image(systemName: "checkmark").foregroundStyle(Theme.primary)
                                    }
                                }
                            }
                        }
                    }
                    if styles.isEmpty {
                        EmptyMessage(text: "Aucune catégorie. Elles se créent dans les paramètres de Raton.")
                    }
                }
            }
            .ratonPage()
            .navigationTitle("Catégories")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Enregistrer") {
                        Task {
                            await onSave(selected)
                            dismiss()
                        }
                    }
                }
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } }
            }
        }
        .task { styles = (try? await api.get("/api/categories")) ?? [] }
    }
}

/// Add the fiche to a playlist, remove it from one, or start a new playlist with it.
struct PlaylistsSheet: View {
    let api: RatonAPI
    let detail: VideoDetail
    let onChange: () async -> Void
    @State private var playlists: [PlaylistSummary] = []
    @State private var memberships: [VideoPlaylistRef] = []
    @State private var newTitle = ""
    @State private var errorMessage: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ErrorMessage(text: errorMessage)
                    ForEach(playlists) { playlist in
                        let member = memberships.first { $0.playlistId == playlist.id }
                        Button { Task { await toggle(playlist, member) } } label: {
                            ListRow {
                                HStack {
                                    Text(playlist.title).font(.raton(17, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    Image(systemName: member == nil ? "plus.circle" : "checkmark.circle.fill")
                                        .foregroundStyle(member == nil ? Theme.textMuted : Theme.primary)
                                }
                            }
                        }
                    }
                    HStack {
                        TextField("Nouvelle playlist", text: $newTitle).font(.raton(17))
                        Button("Créer") { Task { await create() } }
                            .disabled(newTitle.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                    .padding(16)
                }
            }
            .ratonPage()
            .navigationTitle("Playlists")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Fermer") { dismiss() } } }
        }
        .task { await load() }
    }

    private func load() async {
        do {
            playlists = try await api.get("/api/playlists")
            let fresh: VideoDetail = try await api.get("/api/videos/\(detail.id)")
            memberships = fresh.playlists
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func toggle(_ playlist: PlaylistSummary, _ member: VideoPlaylistRef?) async {
        do {
            if let member {
                try await api.delete("/api/playlists/\(playlist.id)/items/\(member.itemId)")
            } else {
                let _: PlaylistDetail = try await api.post(
                    "/api/playlists/\(playlist.id)/items", body: ["video_id": detail.id])
            }
            await load()
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func create() async {
        do {
            let created: PlaylistSummary = try await api.post(
                "/api/playlists", body: ["title": newTitle])
            let _: PlaylistDetail = try await api.post(
                "/api/playlists/\(created.id)/items", body: ["video_id": detail.id])
            newTitle = ""
            await load()
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: Panels

/// A section behind a title with a chevron, closed until tapped.
struct Collapsible<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() }
            } label: {
                HStack {
                    Text(title).font(.raton(18, .bold)).foregroundStyle(Theme.text)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.down").font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Theme.textMuted)
                        .rotationEffect(.degrees(expanded ? 180 : 0))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(expanded ? "Dépliée" : "Repliée")
            if expanded { content() }
        }
    }
}

struct InfoPanel: View {
    let detail: VideoDetail
    let seek: (Double) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Collapsible(title: "Description") {
                VStack(alignment: .leading, spacing: 10) {
                    Text(detail.metadata.description ?? "Pas de description.")
                        .font(.raton(15)).foregroundStyle(Theme.textSoft)
                    if !detail.metadata.tags.isEmpty {
                        Text(detail.metadata.tags.map { "#\($0)" }.joined(separator: " "))
                            .font(.raton(13)).foregroundStyle(Theme.textMuted)
                    }
                    if !detail.metadata.chapters.isEmpty {
                        Text("Chapitres").font(.raton(16, .bold)).foregroundStyle(Theme.text).padding(.top, 4)
                        ForEach(Array(detail.metadata.chapters.enumerated()), id: \.offset) { _, chapter in
                            Button {
                                if let start = chapter.startSeconds { seek(start) }
                            } label: {
                                HStack {
                                    Text(Format.clock(chapter.startSeconds ?? 0)).monospacedDigit()
                                        .foregroundStyle(Theme.primary)
                                    Text(chapter.title).foregroundStyle(Theme.textSoft)
                                    Spacer(minLength: 0)
                                }
                                .font(.raton(15))
                            }
                        }
                    }
                }
            }
            if !detail.playlists.isEmpty {
                Text("Playlists : " + detail.playlists.map(\.title).joined(separator: ", "))
                    .font(.raton(14)).foregroundStyle(Theme.textMuted)
            }
        }
    }
}

struct NotesPanel: View {
    let detail: VideoDetail
    let generating: Bool
    let generate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let summary = detail.documents.shortSummary {
                Text(summary).font(.raton(16, .semibold)).foregroundStyle(Theme.text)
            }
            if let notes = detail.documents.notes {
                MarkdownText(text: notes)
            }
            Button(generating ? "Génération…" : "Régénérer les notes", action: generate)
                .buttonStyle(SandButtonStyle())
                .disabled(generating || !detail.hasTranscript)
        }
    }
}

struct CommentPanel: View {
    let initial: String
    let save: (String) async -> Void
    @State private var text = ""
    @State private var saving = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextEditor(text: $text)
                .font(.raton(16))
                .frame(minHeight: 140)
                .scrollContentBackground(.hidden)
                .padding(10)
                .surfaceCard(radius: 10)
            Button(saving ? "Enregistrement…" : "Enregistrer") {
                saving = true
                Task {
                    await save(text)
                    saving = false
                }
            }
            .buttonStyle(SandButtonStyle(active: text != initial))
            .disabled(saving || text == initial)
        }
        .onAppear { text = initial }
    }
}

/// The discussion about one fiche (`POST /api/videos/{id}/chat`, then the job is polled).
struct ChatPanel: View {
    let api: RatonAPI
    let detail: VideoDetail
    let onChange: () async -> Void
    @State private var question = ""
    @State private var pending: String?
    @State private var errorMessage: String?

    @FocusState private var focused: Bool

    private var messages: [ChatMessage] { detail.documents.chatMessages }
    private var canSend: Bool { !question.trimmingCharacters(in: .whitespaces).isEmpty && pending == nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            ForEach(Array(messages.enumerated()), id: \.offset) { _, message in
                if message.role == "user" { userMessage(message.content) } else { reply(message.content) }
            }
            if let pending {
                userMessage(pending)
                Spark(thinking: true)
            }
            ErrorMessage(text: errorMessage)
            if messages.isEmpty && pending == nil && !detail.documents.suggestedQuestions.isEmpty {
                suggestions
            }
            composer
            if !messages.isEmpty {
                Button { Task { await clear() } } label: {
                    Label("Effacer la conversation", systemImage: "trash").font(.raton(13, .semibold))
                        .foregroundStyle(Theme.textMuted)
                }
            }
        }
        .animation(.easeOut(duration: 0.2), value: messages.count)
    }

    /// The user's message: a soft sand bubble on the right, like the Claude app.
    private func userMessage(_ text: String) -> some View {
        Text(text)
            .font(.raton(16)).foregroundStyle(Theme.text)
            .padding(.horizontal, 16).padding(.vertical, 11)
            .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.surfaceMuted))
            .padding(.leading, 56)
            .frame(maxWidth: .infinity, alignment: .trailing)
    }

    /// Raton's answer: plain text on the page, no bubble, with the little spark under it.
    private func reply(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(text)
                .font(.raton(16)).lineSpacing(5).foregroundStyle(Theme.text)
                .textSelection(.enabled)
            Spark(thinking: false)
        }
    }

    private var suggestions: some View {
        FlowLayout(spacing: 8) {
            ForEach(detail.documents.suggestedQuestions, id: \.self) { suggestion in
                Button { Task { await ask(suggestion) } } label: {
                    Text(suggestion).font(.raton(14, .medium)).foregroundStyle(Theme.textSoft)
                        .multilineTextAlignment(.leading)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .overlay(Capsule().stroke(Theme.borderStrong, lineWidth: 1))
                }
                .buttonStyle(.plain)
            }
        }
    }

    /// One line: the field and the round send button inside a white capsule. Return sends too.
    private var composer: some View {
        HStack(spacing: 8) {
            TextField("Poser une question à Raton", text: $question)
                .font(.raton(17)).focused($focused)
                .submitLabel(.send)
                .onSubmit(send)
                .padding(.leading, 8)
            Button(action: send) {
                Image(systemName: "arrow.up").font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(canSend ? Theme.primary : Theme.textFaint.opacity(0.7)))
            }
            .disabled(!canSend)
            .accessibilityLabel("Envoyer")
        }
        .padding(.leading, 12).padding(.trailing, 9).frame(height: 54)
        // Frosted glass like the tab bar: blur, a white veil and a bright rim, lit from the top.
        .background(.ultraThinMaterial, in: Capsule())
        .background(Capsule().fill(Color.white.opacity(0.55)))
        .overlay(
            Capsule().stroke(
                LinearGradient(colors: [Color.white.opacity(0.95), Color.white.opacity(0.25)],
                               startPoint: .top, endPoint: .bottom), lineWidth: 1.2)
        )
        .overlay(Capsule().stroke(Theme.border.opacity(0.7), lineWidth: 0.5).padding(-0.5))
        .shadow(color: Theme.shadow.opacity(0.12), radius: 18, y: 8)
        .id("chat-composer")
    }

    private func send() {
        guard canSend else { return }
        let asked = question
        question = ""
        // The keyboard goes away with the question: the answer is read, not typed over.
        focused = false
        Task { await ask(asked) }
    }

    private func ask(_ text: String) async {
        errorMessage = nil
        pending = text
        do {
            let job: QueuedJob = try await api.post("/api/videos/\(detail.id)/chat", body: ["question": text])
            _ = try await api.waitForLLMJob(job.jobId)
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
        pending = nil
    }

    private func clear() async {
        do {
            try await api.delete("/api/videos/\(detail.id)/chat")
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

/// Raton's mark under an answer; it turns slowly while an answer is being written.
private struct Spark: View {
    let thinking: Bool
    @State private var turning = false

    var body: some View {
        Image(systemName: "sparkle").font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.primary)
            .rotationEffect(.degrees(turning ? 360 : 0))
            .scaleEffect(thinking && turning ? 1.15 : 1)
            .onAppear {
                guard thinking else { return }
                withAnimation(.linear(duration: 2.4).repeatForever(autoreverses: false)) { turning = true }
            }
    }
}
