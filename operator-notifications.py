#!/usr/bin/env python3
"""
Üzemeltetői értesítő script -- feliratkozás képfeltöltési és OCR eseményekre.

Használat:
    pip install pika redis
    python operator_subscribe.py

Környezeti változók:
    RABBITMQ_URL    (alapértelmezés: amqp://guest:guest@localhost:5672/%2F)
    REDIS_URL       (alapértelmezés: redis://localhost:6379/0)
    SUBSCRIBER_NAME (alapértelmezés: operator_default)
"""

import json
import os
import sys

import pika
import redis

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://cloudlab:cloudlab@localhost:5672/%2F")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "events")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SUBSCRIBER_NAME = os.getenv("SUBSCRIBER_NAME", "operator_default")


def format_notification(description: str, ocr_results: list[dict]) -> str:
    """Az értesítés formázása emberi olvasásra."""
    lines = [
        f"  Leírás:    {description}",
    ]
    if ocr_results:
        texts = [r["text"] for r in ocr_results]
        lines.append(f"  OCR szöveg: {' | '.join(texts)}")
    else:
        lines.append("  OCR szöveg: (nem található szöveg a képen)")
    return "\n".join(lines)


def process_existing_images(redis_client: redis.Redis) -> None:
    """Korábban feltöltött képek feldolgozása Redisből."""
    keys = redis_client.keys("image:*")
    if not keys:
        print("[INFO] Nincsenek korábban feltöltött képek.\n")
        return

    print(f"[INFO] {len(keys)} korábbi kép feldolgozása...\n")
    for key in keys:
        data = redis_client.hgetall(key)
        image_hash = key.decode().removeprefix("image:")
        description = data.get(b"description", b"").decode(errors="replace")
        ocr_raw = data.get(b"ocr_results", b"").decode(errors="replace")

        if not ocr_raw:
            print(f"[KORÁBBI] {image_hash[:12]}... (OCR még folyamatban)")
            print(f"  Leírás: {description}\n")
            continue

        ocr_results = json.loads(ocr_raw)
        print(f"[KORÁBBI] {image_hash[:12]}...")
        print(format_notification(description, ocr_results))
        print()


def on_ocr_completed(ch, method, _properties, body, redis_client: redis.Redis) -> None:
    """Új OCR eredmény érkezésekor hívódik."""
    payload = json.loads(body.decode("utf-8"))
    image_hash = payload.get("hash", "")
    ocr_results = payload.get("ocr_results", [])

    # Leírás lekérése Redisből
    description_bytes = redis_client.hget(f"image:{image_hash}", "description")
    description = description_bytes.decode(errors="replace") if description_bytes else "(ismeretlen)"

    print(f"[ÚJ] {image_hash[:12]}...")
    print(format_notification(description, ocr_results))
    print()

    ch.basic_ack(delivery_tag=method.delivery_tag)


def main() -> None:
    redis_client = redis.Redis.from_url(REDIS_URL)

    # 1. Korábbi képek feldolgozása
    process_existing_images(redis_client)

    # 2. Feliratkozás új eseményekre
    #    A sor neve a feliratkozó nevét tartalmazza -- minden operátor
    #    a saját sorából olvas, így mindenki megkapja az összes üzenetet.
    queue_name = f"subscriber_{SUBSCRIBER_NAME}"

    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.exchange_declare(
        exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
    )
    channel.queue_declare(queue=queue_name, durable=True)
    channel.queue_bind(
        exchange=RABBITMQ_EXCHANGE,
        queue=queue_name,
        routing_key="ocr_completed",
    )

    print(f"[INFO] Feliratkozva mint '{SUBSCRIBER_NAME}' -- várakozás új képekre...\n")

    channel.basic_consume(
        queue=queue_name,
        on_message_callback=lambda ch, method, props, body: on_ocr_completed(
            ch, method, props, body, redis_client
        ),
    )

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("\n[INFO] Feliratkozás leállítva.")
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()