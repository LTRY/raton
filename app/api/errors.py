"""One error format for `/api`: `{"detail": "<French message>"}`, validation errors included.

A refused action already answers that way (the route turns the service's exception into an
`HTTPException` carrying its message). FastAPI's own validation errors would answer a list in
English instead: `validation_error_handler` rewrites them, and keeps each field's problem in
`errors`. The HTML routes keep FastAPI's default answer.
"""

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

API_PREFIX = "/api"

# Pydantic error type -> French message; `{name}` is filled from the error's context.
_MESSAGES = {
    "missing": "champ obligatoire",
    "int_parsing": "doit être un nombre entier",
    "int_type": "doit être un nombre entier",
    "int_from_float": "doit être un nombre entier",
    "float_parsing": "doit être un nombre",
    "float_type": "doit être un nombre",
    "bool_parsing": "doit valoir true ou false",
    "bool_type": "doit valoir true ou false",
    "string_type": "doit être du texte",
    "list_type": "doit être une liste",
    "dict_type": "doit être un objet",
    "model_attributes_type": "doit être un objet",
    "json_invalid": "JSON invalide",
    "literal_error": "doit valoir {expected}",
    "enum": "doit valoir {expected}",
    "greater_than_equal": "doit être supérieur ou égal à {ge}",
    "greater_than": "doit être supérieur à {gt}",
    "less_than_equal": "doit être inférieur ou égal à {le}",
    "less_than": "doit être inférieur à {lt}",
}


class FieldErrorRead(BaseModel):
    field: str
    message: str


class ErrorRead(BaseModel):
    """Every `/api` error: `detail` is ready to show; `errors` lists a request's invalid fields."""

    detail: str
    errors: list[FieldErrorRead] | None = None


def _field(location: tuple) -> str:
    # ("body", "state") -> "state": where the field came from is the request's business.
    parts = [str(part) for part in location if part not in ("body", "query", "path")]
    return ".".join(parts) or "requête"


def _message(error: dict) -> str:
    template = _MESSAGES.get(error["type"])
    if template is None:
        return error["msg"]
    try:
        return template.format(**error.get("ctx", {}))
    except KeyError:
        return error["msg"]


async def validation_error_handler(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith(API_PREFIX + "/"):
        return await request_validation_exception_handler(request, exc)
    errors = [
        FieldErrorRead(field=_field(tuple(error["loc"])), message=_message(error))
        for error in exc.errors()
    ]
    detail = "Requête invalide : " + " ; ".join(f"{e.field} : {e.message}" for e in errors) + "."
    return JSONResponse(
        status_code=422,
        content=ErrorRead(detail=detail, errors=errors).model_dump(),
    )


_DESCRIPTIONS = {
    400: "Action refusée",
    404: "Introuvable",
    409: "Conflit avec l'état actuel",
    422: "Requête invalide",
    502: "Service externe en échec",
}


def error_responses(*codes: int) -> dict:
    """The `responses` of a route: each error code it answers, with the `ErrorRead` format."""
    return {code: {"model": ErrorRead, "description": _DESCRIPTIONS[code]} for code in codes}
