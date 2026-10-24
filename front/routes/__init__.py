"""The page routers, in resolution order (the first matching path wins)."""

from front.routes import channels, dashboard, playlists, raton, settings, stats, users, videos

ROUTERS = [
    dashboard.router,
    raton.router,
    stats.router,
    settings.router,
    users.router,
    channels.router,
    playlists.router,
    videos.router,
]
