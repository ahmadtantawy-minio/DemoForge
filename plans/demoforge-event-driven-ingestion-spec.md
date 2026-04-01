# DemoForge Spec: Event-Driven Data Ingestion Pipeline

## Demo Identity

- **Template name**: `event-driven-ingestion`
- **Display name**: Event-Driven Data Ingestion Pipeline
- **Description**: Demonstrates a production-grade event ingestion pattern where producers fire events freely into Solace PubSub+, Kong Gateway manages downstream consumer protection, and MinIO provides S3-compatible object storage with bucket notification feedback into the event mesh.
- **Resource weight**: `heavy` (~6-8GB RAM total)
- **Category**: Integration / Event-Driven Architecture

---

## 1. Architecture Overview

### 1.1 Design Philosophy

Producers must never be throttled. The event broker (Solace) absorbs all events with guaranteed delivery, manages retry and backpressure transparently, and fans out to consumers via topic subscriptions. The API gateway (Kong) protects downstream services — not producers. MinIO bucket notifications feed back into the event mesh, enabling reactive downstream processing.

### 1.2 Data Flow

```
Step 1: Producers → Solace PubSub+ (MQTT / AMQP / REST)
Step 2: Solace → Kong Gateway (guaranteed delivery, topic routing)
Step 3: Kong → MinIO (auth, transformation, rate limiting on consumer side)
Step 4: MinIO bucket notification → Solace (feedback loop via webhook)
Step 5: Solace → Downstream consumers (fan-out via topic subscriptions)
```

### 1.3 Component Roles

| Component | Role | Why Here |
|-----------|------|----------|
| **Solace PubSub+** | Event broker | Guaranteed delivery, backpressure management, retry, topic-based routing. Accepts all events without throttling. MQTT/AMQP/REST ingress. |
| **Kong Gateway** | API gateway | Consumer-side rate limiting, auth, request/response transformation, observability, logging. Protects MinIO and downstream services. |
| **MinIO** | Object storage | S3-compatible landing zone. Bucket notifications trigger events back into Solace for downstream fan-out. |
| **Event Bridge** | Webhook relay | Lightweight container that receives MinIO bucket notification webhooks and publishes them to Solace's REST ingress. Completes the feedback loop. |

### 1.4 Port Map

| Service | Port | Purpose |
|---------|------|---------|
| Solace PubSub+ | 8080 | PubSub+ Manager (web UI) |
| Solace PubSub+ | 55555 | SMF (Solace Message Format) |
| Solace PubSub+ | 1883 | MQTT |
| Solace PubSub+ | 8008 | REST messaging |
| Solace PubSub+ | 5672 | AMQP |
| Kong Gateway | 8000 | Proxy (consumer-facing) |
| Kong Gateway | 8443 | Proxy SSL |
| Kong Gateway | 8001 | Admin API |
| MinIO | 9000 | S3 API |
| MinIO | 9001 | Console (web UI) |
| Event Bridge | 3500 | Webhook receiver (internal only) |

---

## 2. Component Manifests

Four new manifests required in `manifests/components/`.

### 2.1 `solace-pubsub.yaml`

```yaml
name: solace-pubsub
display_name: Solace PubSub+ Standard
description: Enterprise-grade event broker with guaranteed messaging, topic routing, and multi-protocol support (MQTT, AMQP, REST, SMF).
category: messaging
vendor: true
image: solace/solace-pubsub-standard:latest
image_size_mb: 1200
resource_weight: heavy

ports:
  - container_port: 8080
    host_port: 8080
    protocol: tcp
    description: PubSub+ Manager web UI
  - container_port: 55555
    host_port: 55555
    protocol: tcp
    description: SMF messaging
  - container_port: 1883
    host_port: 1883
    protocol: tcp
    description: MQTT
  - container_port: 8008
    host_port: 8008
    protocol: tcp
    description: REST messaging
  - container_port: 5672
    host_port: 5672
    protocol: tcp
    description: AMQP

environment:
  - name: username_admin_globalaccesslevel
    value: admin
  - name: username_admin_password
    value: admin
  - name: system_scaling_maxconnectioncount
    value: "100"

shm_size: "1g"

healthcheck:
  test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
  interval: 15s
  timeout: 10s
  retries: 20
  start_period: 60s

ui_links:
  - label: PubSub+ Manager
    url: "http://localhost:8080"
    description: Solace web management console

notes: |
  Solace PubSub+ Standard is the free tier. It takes 30-60 seconds to boot fully.
  Requires shm_size of at least 1g. Recommend 2-4GB system RAM available.
  The 'heavy' resource_weight flag warns FAs about memory requirements.
```

### 2.2 `kong-gateway.yaml`

```yaml
name: kong-gateway
display_name: Kong Gateway (DB-less)
description: Lightweight API gateway in declarative DB-less mode. Provides auth, rate limiting, request transformation, and observability for downstream service protection.
category: networking
vendor: true
image: kong/kong-gateway:3.9
image_size_mb: 500
resource_weight: medium

ports:
  - container_port: 8000
    host_port: 8000
    protocol: tcp
    description: Proxy (consumer-facing)
  - container_port: 8443
    host_port: 8443
    protocol: tcp
    description: Proxy SSL
  - container_port: 8001
    host_port: 8001
    protocol: tcp
    description: Admin API

environment:
  - name: KONG_DATABASE
    value: "off"
  - name: KONG_PROXY_ACCESS_LOG
    value: /dev/stdout
  - name: KONG_ADMIN_ACCESS_LOG
    value: /dev/stdout
  - name: KONG_PROXY_ERROR_LOG
    value: /dev/stderr
  - name: KONG_ADMIN_ERROR_LOG
    value: /dev/stderr
  - name: KONG_ADMIN_LISTEN
    value: "0.0.0.0:8001"
  - name: KONG_DECLARATIVE_CONFIG
    value: /etc/kong/kong.yml

volumes:
  - source: ./config/kong/kong.yml
    target: /etc/kong/kong.yml
    read_only: true

healthcheck:
  test: ["CMD", "kong", "health"]
  interval: 10s
  timeout: 5s
  retries: 10
  start_period: 15s

ui_links:
  - label: Kong Admin API
    url: "http://localhost:8001"
    description: Kong admin API (no UI — use curl or HTTPie)

notes: |
  Runs in DB-less / declarative mode — no Postgres dependency.
  All routes and plugins are defined in kong.yml, mounted as a volume.
  The template's setup script generates kong.yml with the correct upstream URLs.
```

### 2.3 `event-bridge.yaml`

```yaml
name: event-bridge
display_name: Event Bridge (MinIO → Solace)
description: Lightweight webhook relay that receives MinIO bucket notifications and publishes them as events to Solace PubSub+ REST ingress. Completes the event mesh feedback loop.
category: integration
vendor: false
image: localhost:5000/demoforge-event-bridge:latest
image_size_mb: 50
resource_weight: light

build:
  context: ./images/event-bridge
  dockerfile: Dockerfile

ports:
  - container_port: 3500
    host_port: 3500
    protocol: tcp
    description: Webhook receiver (internal)

environment:
  - name: SOLACE_REST_URL
    value: "http://solace-pubsub:8008"
  - name: SOLACE_TOPIC_PREFIX
    value: "minio/events"
  - name: WEBHOOK_PORT
    value: "3500"
  - name: LOG_LEVEL
    value: info

healthcheck:
  test: ["CMD-SHELL", "curl -sf http://localhost:3500/health || exit 1"]
  interval: 10s
  timeout: 3s
  retries: 5
  start_period: 5s

depends_on:
  - solace-pubsub

notes: |
  Custom image — built from images/event-bridge/ in dev mode,
  pulled from private registry (localhost:5000) in FA mode.
  Stateless relay: receives POST from MinIO webhook, publishes to Solace REST.
```

### 2.4 MinIO Manifest Update

The existing MinIO manifest needs an addition to its environment section for this template. This is handled at the **template level**, not by modifying the base MinIO manifest. The template overrides MinIO's environment to configure bucket notification webhooks:

```yaml
# In the template's component overrides for minio:
environment_overrides:
  - name: MINIO_NOTIFY_WEBHOOK_ENABLE_BRIDGE
    value: "on"
  - name: MINIO_NOTIFY_WEBHOOK_ENDPOINT_BRIDGE
    value: "http://event-bridge:3500/webhook"
  - name: MINIO_NOTIFY_WEBHOOK_QUEUE_DIR_BRIDGE
    value: /data/.minio/notify/webhook
  - name: MINIO_NOTIFY_WEBHOOK_QUEUE_LIMIT_BRIDGE
    value: "10000"
```

---

## 3. Event Bridge Container

### 3.1 Purpose

MinIO bucket notifications use webhooks (HTTP POST). Solace PubSub+ accepts REST messages via its REST ingress on port 8008. The Event Bridge is a stateless HTTP relay that:

1. Receives MinIO webhook POSTs on `/webhook`
2. Extracts the event type and bucket/object key from the notification JSON
3. Publishes to Solace REST ingress with a topic derived from the event (e.g., `minio/events/{bucket}/{eventType}`)
4. Returns 200 to MinIO (so MinIO doesn't retry)

### 3.2 Implementation

Minimal Python (FastAPI) or Node.js container. ~50 lines of code.

```
images/event-bridge/
├── Dockerfile
├── main.py          # FastAPI app
└── requirements.txt # fastapi, uvicorn, httpx
```

**Core logic (Python pseudocode):**

```python
from fastapi import FastAPI, Request
import httpx

app = FastAPI()
SOLACE_REST_URL = os.environ["SOLACE_REST_URL"]
TOPIC_PREFIX = os.environ.get("SOLACE_TOPIC_PREFIX", "minio/events")

@app.post("/webhook")
async def handle_minio_webhook(request: Request):
    payload = await request.json()
    event_name = payload.get("EventName", "unknown")
    bucket = payload.get("Records", [{}])[0].get("s3", {}).get("bucket", {}).get("name", "unknown")
    key = payload.get("Records", [{}])[0].get("s3", {}).get("object", {}).get("key", "unknown")
    
    topic = f"{TOPIC_PREFIX}/{bucket}/{event_name}"
    
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SOLACE_REST_URL}/TOPIC/{topic}",
            json=payload,
            headers={"Content-Type": "application/json", "Solace-delivery-mode": "persistent"}
        )
    
    return {"status": "ok", "topic": topic}

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### 3.3 Image Lifecycle

- **Dev mode**: Built from `images/event-bridge/Dockerfile`
- **FA mode**: Pulled from private registry via `localhost:5000/demoforge-event-bridge:latest`
- **Push**: Added to `hub-push.sh` image list after build

---

## 4. Kong Declarative Configuration

### 4.1 Kong Config File

The template includes a pre-built `kong.yml` that defines routes and plugins. This file is generated by the template's setup script and mounted into the Kong container.

```
config/kong/kong.yml
```

### 4.2 Routes and Services

```yaml
_format_version: "3.0"
_transform: true

services:
  # Route: Solace → Kong → MinIO S3 API
  - name: minio-s3
    url: http://minio:9000
    routes:
      - name: minio-s3-route
        paths:
          - /s3
        strip_path: true
    plugins:
      - name: rate-limiting
        config:
          minute: 120
          policy: local
      - name: key-auth
        config:
          key_names:
            - x-api-key
      - name: request-transformer
        config:
          add:
            headers:
              - "X-Forwarded-Proto:http"

  # Route: Direct MinIO Console access (passthrough, no rate limiting)
  - name: minio-console
    url: http://minio:9001
    routes:
      - name: minio-console-route
        paths:
          - /console
        strip_path: true

consumers:
  - username: solace-consumer
    keyauth_credentials:
      - key: demo-solace-key-2024
```

### 4.3 Plugin Rationale

| Plugin | Purpose |
|--------|---------|
| `rate-limiting` | Protects MinIO from burst overload — consumer-side throttling, not producer-side |
| `key-auth` | Authenticates Solace as an authorized consumer of MinIO |
| `request-transformer` | Adds required headers for MinIO S3 compatibility |

---

## 5. Demo Template

### 5.1 Template File

Location: `demo-templates/event-driven-ingestion.yaml`

```yaml
name: event-driven-ingestion
display_name: Event-Driven Data Ingestion Pipeline
description: >
  Producers fire events freely into Solace PubSub+ without throttling.
  Kong Gateway protects downstream MinIO storage with consumer-side rate limiting
  and auth. MinIO bucket notifications feed back into the event mesh via a
  lightweight bridge, enabling reactive fan-out to downstream consumers.
category: integration
resource_weight: heavy
estimated_ram_gb: 6
tags:
  - event-driven
  - messaging
  - api-gateway
  - object-storage
  - solace
  - kong
  - minio

components:
  - name: solace-pubsub
    manifest: solace-pubsub
    # No overrides — defaults are sufficient

  - name: kong-gateway
    manifest: kong-gateway
    # kong.yml volume is defined in manifest, template provides the config file

  - name: minio
    manifest: minio
    environment_overrides:
      - name: MINIO_NOTIFY_WEBHOOK_ENABLE_BRIDGE
        value: "on"
      - name: MINIO_NOTIFY_WEBHOOK_ENDPOINT_BRIDGE
        value: "http://event-bridge:3500/webhook"
      - name: MINIO_NOTIFY_WEBHOOK_QUEUE_DIR_BRIDGE
        value: /data/.minio/notify/webhook
      - name: MINIO_NOTIFY_WEBHOOK_QUEUE_LIMIT_BRIDGE
        value: "10000"

  - name: event-bridge
    manifest: event-bridge

startup_order:
  - solace-pubsub     # Boots first, takes 30-60s
  - minio             # Boots in parallel once Solace is healthy
  - event-bridge      # Waits for Solace (depends_on in manifest)
  - kong-gateway      # Last — needs MinIO and Solace ready

network:
  name: event-ingestion-net
  driver: bridge

setup_script: |
  #!/bin/bash
  # Post-deploy setup:
  # 1. Create MinIO bucket "ingestion" via mc
  # 2. Configure MinIO bucket notification for the "ingestion" bucket
  # 3. Create Solace queue and topic subscription via SEMP API
  # 4. Verify end-to-end flow with a test event

  echo "Waiting for Solace PubSub+ to be ready..."
  until curl -sf http://localhost:8080/health > /dev/null 2>&1; do sleep 5; done
  echo "Solace is ready."

  echo "Waiting for MinIO to be ready..."
  until curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; do sleep 2; done
  echo "MinIO is ready."

  # Create MinIO alias and bucket
  mc alias set local http://minio:9000 minioadmin minioadmin
  mc mb local/ingestion --ignore-existing
  
  # Enable bucket notification for the ingestion bucket
  mc event add local/ingestion arn:minio:sqs::BRIDGE:webhook --event "put,delete"

  # Configure Solace via SEMP v2 API
  SEMP_URL="http://solace-pubsub:8080/SEMP/v2/config"
  AUTH="-u admin:admin"
  VPN="default"

  # Create queue for MinIO events
  curl -sf $AUTH -X POST "$SEMP_URL/msgVpns/$VPN/queues" \
    -H "Content-Type: application/json" \
    -d '{
      "queueName": "minio-events",
      "accessType": "non-exclusive",
      "egressEnabled": true,
      "ingressEnabled": true,
      "permission": "consume"
    }'

  # Subscribe queue to MinIO event topics
  curl -sf $AUTH -X POST "$SEMP_URL/msgVpns/$VPN/queues/minio-events/subscriptions" \
    -H "Content-Type: application/json" \
    -d '{"subscriptionTopic": "minio/events/>"}'

  echo "Setup complete. Pipeline is ready."
```

### 5.2 Canvas Layout Hints

The template includes layout coordinates so the React Flow canvas renders the components in the logical flow order (left to right):

```yaml
canvas_layout:
  solace-pubsub:   { x: 200, y: 200 }
  kong-gateway:    { x: 500, y: 200 }
  minio:           { x: 800, y: 200 }
  event-bridge:    { x: 500, y: 450 }
```

Edges (connections) rendered on canvas:

```yaml
canvas_edges:
  - source: solace-pubsub
    target: kong-gateway
    label: "Guaranteed delivery"
  - source: kong-gateway
    target: minio
    label: "Auth + rate limit"
  - source: minio
    target: event-bridge
    label: "Bucket notification"
  - source: event-bridge
    target: solace-pubsub
    label: "REST publish"
```

---

## 6. DemoForge Changes Required

### 6.1 Manifest Schema Changes

| Change | Reason | Impact |
|--------|--------|--------|
| Add `shm_size` field | Solace requires shared memory configuration (`shm_size: "1g"`). Docker Compose supports this natively but DemoForge's manifest schema must allow it. | Manifest schema + Docker Compose generator |
| Add `resource_weight` field | Values: `light`, `medium`, `heavy`. Enables the UI to warn FAs before deploying memory-intensive stacks. | Manifest schema + template schema |
| Add `estimated_ram_gb` to template schema | Numeric estimate of total stack RAM. Displayed in template gallery alongside the template description. | Template schema + gallery UI |
| Add `environment_overrides` in template components | Templates need to inject additional env vars into base manifests without modifying them. The MinIO webhook config is template-specific. | Template schema + Docker Compose generator |
| Add `startup_order` to template schema | Defines the order containers should be started with health-gate checks between stages. | Template schema + deployment orchestrator |
| Add `depends_on` with health conditions to manifests | Solace takes 30-60s to boot. Event Bridge must wait. Kong must wait for MinIO. Docker Compose `depends_on` with `condition: service_healthy`. | Docker Compose generator |

### 6.2 New Files to Create

```
manifests/components/
├── solace-pubsub.yaml          # NEW — Solace PubSub+ Standard
├── kong-gateway.yaml           # NEW — Kong Gateway (DB-less)
└── event-bridge.yaml           # NEW — Event Bridge relay

images/event-bridge/
├── Dockerfile                  # NEW — Python/FastAPI webhook relay
├── main.py                     # NEW — ~50 lines, MinIO webhook → Solace REST
└── requirements.txt            # NEW — fastapi, uvicorn, httpx

demo-templates/
└── event-driven-ingestion.yaml # NEW — Full template definition

config/kong/
└── kong.yml                    # NEW — Kong declarative config (generated or static)
```

### 6.3 Existing Files to Modify

| File | Change |
|------|--------|
| Manifest JSON schema | Add `shm_size` (string, optional), `resource_weight` (enum, optional), `depends_on` (array of objects with conditions, optional) |
| Template JSON schema | Add `estimated_ram_gb` (number, optional), `resource_weight` (enum, optional), `startup_order` (array, optional), `environment_overrides` in component entries |
| Docker Compose generator | Handle `shm_size`, `depends_on` with health conditions, `environment_overrides` merging |
| `hub-push.sh` | Add `demoforge-event-bridge` to the image push list |
| Template gallery UI (optional) | Display `resource_weight` badge and `estimated_ram_gb` in template cards |

### 6.4 What Does NOT Change

- **React Flow canvas** — already handles arbitrary component types from manifests
- **Deployment engine** — Docker Compose generation is already dynamic; schema additions flow through automatically once the generator is updated
- **Hub sync** — template sync works for any template YAML; no changes needed
- **Existing manifests** — no modifications to existing MinIO, Trino, Spark, etc. manifests

---

## 7. Implementation Phases

### Phase 1: Schema & Manifests
1. Extend manifest schema with `shm_size`, `resource_weight`, `depends_on`
2. Extend template schema with `estimated_ram_gb`, `resource_weight`, `startup_order`, `environment_overrides`
3. Create the three new component manifests (solace-pubsub, kong-gateway, event-bridge)
4. Update Docker Compose generator to handle new fields

### Phase 2: Event Bridge Container
5. Create `images/event-bridge/` with Dockerfile, main.py, requirements.txt
6. Build and test locally in dev mode
7. Add to `hub-push.sh` for registry publishing

### Phase 3: Template & Config
8. Create Kong declarative config (`config/kong/kong.yml`)
9. Create demo template YAML with all component wiring
10. Write and test the setup script (MinIO bucket, notifications, Solace queue/subscription)

### Phase 4: End-to-End Validation
11. Deploy full stack via `make dev`
12. Publish a test event via MQTT to Solace
13. Verify it flows through Kong → MinIO → bucket notification → Event Bridge → back into Solace
14. Verify downstream consumer receives the fan-out event
15. Test failure scenarios: MinIO down (Solace retries), Kong rate limit hit (Solace buffers)

### Phase 5: FA Experience
16. Push event-bridge image to private registry
17. Test full FA flow: `make fa-setup` → load template → deploy → demo
18. Add resource weight badge to template gallery (optional, low priority)

---

## 8. Demo Script (What the FA Shows)

### 8.1 Story Arc

> "Your IoT fleet is generating thousands of events per second. You can't afford to drop any of them, but you also can't let a burst take down your storage layer. Here's how we solve that."

### 8.2 Walkthrough Steps

1. **Show the canvas** — four components wired together, explain the flow
2. **Deploy the stack** — one click, watch containers come up (Solace takes ~60s)
3. **Open Solace Manager** (`:8080`) — show the queue, zero messages
4. **Publish test events** — use MQTT client or curl to fire 50 events into Solace
5. **Show Solace Manager** — messages flowing through, queue depth visible
6. **Open MinIO Console** (`:9001`) — show objects landing in the `ingestion` bucket
7. **Show the feedback loop** — delete an object in MinIO, watch the bucket notification appear as a new event in Solace
8. **Show Kong rate limiting** — fire a burst directly at Kong, show some requests get 429'd while Solace holds the overflow and retries
9. **Key takeaway**: "Producers never get throttled. The broker absorbs everything. The gateway protects your storage. Events flow in a loop."

### 8.3 Test Commands for FA

```bash
# Publish 10 test events via Solace REST ingress
for i in $(seq 1 10); do
  curl -X POST http://localhost:8008/TOPIC/demo/ingest \
    -H "Content-Type: application/json" \
    -H "Solace-delivery-mode: persistent" \
    -d "{\"sensor_id\": \"sensor-$i\", \"value\": $((RANDOM % 100)), \"ts\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
done

# Check Solace queue depth
curl -sf -u admin:admin http://localhost:8080/SEMP/v2/monitor/msgVpns/default/queues/minio-events | jq '.data.msgCount'

# Check MinIO bucket
mc ls local/ingestion/

# Fire burst at Kong to demo rate limiting
for i in $(seq 1 200); do
  curl -s -o /dev/null -w "%{http_code}\n" -X PUT http://localhost:8000/s3/ingestion/burst-$i \
    -H "x-api-key: demo-solace-key-2024" \
    -d "payload-$i"
done | sort | uniq -c
# Expected: mix of 200s and 429s
```

---

## 9. Open Questions

1. **Port conflicts**: Solace uses 8080 (PubSub+ Manager). If another component in DemoForge already claims 8080, the template needs a port remap. Investigate current port allocations.

2. **Kong mode**: DB-less is simpler (no Postgres dependency), but limits runtime route changes. If FAs want to add routes during demos, we'd need DB-backed mode + a `kong-db` manifest. Start with DB-less, revisit if needed.

3. **Solace licensing**: PubSub+ Standard is free but has connection limits (100 connections, 10k msg/s). Sufficient for demos. If FAs need higher throughput for specific demos, document the upgrade path to PubSub+ Enterprise (requires Solace license).

4. **Event Bridge alternatives**: Instead of a custom container, MinIO can send notifications to Kafka (via built-in support), and Solace has a Kafka bridge. But that adds Kafka as a dependency, which defeats the simplicity. Custom bridge is the right call for now.

5. **Template `environment_overrides` design**: Should overrides merge with or replace the manifest's environment list? Recommendation: **merge** (append new vars, override existing by name). This is the least surprising behavior and matches Docker Compose semantics.
