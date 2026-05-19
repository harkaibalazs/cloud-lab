import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any

import pika
import pytesseract
import redis
from PIL import Image
from pika.adapters.blocking_connection import BlockingChannel


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "events")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "ocr_worker")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TESSERACT_LANGS = os.getenv("TESSERACT_LANGS", "eng+chi_sim")
MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ocr")

# pytesseract returns word-level entries at level 5 (page=1, block=2, par=3, line=4, word=5)
_WORD_LEVEL = 5


def normalize_tesseract_data(data: dict[str, list[Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    count = len(data.get("text", []))
    for i in range(count):
        if int(data["level"][i]) != _WORD_LEVEL:
            continue
        text = data["text"][i].strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if conf < 0:
            continue
        x = float(data["left"][i])
        y = float(data["top"][i])
        w = float(data["width"][i])
        h = float(data["height"][i])
        results.append(
            {
                "bbox": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                "text": text,
                "confidence": conf / 100.0,
            }
        )
    return results


def fetch_image_bytes(
    redis_client: redis.Redis, image_hash: str
) -> tuple[str, bytes] | tuple[None, None]:
    candidate_keys = (image_hash, f"image:{image_hash}")
    for key in candidate_keys:
        image_bytes = redis_client.hget(key, "image")
        if image_bytes:
            return key, image_bytes
    return None, None


def run_ocr(image_bytes: bytes) -> list[dict[str, Any]]:
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    data = pytesseract.image_to_data(
        image, lang=TESSERACT_LANGS, output_type=pytesseract.Output.DICT
    )
    results = normalize_tesseract_data(data)
    if MIN_CONFIDENCE > 0:
        results = [r for r in results if r["confidence"] >= MIN_CONFIDENCE]
    return results


def publish_event(
    channel: BlockingChannel,
    routing_key: str,
    payload: dict[str, Any],
) -> None:
    channel.basic_publish(
        exchange=RABBITMQ_EXCHANGE,
        routing_key=routing_key,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json", delivery_mode=2
        ),
    )


def publish_ocr_started(channel: BlockingChannel, image_hash: str) -> None:
    publish_event(
        channel,
        "ocr_started",
        {"type": "ocr_started", "hash": image_hash},
    )


def publish_ocr_completed(
    channel: BlockingChannel,
    image_hash: str,
    ocr_results: list[dict[str, Any]],
) -> None:
    publish_event(
        channel,
        "ocr_completed",
        {
            "type": "ocr_completed",
            "hash": image_hash,
            "ocr_results": ocr_results,
        },
    )


def main() -> None:
    log.info("OCR worker starting up")

    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract binary not found in PATH")
    version = (
        subprocess.check_output(["tesseract", "--version"], stderr=subprocess.STDOUT)
        .decode()
        .splitlines()[0]
    )
    log.info("Tesseract ready: %s (languages: %s)", version, TESSERACT_LANGS)

    log.info("Connecting to Redis at %s", REDIS_URL)
    redis_client = redis.Redis.from_url(REDIS_URL)
    redis_client.ping()
    log.info("Redis connection established")

    while True:
        try:
            log.info("Connecting to RabbitMQ at %s", RABBITMQ_URL)
            rabbit_connection = pika.BlockingConnection(
                pika.URLParameters(RABBITMQ_URL)
            )
            channel = rabbit_connection.channel()
            channel.exchange_declare(
                exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
            )
            channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
            channel.queue_bind(
                exchange=RABBITMQ_EXCHANGE,
                queue=RABBITMQ_QUEUE,
                routing_key="image_uploaded",
            )
            log.info(
                "RabbitMQ ready: exchange=%s queue=%s routing_key=image_uploaded",
                RABBITMQ_EXCHANGE,
                RABBITMQ_QUEUE,
            )

            def on_message(
                _channel: BlockingChannel,
                method: Any,
                _properties: Any,
                body: bytes,
            ) -> None:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if payload.get("type") != "image_uploaded":
                        log.info(
                            "Skipping non-image_uploaded event: %s",
                            payload.get("type"),
                        )
                        _channel.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    image_hash = payload.get("hash")
                    if not image_hash:
                        log.warning("Received image_uploaded event with no hash; acking")
                        _channel.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    log.info("Processing image %s", image_hash)
                    publish_ocr_started(_channel, image_hash)
                    redis_key, image_bytes = fetch_image_bytes(redis_client, image_hash)
                    if not redis_key or not image_bytes:
                        log.warning("Image %s not found in Redis; acking", image_hash)
                        _channel.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    ocr_start = time.monotonic()
                    ocr_results = run_ocr(image_bytes)
                    log.info(
                        "OCR done for %s: %d words in %.2fs",
                        image_hash,
                        len(ocr_results),
                        time.monotonic() - ocr_start,
                    )
                    redis_client.hset(
                        redis_key, "ocr_results", json.dumps(ocr_results)
                    )
                    publish_ocr_completed(_channel, image_hash, ocr_results)
                    log.info("Published ocr_completed for %s", image_hash)
                    _channel.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Failed to process message: %s", exc)
                    _channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=on_message)
            log.info("Initialization finished, OCR worker is ready and listening")
            channel.start_consuming()
        except Exception as exc:  # noqa: BLE001
            log.error("Connection error: %s. Retrying in 5 seconds...", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
