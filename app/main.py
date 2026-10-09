import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
VAPI_SECRET = os.getenv("VAPI_SECRET", "")
VAPI_API_KEY = os.getenv("VAPI_API_KEY") or os.getenv("VAPI_PRIVATE_KEY", "")
VAPI_BASE_URL = os.getenv("VAPI_BASE_URL", "https://api.vapi.ai").rstrip("/")

# Only expose resources that are part of the Vapi API. This prevents the proxy
# from becoming an arbitrary URL forwarding endpoint.
VAPI_RESOURCES = {
    "assistants": "assistant",
    "calls": "call",
    "phone-numbers": "phone-number",
    "tools": "tool",
    "squads": "squad",
    "files": "file",
    "knowledge-bases": "knowledge-base",
    "providers": "provider",
}

@app.get("/health")
def health():
    return {"ok": True}


def require_vapi_api_key() -> str:
    if not VAPI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="VAPI_API_KEY is not configured on the server",
        )
    return VAPI_API_KEY


async def read_json_body(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    if not raw_body:
        return {}

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    return body


async def forward_to_vapi(
    request: Request,
    upstream_path: str,
    *,
    method: str | None = None,
) -> Response:
    api_key = require_vapi_api_key()
    body = await read_json_body(request) if request.method in {"POST", "PATCH", "PUT"} else None
    upstream_method = method or request.method

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(base_url=VAPI_BASE_URL, timeout=30.0) as client:
            upstream_response = await client.request(
                upstream_method,
                upstream_path,
                params=list(request.query_params.multi_items()),
                json=body,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Vapi request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Unable to connect to Vapi") from exc

    content_type = upstream_response.headers.get("content-type", "")
    if not upstream_response.content:
        return Response(status_code=upstream_response.status_code)
    if "application/json" in content_type:
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            media_type="application/json",
        )
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=content_type or None,
    )


@app.api_route(
    "/api/{resource}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    tags=["Vapi proxy"],
)
async def vapi_collection(resource: str, request: Request) -> Response:
    upstream_resource = VAPI_RESOURCES.get(resource)
    if upstream_resource is None:
        raise HTTPException(status_code=404, detail=f"Unsupported Vapi resource: {resource}")
    return await forward_to_vapi(request, f"/{upstream_resource}")


@app.api_route(
    "/api/{resource}/{resource_id}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    tags=["Vapi proxy"],
)
async def vapi_resource(resource: str, resource_id: str, request: Request) -> Response:
    upstream_resource = VAPI_RESOURCES.get(resource)
    if upstream_resource is None:
        raise HTTPException(status_code=404, detail=f"Unsupported Vapi resource: {resource}")
    return await forward_to_vapi(request, f"/{upstream_resource}/{resource_id}")


@app.api_route(
    "/assistant",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    tags=["Vapi proxy"],
)
async def assistant_collection(request: Request) -> Response:
    return await forward_to_vapi(request, "/assistant")


@app.api_route(
    "/assistant/{assistant_id}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    tags=["Vapi proxy"],
)
async def assistant_resource(assistant_id: str, request: Request) -> Response:
    return await forward_to_vapi(request, f"/assistant/{assistant_id}")


@app.api_route(
    "/call",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    tags=["Vapi proxy"],
)
async def call_collection(request: Request) -> Response:
    return await forward_to_vapi(request, "/call")


@app.api_route(
    "/call/{call_id}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    tags=["Vapi proxy"],
)
async def call_resource(call_id: str, request: Request) -> Response:
    return await forward_to_vapi(request, f"/call/{call_id}")


@app.post("/vapi/tools")
async def vapi_tools(
    request: Request,
    x_vapi_secret: str | None = Header(None),
    authorization: str | None = Header(None),
):
    bearer_secret = None
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer":
            bearer_secret = credentials.strip()

    if VAPI_SECRET and x_vapi_secret != VAPI_SECRET and bearer_secret != VAPI_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    message = body.get("message", {})
    if message.get("type") != "tool-calls":
        return {}

    results = []
    for call in message.get("toolCallList", []):
        fn = call.get("function", {})
        name = fn.get("name") or call.get("name")
        args = fn.get("arguments") or call.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args)

        if name == "save_lead":
            print("NEW LEAD:", args, flush=True)
            result = f"Saved lead {args.get('name')} from {args.get('company')}."
        else:
            result = f"Unknown tool: {name}"

        results.append({"toolCallId": call["id"], "result": result})

    return {"results": results}
