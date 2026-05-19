import asyncio
import hashlib
import json
import os
import threading
import time
from contextlib import asynccontextmanager

import pika
import redis
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "events")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

redis_client = redis.Redis.from_url(REDIS_URL)

ws_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


# ── helpers ──────────────────────────────────────────────────────────────────


def publish_image_uploaded(image_hash: str) -> None:
    event = {"type": "image_uploaded", "hash": image_hash}
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.exchange_declare(
        exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
    )
    channel.basic_publish(
        exchange=RABBITMQ_EXCHANGE,
        routing_key="image_uploaded",
        body=json.dumps(event).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json", delivery_mode=2
        ),
    )
    connection.close()


async def broadcast(event: dict) -> None:
    for ws in list(ws_clients):
        try:
            await ws.send_json(event)
        except Exception:
            ws_clients.discard(ws)


# ── API endpoints ────────────────────────────────────────────────────────────


async def upload_image(request: Request) -> JSONResponse:
    form = await request.form()
    image_file = form.get("image")
    description = form.get("description", "")

    if image_file is None:
        return JSONResponse({"error": "missing image field"}, status_code=400)
    if not description:
        return JSONResponse({"error": "missing description field"}, status_code=400)

    image_bytes = await image_file.read()
    if not image_bytes:
        return JSONResponse({"error": "image file is empty"}, status_code=400)

    image_hash = hashlib.sha256(image_bytes).hexdigest()
    redis_key = f"image:{image_hash}"

    try:
        redis_client.hset(
            redis_key,
            mapping={
                "description": description,
                "image": image_bytes,
                "filename": image_file.filename or "",
                "content_type": image_file.content_type or "",
                "ocr_results": "",
            },
        )
    except redis.RedisError:
        return JSONResponse(
            {"error": "failed to store upload in redis"}, status_code=503
        )

    try:
        publish_image_uploaded(image_hash)
    except Exception:
        return JSONResponse(
            {"error": "failed to enqueue upload job"}, status_code=503
        )

    return JSONResponse({"key": redis_key, "image_hash": image_hash}, status_code=201)


async def list_images(request: Request) -> JSONResponse:
    keys = redis_client.keys("image:*")
    images = []
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        image_hash = key_str.removeprefix("image:")
        data = redis_client.hgetall(key)
        decoded: dict = {"image_hash": image_hash}
        for k, v in data.items():
            field = k.decode()
            if field == "image":
                continue
            decoded[field] = v.decode(errors="replace")
        ocr_raw = decoded.get("ocr_results", "")
        decoded["ocr_results"] = json.loads(ocr_raw) if ocr_raw else None
        images.append(decoded)
    return JSONResponse(images)


async def get_image_metadata(request: Request) -> JSONResponse:
    image_hash = request.path_params["image_hash"]
    data = redis_client.hgetall(f"image:{image_hash}")
    if not data:
        return JSONResponse({"error": "image not found"}, status_code=404)
    decoded: dict = {"image_hash": image_hash}
    for k, v in data.items():
        field = k.decode()
        if field == "image":
            continue
        decoded[field] = v.decode(errors="replace")
    ocr_raw = decoded.get("ocr_results", "")
    decoded["ocr_results"] = json.loads(ocr_raw) if ocr_raw else None
    return JSONResponse(decoded)


async def rerun_ocr(request: Request) -> JSONResponse:
    image_hash = request.path_params["image_hash"]
    redis_key = f"image:{image_hash}"
    if not redis_client.exists(redis_key):
        return JSONResponse({"error": "image not found"}, status_code=404)
    try:
        redis_client.hset(redis_key, "ocr_results", "")
    except redis.RedisError:
        return JSONResponse({"error": "failed to reset state"}, status_code=503)
    try:
        publish_image_uploaded(image_hash)
    except Exception:
        return JSONResponse({"error": "failed to enqueue job"}, status_code=503)
    return JSONResponse({"image_hash": image_hash, "status": "queued"})


async def get_image_file(request: Request) -> Response:
    image_hash = request.path_params["image_hash"]
    image_bytes, content_type = redis_client.hmget(
        f"image:{image_hash}", "image", "content_type"
    )
    if not image_bytes:
        return JSONResponse({"error": "image not found"}, status_code=404)
    ct = content_type.decode() if content_type else "application/octet-stream"
    return Response(content=image_bytes, media_type=ct)


# ── WebSocket ────────────────────────────────────────────────────────────────


async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)


# ── RabbitMQ consumer (background thread) ────────────────────────────────────


def rabbitmq_consumer() -> None:
    while True:
        try:
            connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            channel = connection.channel()
            channel.exchange_declare(
                exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
            )
            queue_name = "web_ocr_results"
            channel.queue_declare(queue=queue_name, durable=True)
            channel.queue_bind(
                exchange=RABBITMQ_EXCHANGE,
                queue=queue_name,
                routing_key="ocr_completed",
            )
            channel.queue_bind(
                exchange=RABBITMQ_EXCHANGE,
                queue=queue_name,
                routing_key="ocr_started",
            )
            channel.queue_bind(
                exchange=RABBITMQ_EXCHANGE,
                queue=queue_name,
                routing_key="ocr_progress",
            )

            def on_message(ch, method, _properties, body):
                payload = json.loads(body.decode("utf-8"))
                if _loop is not None:
                    asyncio.run_coroutine_threadsafe(broadcast(payload), _loop)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=queue_name, on_message_callback=on_message)
            print("Web: listening for ocr_completed events...")
            channel.start_consuming()
        except Exception as exc:
            print(f"RabbitMQ consumer error: {exc}. Retrying in 5s...")
            time.sleep(5)


# ── App setup ────────────────────────────────────────────────────────────────


async def on_startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    threading.Thread(target=rabbitmq_consumer, daemon=True).start()


@asynccontextmanager
async def lifespan(_app):
    await on_startup()
    yield


routes: list = [
    Route("/api/upload", upload_image, methods=["POST"]),
    Route("/api/images/{image_hash}/rerun", rerun_ocr, methods=["POST"]),
    Route("/api/images/{image_hash}/image", get_image_file),
    Route("/api/images/{image_hash}", get_image_metadata),
    Route("/api/images", list_images),
    WebSocketRoute("/ws", websocket_endpoint),
]

if os.path.isdir(STATIC_DIR):
    routes.append(Mount("/", app=StaticFiles(directory=STATIC_DIR, html=True)))

asgi_app = Starlette(routes=routes, lifespan=lifespan)
