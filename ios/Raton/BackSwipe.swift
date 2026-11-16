import SwiftUI
import UIKit

/// The swipe from the left edge that goes back a page. The pages hide the navigation bar, which
/// switches that gesture off, so the navigation controller is made its delegate again. It never
/// starts over a player: there the finger scrubs a progress bar or slides the video / audio carousel.
enum BackSwipe {
    @MainActor static var zones: [UUID: CGRect] = [:]

    @MainActor static func blocked(at point: CGPoint) -> Bool {
        zones.values.contains { $0.contains(point) }
    }
}

extension UINavigationController: @retroactive UIGestureRecognizerDelegate {
    open override func viewDidLoad() {
        super.viewDidLoad()
        interactivePopGestureRecognizer?.delegate = self
        // Only the edge swipe: a horizontal swipe anywhere in the page must never carry it away.
        if #available(iOS 26, *) { interactiveContentPopGestureRecognizer?.isEnabled = false }
    }

    public func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
        guard gestureRecognizer === interactivePopGestureRecognizer else { return true }
        // Nothing to go back to on a tab's base page.
        guard viewControllers.count > 1 else { return false }
        return !BackSwipe.blocked(at: gestureRecognizer.location(in: nil))
    }
}

private struct BlocksBackSwipe: ViewModifier {
    @State private var id = UUID()

    func body(content: Content) -> some View {
        content
            .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { BackSwipe.zones[id] = $0 }
            .onDisappear { BackSwipe.zones[id] = nil }
    }
}

extension View {
    /// The back swipe does not start over this view (a player, a progress bar).
    func blocksBackSwipe() -> some View { modifier(BlocksBackSwipe()) }
}
