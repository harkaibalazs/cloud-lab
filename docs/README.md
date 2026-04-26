# Cloud Lab -- Fejlesztői dokumentáció

## Bevezetés

A Cloud Lab egy felhőtechnológiákra épülő, mikroszolgáltatás-alapú alkalmazás, amely képek feltöltését, tárolását és automatikus karakterfelismerést (OCR) valósít meg. A rendszer három fő komponensből áll: egy **React frontend**-ből, egy **Python backend**-ből (web) és egy **OCR worker**-ből. A komponensek közötti kommunikáció RabbitMQ üzenetsoron, az adattárolás pedig Redis-ben történik.

### Architektúra áttekintés

```
┌─────────────┐      HTTP/WS       ┌─────────────────┐
│   React     │◄──────────────────►│   Web Backend    │
│  Frontend   │                    │  (Starlette)     │
└─────────────┘                    └──────┬──────┬────┘
                                          │      │
                                    Redis │      │ RabbitMQ
                                          │      │
                                   ┌──────▼──────▼────┐
                                   │   OCR Worker      │
                                   │   (EasyOCR)       │
                                   └───────────────────┘
```

**Adatfolyam:**

1. A felhasználó a React felületen kiválaszt egy képet és megad egy leírást, majd feltölti.
2. A web backend a képet és metaadatokat Redisben tárolja, majd egy `image_uploaded` eseményt küld a RabbitMQ `events` exchange-re.
3. Az OCR worker felveszi az üzenetet, Redisből kiolvassa a képet, lefuttatja az EasyOCR karakterfelismerést.
4. Az eredményeket visszaírja Redisbe, majd egy `ocr_completed` eseményt publikál RabbitMQ-n.
5. A web backend egy háttérszálban figyeli az `ocr_completed` eseményeket és WebSocket-en keresztül azonnal továbbítja az összes csatlakozott kliensnek.
6. A React frontend megkapja az eredményt és a képen canvas overlay segítségével megjeleníti a felismert szövegterületeket bekeretezve.

---

## Frontend (React)

### Technológiák

| Technológia | Verzió  | Szerep                              |
|-------------|---------|-------------------------------------|
| React       | 19.x    | UI komponensek                      |
| TypeScript  | 5.x     | Típusbiztos fejlesztés              |
| Vite        | 6.x     | Build eszköz és fejlesztői szerver  |

### Könyvtárszerkezet

```
web/frontend/
├── index.html              # HTML belépési pont
├── package.json            # Függőségek és scriptek
├── tsconfig.json           # TypeScript konfiguráció
├── vite.config.ts          # Vite konfiguráció (proxy beállítások)
└── src/
    ├── main.tsx            # React alkalmazás belépési pont
    ├── App.tsx             # Fő komponens, állapotkezelés, WebSocket
    ├── App.css             # Globális stílusok
    └── components/
        ├── UploadForm.tsx  # Kép- és leírás feltöltő űrlap
        └── ImageCard.tsx   # Kép megjelenítése OCR eredményekkel
```

### Komponensek

#### `App.tsx` -- Fő komponens

Az alkalmazás belépési pontja. Feladatai:

- **Állapotkezelés:** A feltöltött képek listáját (`ImageData[]`) kezeli React `useState`-tel.
- **Kezdeti betöltés:** Oldalbetöltéskor lekéri az összes korábban feltöltött képet a `GET /api/images` végponttól.
- **WebSocket kapcsolat:** Csatlakozik a `/ws` végpontra. Amikor `ocr_completed` típusú üzenet érkezik, az `image_hash` alapján megkeresi a megfelelő képet az állapotban és frissíti annak `ocr_results` mezőjét. Kapcsolat megszakadása esetén 3 másodperc múlva automatikusan újracsatlakozik.

Adatmodellek:

```typescript
interface OcrResult {
  bbox: number[][];     // 4 sarokpont [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
  text: string;         // Felismert szöveg
  confidence: number;   // Megbízhatóság (0.0 -- 1.0)
}

interface ImageData {
  image_hash: string;       // SHA-256 hash (egyedi azonosító)
  description: string;      // Felhasználó által megadott leírás
  filename: string;         // Eredeti fájlnév
  content_type: string;     // MIME típus (pl. image/png)
  ocr_results: OcrResult[] | null;  // null = még feldolgozás alatt
}
```

#### `UploadForm.tsx` -- Feltöltő űrlap

Egy `<form>` elem, amely két beviteli mezőt tartalmaz:

- **Fájlválasztó** (`<input type="file" accept="image/*">`): Kép kiválasztása.
- **Leírás** (`<input type="text">`): A képhez tartozó rövid leírás.

Működése:
1. A felhasználó kiválasztja a képet és megadja a leírást.
2. A "Upload" gomb megnyomásával `FormData`-ként POST kérés indul a `/api/upload` végpontra.
3. Sikeres feltöltés után meghívja az `onUploaded` callback-et, amely a képet `ocr_results: null` állapottal hozzáadja a galéria elejéhez.
4. A form ürítődik a következő feltöltéshez.

Hibakezelés: Ha a szerver hibát ad vissza (pl. hiányzó mező), a hibaüzenet megjelenik a form alatt piros szöveggel.

#### `ImageCard.tsx` -- Képkártya OCR eredményekkel

Megjeleníti a feltöltött képet és rávetíti az OCR által detektált szövegterületeket. A megvalósítás egy `<img>` és egy rá helyezett `<canvas>` elem kombinációja:

- A `<canvas>` belső felbontása megegyezik a kép eredeti méretével (`naturalWidth` x `naturalHeight`).
- CSS-sel a canvas ugyanakkora méretre van méretezve, mint a megjelenített kép, így a koordináták automatikusan illeszkednek.

Rajzolási logika (`useEffect`, `image.ocr_results` változásakor fut):

1. Minden OCR találatra zöld (`#00ff00`) poligont rajzol a `bbox` 4 sarokpontja alapján.
2. A poligon fölé félkék háttérrel feliratot helyez a felismert szöveggel.

Állapotjelzők:
- `ocr_results === null` → "OCR processing..." felirat
- `ocr_results` üres tömb → "No text detected" felirat

### Fejlesztői szerver

A `vite.config.ts` proxy beállításai lehetővé teszik a lokális fejlesztést a backend mellett:

- `/api/*` kérések → `http://localhost:8000` (Python backend)
- `/ws` → `ws://localhost:8000` (WebSocket)

Indítás:

```bash
cd web/frontend
npm install
npm run dev       # Elindul a Vite dev szerver (alapértelmezetten :5173)
```

### Build

```bash
npm run build     # TypeScript ellenőrzés + Vite production build → dist/
```

A build kimenete a `dist/` könyvtárba kerül, amelyet a Docker build során a Python konténer `static/` mappájába másol a rendszer.

---

## Backend (Web)

### Technológiák

| Technológia      | Szerep                                          |
|------------------|-------------------------------------------------|
| Starlette        | ASGI webalkalmazás-keretrendszer                 |
| Uvicorn          | ASGI szerver                                     |
| python-multipart | Multipart form adat (fájlfeltöltés) feldolgozás  |
| Redis (py-redis) | Kapcsolat a Redis adattárhoz                     |
| Pika             | RabbitMQ AMQP kliens                             |

### Könyvtárszerkezet

```
web/
├── app.py              # Alkalmazás fő fájlja
├── requirements.txt    # Python függőségek
├── Dockerfile          # Multi-stage build (Node + Python)
└── frontend/           # React alkalmazás (lásd fentebb)
```

### API végpontok

#### `POST /api/upload`

Kép feltöltése leírással.

**Kérés:** `multipart/form-data`

| Mező          | Típus  | Kötelező | Leírás                    |
|---------------|--------|----------|---------------------------|
| `image`       | file   | igen     | A feltöltendő képfájl     |
| `description` | string | igen     | A képhez tartozó leírás   |

**Sikeres válasz (201):**
```json
{
  "key": "image:<sha256_hash>",
  "image_hash": "<sha256_hash>"
}
```

**Működése:**
1. SHA-256 hash-t számol a kép tartalmából (ez lesz az egyedi azonosító).
2. Redisben `image:<hash>` kulcs alá hash map-ként tárolja: `description`, `image` (nyers bájtok), `filename`, `content_type`, `ocr_results` (üres string kezdetben).
3. RabbitMQ `events` exchange-re `image_uploaded` routing key-jel publikál egy üzenetet a hash-sel.

#### `GET /api/images`

Az összes feltöltött kép metaadatainak lekérése.

**Válasz (200):**
```json
[
  {
    "image_hash": "abc123...",
    "description": "Számla fotója",
    "filename": "szamla.jpg",
    "content_type": "image/jpeg",
    "ocr_results": [ ... ] | null
  }
]
```

Az `ocr_results` mező `null` ha még nem készült el a feldolgozás, egyébként az OCR találatok tömbje.

#### `GET /api/images/{image_hash}`

Egyetlen kép metaadatai és OCR eredményei (kép bájtok nélkül).

#### `GET /api/images/{image_hash}/image`

A kép nyers bájtjainak kiszolgálása a megfelelő `Content-Type` fejléccel. Ezt a végpontot használja a frontend az `<img>` elemek `src` attribútumában.

### WebSocket (`/ws`)

A backend natív Starlette WebSocket támogatást használ. A kapcsolat felállása:

1. A kliens csatlakozik a `/ws` végpontra.
2. A szerver elfogadja és hozzáadja a `ws_clients` halmazhoz.
3. Amikor `ocr_completed` üzenet érkezik RabbitMQ-ról, a szerver broadcast-olja az összes csatlakozott kliensnek.
4. Kapcsolat bontása esetén a kliens eltávolítása a halmazból.

**WebSocket üzenet formátum (szerver → kliens):**
```json
{
  "type": "ocr_completed",
  "hash": "<image_hash>",
  "ocr_results": [
    {
      "bbox": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
      "text": "felismert szöveg",
      "confidence": 0.95
    }
  ]
}
```

### RabbitMQ fogyasztó (háttérszál)

Az alkalmazás indulásakor (`on_startup`) egy daemon szál indul, amely:

1. Csatlakozik a RabbitMQ-hoz és deklarálja a `web_ocr_results` sort.
2. A sort köti az `events` exchange `ocr_completed` routing key-éhez.
3. Beérkező üzenetekre `asyncio.run_coroutine_threadsafe` hívással a fő event loop-on broadcast-ol a WebSocket klienseknek.
4. Kapcsolati hiba esetén 5 másodperc után újra próbálkozik.

### Környezeti változók

| Változó            | Alapértelmezés                              | Leírás                    |
|--------------------|---------------------------------------------|---------------------------|
| `RABBITMQ_URL`     | `amqp://guest:guest@localhost:5672/%2F`      | RabbitMQ kapcsolati URL   |
| `RABBITMQ_EXCHANGE`| `events`                                     | Topic exchange neve       |
| `REDIS_URL`        | `redis://localhost:6379/0`                   | Redis kapcsolati URL      |

### Dockerfile (multi-stage build)

```
1. fázis (frontend):  Node 22 Alpine konténerben npm ci + npm run build → dist/
2. fázis (backend):   Python 3.14 Slim konténerben pip install + app.py + static/
```

A végleges image tartalmazza a lefordított React alkalmazást a `static/` könyvtárban, amelyet a Starlette `StaticFiles` middleware szolgál ki (`html=True` beállítással, így az `index.html` SPA fallback-ként működik).

---

## OCR Worker

### Technológiák

| Technológia | Szerep                                        |
|-------------|-----------------------------------------------|
| EasyOCR     | Neurális hálózat alapú karakterfelismerő motor |
| PyTorch     | Gépi tanulási keretrendszer (EasyOCR függőség) |
| Pika        | RabbitMQ AMQP kliens                          |
| Redis       | Kép- és eredménytárolás                        |

### Könyvtárszerkezet

```
ocr/
├── app.py              # Worker fő fájlja
├── requirements.txt    # Python függőségek
└── Dockerfile          # PyTorch + EasyOCR build
```

### Működési elv

Az OCR worker egy hosszú életű folyamat (long-running process), amely nem szolgál ki HTTP kéréseket. Ehelyett RabbitMQ üzenetsorból dolgozik:

#### Indulás (`main()`)

1. Betölti az EasyOCR modellt egyszerűsített kínai (`ch_sim`) és angol (`en`) nyelvi támogatással. Ez a lépés jelentős időt vesz igénybe (modellfájlok letöltése és GPU/CPU inicializálás).
2. Redis kapcsolatot létesít.
3. Végtelen ciklusban csatlakozik a RabbitMQ-hoz.

#### Üzenetfeldolgozás (`on_message`)

Amikor `image_uploaded` típusú üzenet érkezik:

1. **Kép kiolvasás:** A `hash` mező alapján Redisből kiolvassa a kép nyers bájtjait. Két kulcsformátumot is megpróbál: `<hash>` és `image:<hash>`.
2. **OCR futtatás (`run_ocr`):** A kép bájtjait ideiglenes fájlba írja, majd az EasyOCR `readtext()` metódusával feldolgozza.
3. **Eredmény normalizálás (`normalize_ocr_results`):** Az EasyOCR nyers kimenetét egységes formátumra alakítja:
   ```python
   {
       "bbox": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],  # Befoglaló téglalap 4 sarka
       "text": "felismert szöveg",                        # Detektált szöveg
       "confidence": 0.95                                  # Megbízhatósági érték
   }
   ```
4. **Tárolás:** Az eredményt JSON stringként visszaírja a Redis hash `ocr_results` mezőjébe.
5. **Értesítés:** `ocr_completed` eseményt publikál a RabbitMQ `events` exchange-re, amely tartalmazza a hash-t és a teljes OCR eredményt.

#### Hibakezelés

- Egyedi üzenet feldolgozási hiba esetén `basic_nack` (requeue nélkül), így az üzenet nem kerül vissza a sorba.
- RabbitMQ kapcsolati hiba esetén 5 másodperc múlva újracsatlakozik.
- `prefetch_count=1` beállítás biztosítja, hogy egyszerre csak egy képet dolgoz fel (az OCR CPU/GPU-intenzív művelet).

### Környezeti változók

| Változó            | Alapértelmezés                              | Leírás                     |
|--------------------|---------------------------------------------|----------------------------|
| `RABBITMQ_URL`     | `amqp://guest:guest@localhost:5672/%2F`      | RabbitMQ kapcsolati URL    |
| `RABBITMQ_EXCHANGE`| `events`                                     | Topic exchange neve        |
| `RABBITMQ_QUEUE`   | `ocr_worker`                                 | Fogyasztói sor neve        |
| `REDIS_URL`        | `redis://localhost:6379/0`                   | Redis kapcsolati URL       |

### Dockerfile

A PyTorch hivatalos Docker image-re (`pytorch/pytorch`) épül:

1. Telepíti a szükséges rendszercsomagokat (grafikus könyvtárak az OpenCV/EasyOCR-hoz).
2. Klónozza és forrásból építi az EasyOCR-t.
3. Telepíti a Python függőségeket (`pika`, `redis`).
4. Az `app.py` másolásakor a konténer kész az indulásra.

**Megjegyzés:** Az image mérete jelentős (~6-8 GB) a PyTorch és az EasyOCR modellek miatt. Első induláskor az EasyOCR automatikusan letölti a szükséges súlyfájlokat.

---

## Komponensek közötti kommunikáció

### RabbitMQ exchange és routing

Az összes komponens egyetlen topic exchange-et használ: `events`

| Routing key       | Kiadja          | Fogyasztja                    | Üzenet tartalma                    |
|--------------------|-----------------|-------------------------------|------------------------------------|
| `image_uploaded`   | Web Backend     | OCR Worker                    | `{ type, hash }`                   |
| `ocr_completed`    | OCR Worker      | Web Backend, Feliratkozók     | `{ type, hash, ocr_results }`      |

### Redis adatstruktúra

Minden feltöltött kép egy Redis hash-ben tárolódik `image:<sha256>` kulcs alatt:

| Mező           | Típus  | Leírás                                         |
|----------------|--------|-------------------------------------------------|
| `description`  | string | Felhasználó által megadott leírás               |
| `image`        | bytes  | A kép nyers bájtjai                             |
| `filename`     | string | Eredeti fájlnév                                 |
| `content_type` | string | MIME típus                                      |
| `ocr_results`  | string | JSON tömb az OCR eredményekkel (üres = futás) |

---

## Üzemeltetői feliratkozás (értesítések)

### Koncepció

A rendszer lehetőséget biztosít az üzemeltetők (operátorok) számára, hogy értesítéseket kapjanak a feltöltött képekről és azok OCR eredményeiről. Az értesítés tartalmazza:

- A képhez tartozó **rövid leírást** (amelyet a felhasználó adott meg feltöltéskor)
- A képen **detektált szöveges tartalmat** (az OCR által felismert szavak/karakterek)

A megoldás a már meglévő RabbitMQ infrastruktúrára épül -- nincs szükség új exchange vagy routing key létrehozására.

### Működési elv

A RabbitMQ topic exchange (`events`) lehetővé teszi, hogy tetszőleges számú fogyasztó feliratkozzon ugyanarra a routing key-re. Minden feliratkozó a saját dedikált sorát (queue) hozza létre és köti az exchange-hez. Így az üzenetek minden feliratkozóhoz eljutnak, anélkül hogy az a meglévő komponensek működését befolyásolná.

```
                          events (topic exchange)
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
    routing: ocr_completed  ocr_completed       ocr_completed
              │                   │                   │
              ▼                   ▼                   ▼
      ┌──────────────┐  ┌─────────────────┐  ┌─────────────────┐
      │ web_ocr_results│  │ operator_alice  │  │ operator_bob    │
      │ (Web Backend) │  │ (feliratkozó)   │  │ (feliratkozó)   │
      └──────────────┘  └─────────────────┘  └─────────────────┘
```

**Új képeknél** az OCR worker az `ocr_completed` üzenetben elküldi a hash-t és a teljes OCR eredményt. A feliratkozó ebből a hash alapján lekéri Redisből a leírást is.

**Korábban feltöltött képeknél** a feliratkozó induláskor végigolvassa a Redis `image:*` kulcsokat és feldolgozza az összes már kész OCR eredményt.

### Példa feliratkozó script

Az alábbi Python script bemutatja, hogyan lehet feliratkozni az értesítésekre. A script:

1. Induláskor lekéri az összes korábbi képet Redisből és kiírja az eredményeiket.
2. Ezt követően RabbitMQ-n figyeli az új `ocr_completed` eseményeket.

```python
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

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
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
```

### Példa kimenet

```
[INFO] 3 korábbi kép feldolgozása...

[KORÁBBI] a1b2c3d4e5f6...
  Leírás:    Éttermi számla fotója
  OCR szöveg: Összesen | 4500 Ft | Köszönjük

[KORÁBBI] f6e5d4c3b2a1...
  Leírás:    Parkolójegy
  OCR szöveg: Érvényes | 2026.04.26 | 14:00-16:00

[KORÁBBI] 1234abcd5678... (OCR még folyamatban)
  Leírás: Útjelző tábla

[INFO] Feliratkozva mint 'operator_default' -- várakozás új képekre...

[ÚJ] 9876fedc5432...
  Leírás:    Csomagcímke
  OCR szöveg: Budapest | 1234 | Fő utca 1.
```

### Több feliratkozó futtatása

Minden operátor egyedi `SUBSCRIBER_NAME`-mel indítja a scriptet, így mindegyik saját RabbitMQ sort kap:

```bash
# Terminál 1 -- Alice
SUBSCRIBER_NAME=alice python operator_subscribe.py

# Terminál 2 -- Bob
SUBSCRIBER_NAME=bob python operator_subscribe.py
```

Mindkét feliratkozó megkapja az összes `ocr_completed` üzenetet egymástól függetlenül. Ha egy feliratkozó ideiglenesen leáll, a durable sor megőrzi a közben érkezett üzeneteket, és a következő csatlakozáskor kézbesíti azokat.

### Integrációs lehetőségek

A példa script konzolra ír, de a `on_ocr_completed` callback könnyen bővíthető más értesítési csatornákkal:

| Csatorna        | Megvalósítás                                              |
|-----------------|-----------------------------------------------------------|
| E-mail          | `smtplib` vagy külső szolgáltatás (SendGrid, SES)        |
| Slack           | Slack Incoming Webhook HTTP POST hívás                    |
| Webhook         | Tetszőleges HTTP endpoint meghívása a payload-dal         |
| Adatbázis/napló | Az értesítések perzisztens tárolása további feldolgozáshoz |

---

## CI/CD

Két GitHub Actions workflow működik, komponensenként egy-egy:

### Dev build (push to main)

Triggerelődik, ha a `web/` vagy `ocr/` könyvtárban történik változás a `main` ágban. Az image `dev-<sha7>` taggel kerül a GHCR-be.

### Production build (tag push)

Tag formátum: `web-vX.Y.Z` vagy `ocr-vX.Y.Z`. A workflow:

1. Építi és push-olja az image-et a verzió taggel + `latest` taggel.
2. Frissíti a megfelelő Kubernetes deployment manifest `image` mezőjét.
3. Commitolja a változást a `main` ágra, így az ArgoCD automatikusan észleli és deployolja az új verziót.
