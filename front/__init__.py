"""The HTML front of Raton: Jinja pages rendered from the back's `/api`, and nothing else.

It never imports the back (`back/`): every read and write is an HTTP call to `/api`
(`front/api.py`), and the browser's own `/api` calls go through `front/proxy.py`, so the pages
and the API share one origin. Another front (a SPA, a native app, an MCP server) is built the
same way. Spec: docs/spec/03-architecture.md.
"""
