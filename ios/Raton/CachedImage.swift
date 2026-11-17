import SwiftUI

/// The pictures already decoded, kept in memory: a row that scrolls back on screen draws its picture
/// at once instead of loading it again. The files themselves are in the system's HTTP cache, which
/// follows the `Cache-Control` the back sends.
enum ImageCache {
    private static let cache: NSCache<NSURL, UIImage> = {
        let cache = NSCache<NSURL, UIImage>()
        cache.totalCostLimit = 64 * 1024 * 1024
        return cache
    }()

    static func image(_ url: URL) -> UIImage? { cache.object(forKey: url as NSURL) }

    static func load(_ url: URL) async -> UIImage? {
        if let known = image(url) { return known }
        guard let (data, response) = try? await URLSession.shared.data(from: url),
              (response as? HTTPURLResponse)?.statusCode ?? 200 < 400,
              let decoded = UIImage(data: data) else { return nil }
        // Decoded here, off the main thread, so the first draw does not stall the scroll.
        let ready = await decoded.byPreparingForDisplay() ?? decoded
        let pixels = Int(ready.size.width * ready.scale * ready.size.height * ready.scale)
        cache.setObject(ready, forKey: url as NSURL, cost: pixels * 4)
        return ready
    }
}

/// `AsyncImage` with the memory cache above: same two closures, the picture and what stands in for it.
struct CachedImage<Content: View, Placeholder: View>: View {
    let url: URL?
    @ViewBuilder let content: (Image) -> Content
    @ViewBuilder let placeholder: () -> Placeholder
    @State private var loaded: (url: URL, image: UIImage)?

    /// The picture of the current URL: the one loaded, or the one the cache already has.
    private var image: UIImage? {
        guard let url else { return nil }
        if let loaded, loaded.url == url { return loaded.image }
        return ImageCache.image(url)
    }

    var body: some View {
        Group {
            if let image { content(Image(uiImage: image)) } else { placeholder() }
        }
        .task(id: url) {
            guard let url, image == nil, let fresh = await ImageCache.load(url) else { return }
            loaded = (url, fresh)
        }
    }
}
