import hashlib
import os

import redis
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, jsonify, request


app = Flask(__name__)


@app.get("/")
def hello_world() -> str:
    return "Hello, world!"


def get_redis_client() -> redis.Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(redis_url)


@app.post("/upload")
def upload_image():
    image_file = request.files.get("image")
    description = request.form.get("description", "")

    if image_file is None:
        return jsonify({"error": "missing image field"}), 400
    if not description:
        return jsonify({"error": "missing description field"}), 400

    image_bytes = image_file.read()
    if not image_bytes:
        return jsonify({"error": "image file is empty"}), 400

    image_hash = hashlib.sha256(image_bytes).hexdigest()
    redis_key = f"image:{image_hash}"

    try:
        redis_client = get_redis_client()
        redis_client.hset(
            redis_key,
            mapping={
                "description": description,
                "image": image_bytes,
                "filename": image_file.filename or "",
                "content_type": image_file.mimetype or "",
                "ocr_result": ""
            },
        )
    except redis.RedisError:
        return jsonify({"error": "failed to store upload in redis"}), 503

    return jsonify({"key": redis_key, "image_hash": image_hash}), 201


asgi_app = WsgiToAsgi(app)
