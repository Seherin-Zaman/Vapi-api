import os, json
from fastapi import FastAPI, Request, Header, HTTPException

app = FastAPI()
VAPI_SECRET = os.getenv("VAPI_SECRET", "")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/vapi/tools")
async def vapi_tools(request: Request, x_vapi_secret: str | None = Header(None)):
    if VAPI_SECRET and x_vapi_secret != VAPI_SECRET:
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
