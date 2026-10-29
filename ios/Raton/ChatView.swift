import SwiftUI

/// The library chat (`/api/chat`): a discussion with Raton about the whole library. A question is
/// queued as a job and polled until the answer is written.
struct ChatView: View {
    var initialQuestion = ""
    @EnvironmentObject private var state: AppState
    @State private var chat: LibraryChat?
    @State private var question = ""
    @State private var pending: String?
    @State private var errorMessage: String?
    @State private var started = false

    var body: some View {
        Group {
            if let api = state.api {
                VStack(spacing: 0) {
                    PageHeader(title: "Discussion", back: true) {
                        Menu {
                            Button { Task { await open(api, nil) } } label: { Label("Nouvelle discussion", systemImage: "plus") }
                            ForEach(chat?.conversations ?? []) { conversation in
                                Button(conversation.title) { Task { await open(api, conversation.id) } }
                            }
                            if let id = chat?.conversationId {
                                Button(role: .destructive) { Task { await remove(api, id) } } label: {
                                    Label("Supprimer cette discussion", systemImage: "trash")
                                }
                            }
                        } label: { Image(systemName: "bubble.left.and.bubble.right") }
                        .buttonStyle(CircleButtonStyle())
                        .accessibilityLabel("Discussions")
                    }
                    ScrollViewReader { proxy in
                        ScrollView {
                            VStack(alignment: .leading, spacing: 12) {
                                ForEach(Array((chat?.messages ?? []).enumerated()), id: \.offset) { _, message in
                                    bubble(message)
                                }
                                if let pending {
                                    bubble(LibraryChatMessage(role: "user", content: pending, citations: []))
                                    Text("Raton réfléchit…").font(.raton(14)).foregroundStyle(Theme.textMuted)
                                }
                                ErrorMessage(text: errorMessage)
                                Color.clear.frame(height: 1).id("end")
                            }
                            .padding(16)
                        }
                        .onChange(of: chat?.messages.count) { _ in proxy.scrollTo("end") }
                        .onChange(of: pending) { _ in proxy.scrollTo("end") }
                    }
                    HStack {
                        TextField("Pose une question à ta bibliothèque", text: $question, axis: .vertical)
                            .font(.raton(16))
                            .padding(.horizontal, 14).padding(.vertical, 10)
                            .surface(in: Capsule())
                        Button {
                            let asked = question
                            question = ""
                            Task { await ask(api, asked) }
                        } label: {
                            Image(systemName: "arrow.up.circle.fill").font(.system(size: 32)).foregroundStyle(Theme.primary)
                        }
                        .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty || pending != nil)
                    }
                    .padding(.horizontal, 16).padding(.bottom, 8)
                }
                .task {
                    guard !started else { return }
                    started = true
                    chat = try? await api.get("/api/chat")
                    if !initialQuestion.isEmpty { await ask(api, initialQuestion) }
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    @ViewBuilder
    private func bubble(_ message: LibraryChatMessage) -> some View {
        let mine = message.role == "user"
        VStack(alignment: .leading, spacing: 6) {
            Text(message.content)
                .font(.raton(15)).foregroundStyle(mine ? .white : Theme.text)
            // Sources of the answer: tapping one opens its fiche.
            ForEach(message.citations, id: \.videoId) { citation in
                NavigationLink(value: citation.videoId) {
                    Label(citation.title, systemImage: "play.rectangle")
                        .font(.raton(13, .semibold)).foregroundStyle(Theme.primary).lineLimit(2)
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 14).fill(mine ? Theme.primary : Color.white))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(mine ? Color.clear : Theme.border, lineWidth: 1))
        .frame(maxWidth: .infinity, alignment: mine ? .trailing : .leading)
    }

    private func ask(_ api: RatonAPI, _ text: String) async {
        errorMessage = nil
        pending = text
        do {
            var body: [String: Any] = ["question": text]
            if let id = chat?.conversationId { body["conversation_id"] = id }
            let job: QueuedJob = try await api.post("/api/chat", body: body)
            let done = try await api.waitForLLMJob(job.jobId)
            if let updated = done.libraryChat { chat = updated } else { chat = try? await api.get("/api/chat") }
        } catch {
            errorMessage = error.localizedDescription
        }
        pending = nil
    }

    private func open(_ api: RatonAPI, _ id: Int?) async {
        if let id {
            chat = try? await api.get("/api/chat/conversations/\(id)")
        } else {
            chat = try? await api.get("/api/chat")
            if let current = chat, current.conversationId != nil {
                chat = LibraryChat(conversationId: nil, title: nil, messages: [], conversations: current.conversations)
            }
        }
    }

    private func remove(_ api: RatonAPI, _ id: Int) async {
        try? await api.delete("/api/chat/conversations/\(id)")
        chat = try? await api.get("/api/chat")
    }
}
