"""The whole site in-process, as a browser sees it: the front, whose `/api` calls (its own and
the relayed ones) are served by the back app as the test configured it (`get_db` overridden)."""

import httpx
from fastapi import Request
from fastapi.testclient import TestClient

from back.main import app as back_app
from front import proxy
from front.api import Api, get_api
from front.main import app as front_app


def site_client(**kwargs) -> TestClient:
    api = Api(TestClient(back_app))

    def api_for(request: Request) -> Api:
        return api.for_request(request)

    front_app.dependency_overrides[get_api] = api_for
    proxy._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=back_app), base_url="http://testserver"
    )
    return TestClient(front_app, **kwargs)


def reset_site() -> None:
    front_app.dependency_overrides.pop(get_api, None)
    proxy._client = None
