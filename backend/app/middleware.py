"""Identifiants de requete et corps multipart borne avant analyse."""

from uuid import uuid4

from starlette.responses import JSONResponse


class RequestMiddleware:
    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def identified_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode("ascii")))
            await send(message)

        if scope["method"] == "POST" and scope["path"] in ("/predict", "/predict/visualize"):
            # Borne egalement les requetes sans Content-Length et les uploads avant spooling.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.max_body_bytes:
                    response = JSONResponse(status_code=413, content={"code": "request_too_large",
                                            "message": "La requete depasse la taille autorisee.", "request_id": request_id})
                    await response(scope, receive, identified_send)
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            original_receive = receive
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = replay
        await self.app(scope, receive, identified_send)
