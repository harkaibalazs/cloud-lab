import json
import logging
import os
import sys
import tempfile
import time
from typing import Any

import easyocr
import pika
import redis
from pika.adapters.blocking_connection import BlockingChannel


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "events")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "ocr_worker")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ocr")


def normalize_ocr_results(raw_results: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw_results:
        if len(item) != 3:
            continue

        bbox, text, confidence = item
        normalized.append(
            {
                "bbox": [[float(point[0]), float(point[1])] for point in bbox],
                "text": str(text),
                "confidence": float(confidence),
            }
        )
    return normalized


def fetch_image_bytes(
    redis_client: redis.Redis, image_hash: str
) -> tuple[str, bytes] | tuple[None, None]:
    candidate_keys = (image_hash, f"image:{image_hash}")
    for key in candidate_keys:
        image_bytes = redis_client.hget(key, "image")
        if image_bytes:
            return key, image_bytes
    return None, None


def run_ocr(reader: easyocr.Reader, image_bytes: bytes) -> list[dict[str, Any]]:
    with tempfile.NamedTemporaryFile(suffix=".img") as temp_image:
        temp_image.write(image_bytes)
        temp_image.flush()
        raw_results = reader.readtext(temp_image.name)
    return normalize_ocr_results(raw_results)


def publish_ocr_completed(
    channel: BlockingChannel,
    image_hash: str,
    ocr_results: list[dict[str, Any]],
) -> None:
    event = {
        "type": "ocr_completed",
        "hash": image_hash,
        "ocr_results": ocr_results,
    }
    channel.basic_publish(
        exchange=RABBITMQ_EXCHANGE,
        routing_key="ocr_completed",
        body=json.dumps(event).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json", delivery_mode=2
        ),
    )


def main() -> None:
    log.info("OCR worker starting up")
    log.info("Loading EasyOCR model (languages: ch_sim, en)...")
    model_start = time.monotonic()
    reader = easyocr.Reader(["ch_sim", "en"])
    log.info("EasyOCR model loaded in %.1fs", time.monotonic() - model_start)

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
                        log.info("Skipping non-image_uploaded event: %s", payload.get("type"))
                        _channel.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    image_hash = payload.get("hash")
                    if not image_hash:
                        log.warning("Received image_uploaded event with no hash; acking")
                        _channel.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    log.info("Processing image %s", image_hash)
                    redis_key, image_bytes = fetch_image_bytes(redis_client, image_hash)
                    if not redis_key or not image_bytes:
                        log.warning("Image %s not found in Redis; acking", image_hash)
                        _channel.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    ocr_start = time.monotonic()
                    ocr_results = run_ocr(reader, image_bytes)
                    log.info(
                        "OCR done for %s: %d regions in %.2fs",
                        image_hash,
                        len(ocr_results),
                        time.monotonic() - ocr_start,
                    )
                    redis_client.hset(redis_key, "ocr_results", json.dumps(ocr_results))
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
