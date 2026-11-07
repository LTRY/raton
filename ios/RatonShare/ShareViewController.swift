import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// The "Raton" entry of the share sheet (Safari, the YouTube app): sends the shared YouTube link to the
/// server's `POST /api/videos/share-import`, which imports the fiche and answers when it is done. The
/// server address is the one the app saved in the shared defaults.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        let host = UIHostingController(rootView: ShareView(model: model) { [weak self] in
            self?.extensionContext?.completeRequest(returningItems: nil)
        })
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        Task { await model.send(from: extensionContext?.inputItems as? [NSExtensionItem] ?? []) }
    }
}

@MainActor
final class ShareModel: ObservableObject {
    enum Phase: Equatable { case sending, done, failed(String) }
    @Published var phase = Phase.sending

    private static let group = "group.fr.raton.app"

    func send(from items: [NSExtensionItem]) async {
        guard let server = UserDefaults(suiteName: Self.group)?.string(forKey: "serverURL"),
              let endpoint = URL(string: server + "/api/videos/share-import") else {
            phase = .failed("Ouvrez l'app Raton une fois pour choisir le serveur.")
            return
        }
        guard let link = await sharedLink(in: items) else {
            phase = .failed("Aucun lien à envoyer.")
            return
        }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["url": link])
        // The back waits for the whole import before answering.
        request.timeoutInterval = 300
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            if status == 200 {
                phase = .done
            } else {
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
                phase = .failed(detail ?? "Le serveur a répondu une erreur (HTTP \(status)).")
            }
        } catch {
            phase = .failed("Serveur injoignable.")
        }
    }

    /// The first web link of the shared items; the YouTube app shares text that holds the link.
    private func sharedLink(in items: [NSExtensionItem]) async -> String? {
        for provider in items.flatMap({ $0.attachments ?? [] }) {
            if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
               let value = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier),
               let url = value as? URL {
                return url.absoluteString
            }
            if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
               let value = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier),
               let text = value as? String,
               let link = text.split(whereSeparator: \.isWhitespace).map(String.init).first(where: { $0.hasPrefix("http") }) {
                return link
            }
        }
        return nil
    }
}

struct ShareView: View {
    @ObservedObject var model: ShareModel
    let close: () -> Void

    var body: some View {
        VStack(spacing: 18) {
            switch model.phase {
            case .sending:
                ProgressView()
                Text("Envoi à Raton…").font(.headline)
            case .done:
                Image(systemName: "checkmark.circle.fill").font(.system(size: 44)).foregroundStyle(.green)
                Text("Ajoutée à Raton").font(.headline)
            case .failed(let message):
                Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 40)).foregroundStyle(.orange)
                Text(message).multilineTextAlignment(.center)
            }
            if model.phase != .sending {
                Button("Fermer", action: close).buttonStyle(.borderedProminent)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}
