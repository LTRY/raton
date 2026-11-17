import SwiftUI

/// The short message of an action that failed where the screen has no place of its own for an error
/// (a cloche or a star in a list, a tile's menu): shown a few seconds above the tab bar.
@MainActor
final class Toasts: ObservableObject {
    static let shared = Toasts()
    @Published private(set) var message: String?
    private var hiding: Task<Void, Never>?

    func show(_ text: String) {
        message = text
        AccessibilityNotification.Announcement(text).post()
        hiding?.cancel()
        hiding = Task {
            try? await Task.sleep(for: .seconds(4))
            if !Task.isCancelled { message = nil }
        }
    }

    /// Shows the French message of a failed call; a call cancelled because its page was left says nothing.
    func show(_ error: Error) {
        if !Task.isCancelled { show(error.localizedDescription) }
    }
}

struct ToastView: View {
    @ObservedObject private var toasts = Toasts.shared

    var body: some View {
        if let message = toasts.message {
            Text(message).font(.raton(14, .semibold)).foregroundStyle(.white)
                .multilineTextAlignment(.leading)
                .padding(.horizontal, 16).padding(.vertical, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Theme.danger))
                .shadow(color: Theme.shadow.opacity(0.18), radius: 12, y: 6)
                .padding(.horizontal, TabPill.margin)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .accessibilityAddTraits(.isStaticText)
        }
    }
}
