"""The page routers, in resolution order (the first matching path wins)."""

from front.routes import channels, dashboard, playlists, raton, settings, stats, videos

ROUTERS = [
    dashboard.router,
    raton.router,
    stats.router,
    settings.router,
    channels.router,
    playlists.router,
    videos.router,
]
