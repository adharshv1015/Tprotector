# API Change/Breakage Monitor

A resilient backend system built with Python, FastAPI, APScheduler, SQLAlchemy 2.0, DeepDiff, and PostgreSQL for continuously monitoring 3rd-party APIs.

## Key Capabilities

1. **Schema & Contract Change Detection**:
   - Recursively extracts structural response schemas (field types & nesting without raw data).
   - Identifies breaking changes (field removals, type shifts, container array ↔ object shifts).
   - Classifies additive fields as non-breaking (with documented considerations for rigid deserializers).
   - Stabilizes `null` value transitions (`NoneType` ↔ concrete type categorized as `informational` to eliminate alert fatigue).
   - Compares strictly against the latest successful snapshot, preventing comparisons against error states.

2. **POST & Mutating Endpoint Monitoring with Safety Guardrails**:
   - Supports configurable `test_payload` and `custom_headers`.
   - Requires `is_sandbox=True` for any `POST`, `PUT`, `PATCH`, or `DELETE` methods to prevent accidental live execution against production endpoints.

3. **HTTP Resilience & Deduplication Invariant**:
   - 2-attempt policy with exponential backoff on transient network drops/5xx errors.
   - Guaranteed single snapshot entry per scheduled check.

4. **Multi-Auth Engine & Encryption at Rest**:
   - Supports `none`, `api_key`, `bearer`, `basic`, and `oauth2_client_credentials`.
   - Credentials encrypted at rest with Fernet (`cryptography.fernet`).
   - Token caching with expiration buffers for OAuth2 client-credentials flow.
   - Zero-downtime key rotation architecture (`MultiFernet`).

5. **Rate-Limit Header Monitoring**:
   - Configurable per-API header extraction (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`).
   - Alerts on customizable consumption thresholds (default: >80%).

6. **Latency & Anomaly Drift Detection**:
   - 7-day rolling baseline calculation (mean + std deviation).
   - Z-score anomaly detection ($z > 3.0$) and error rate spike alerts.

7. **Deprecation Notice Scraping**:
   - Changelog SHA-256 hash detection.
   - Keyword & regex pattern scanning (`deprecated`, `sunset`, `will be removed`, `end of life`, `discontinued`).
   - Modular hook prepared for future LLM summarization.

8. **Unified Event Timeline & Multi-Channel Alerts**:
   - Centralized `events` stream.
   - Slack Incoming Webhook and SMTP Email notifications for high and breaking events.

---

## Getting Started

### 1. Environment Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Generate a Fernet encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Place this key into `ENCRYPTION_KEY` in `.env`.

### 2. Encryption Key Rotation Procedure

To rotate your `ENCRYPTION_KEY`:
1. Generate a new Fernet key.
2. In your environment, set `ROTATION_ENCRYPTION_KEYS="<new_key>,<old_key>"`.
3. The system's `MultiFernet` reader can decrypt secrets encrypted with `<old_key>` and will encrypt new records using `<new_key>`.
4. Run the re-encryption utility to migrate existing DB records to the new key.

### 3. Running with Docker Compose (PostgreSQL)

```bash
docker compose up -d postgres
```

### 4. Running the Application

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive API documentation available at `http://localhost:8000/docs`.
