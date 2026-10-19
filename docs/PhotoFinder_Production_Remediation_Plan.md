# PhotoFinder — Production Remediation & Implementation Plan

**Project:** `visual-search-api`  
**Purpose:** Define the recommended implementation for hardening image ingestion, distributed processing, multi-tenant security, FAISS consistency, and operational reliability.

> **Status:** Architecture recommendation and implementation checklist. These changes are proposed, not claimed as implemented or tested. Confirm each item against the current repository before changing production code.

---

## 1. Executive Summary

The current remediation plan identifies six areas:

1. Large image payloads passed through Celery/Redis.
2. Stale in-memory FAISS indexes across API and worker processes.
3. Tenant ID override risk in job-status endpoints.
4. Overly permissive CORS configuration.
5. Legacy worker code and unconsumed Redis lists.
6. Import hygiene.

Keep the underlying findings, but improve two major design decisions:

- **Image handoff:** Do not pass image bytes through Redis or make a shared API-to-worker temporary directory the default production handoff. Store the original image in S3 and pass a lightweight job reference to Celery. Workers download images into their own bounded temporary workspace when processing.
- **FAISS consistency:** Do not rely on modification-time polling as the primary consistency mechanism. Define index ownership, serialize writes per index partition, publish complete index versions safely, and make index updates recoverable.

The intended architecture is:

```text
Client
  |
  | 1. Request upload authorization
  v
FastAPI ------------------------------+
  |                                   |
  | 2. Return presigned URL           | 3. Register upload/job
  v                                   v
Client ----------------------------> S3 / PostgreSQL
                                        |
                                        | Durable job/outbox event
                                        v
                                  Outbox Dispatcher
                                        |
                                        v
                                   Celery / Redis
                                        |
                                        v
                              Distributed AI Workers
                                        |
                              Download from S3 to
                              worker-local temp disk
                                        |
                                        v
                             Validate / detect / embed
                                        |
                                        v
                              Persist results durably
                                        |
                                        v
                               FAISS Index Writer
                                        |
                                        v
                              Publish index version
                                        |
                                        v
                                Search API readers
```

This is a target design, not a requirement to create a separate service for every box immediately. Start with the simplest deployment that preserves the same ownership and reliability rules.

---

## 2. Goals and Non-Goals

### Goals

- Keep Redis/Celery messages small.
- Keep S3 as the durable source of original images.
- Decouple API availability from long-running image inference.
- Bound worker memory, temporary disk, and concurrency.
- Make task retries safe.
- Prevent cross-tenant access.
- Prevent concurrent FAISS updates from silently overwriting one another.
- Recover from partial failures between S3, PostgreSQL, Celery, and FAISS.
- Make processing state and operational failures observable.

### Non-Goals

- Do not introduce a vector database solely to fix stale FAISS caches.
- Do not create a separate microservice for every pipeline stage before measurements justify it.
- Do not assume S3, PostgreSQL, Redis, and FAISS can participate in one atomic transaction.
- Do not claim the proposed fixes are implemented until code and tests confirm them.

---

## 3. Recommended Decisions

| Area | Recommendation | Why |
|---|---|---|
| Original image storage | S3 | Durable source for retries and reprocessing |
| Upload path | Prefer client-to-S3 presigned uploads where suitable; otherwise stream API uploads to S3 | Avoid holding full batches in API memory |
| Celery payload | Prefer a `job_id`; retrieve trusted metadata from PostgreSQL | Small messages and less untrusted data in queue arguments |
| Temporary image storage | Worker-local temporary directory with bounded concurrency | Avoid API/worker shared-filesystem coupling |
| Job state | PostgreSQL as durable source of truth | Redis is not the authoritative job database |
| Queue | Celery with Redis broker | Asynchronous job execution |
| Job dispatch reliability | Transactional outbox or an equivalent durable reconciliation mechanism | Recover when DB commit succeeds but queue publication fails |
| Processing retries | Idempotent tasks and bounded retries | At-least-once execution can repeat work |
| Vector updates | One logical writer per index partition, or equivalent locking/serialization | Avoid lost updates from concurrent writers |
| Index publication | Complete, validated, versioned artifacts; publish atomically where storage semantics permit | Readers should not load partial index files |
| Vector metadata | Durable mapping of tenant/image/face/vector IDs and model version | Supports updates, deletion, replay, and reconciliation |
| Tenant security | Derive tenant from verified identity and authorized membership; scope every query | Prevent IDOR and cross-tenant leakage |
| CORS | Explicit trusted origin allowlist | Avoid permissive cross-origin policy |
| Cleanup | Temporary-file cleanup plus stale-file sweeper | Process crashes can bypass normal cleanup |
| Observability | Queue depth, job age, failures, disk, inference latency, index version/lag | Detect bottlenecks and inconsistencies |

---

## 4. CRIT-01 — Celery Payload Bloat and Image Ingestion

### Problem

Passing raw image bytes as task arguments makes messages large, increases serialization and broker memory/network overhead, and can degrade Redis responsiveness. A shared temporary path reduces message size but couples the API and worker to a common filesystem.

### Recommended implementation

1. Store each original image in S3 before making it eligible for processing.
2. Register its metadata and processing job in PostgreSQL.
3. Publish a small Celery message containing only the job ID where practical.
4. Have the worker retrieve the trusted S3 key and tenant association from PostgreSQL.
5. Download the image to a unique worker-local temporary directory.
6. Validate the object, process it, persist results, and remove temporary files.
7. Add cleanup for abandoned temporary files after worker crashes.

### Preferred flow

```text
Client -> Presigned URL -> S3
                         |
                         v
                PostgreSQL image/job
                         |
                         v
                  Outbox dispatcher
                         |
                         v
                    Celery(job_id)
                         |
                         v
                    AI worker
                         |
                         v
                 S3 -> local temp
                         |
                         v
                  Process and save
                         |
                         v
                    Clean up
```

If the API must receive multipart files, stream the upload to S3 and avoid loading an entire large batch into memory when possible.

### Important details

- Use unique object keys and validate ownership before processing.
- Do not trust a tenant ID or S3 key supplied solely by the Celery message.
- Set upload-size, image-dimension, and content-type limits; validate actual file content rather than trusting the filename/MIME type alone.
- Limit the number of downloads and staged files in flight.
- Do not delete the S3 original after successful processing unless the retention policy explicitly requires it.
- Treat S3 upload, database commit, and Celery publish as separate operations.

### Reliability: outbox or reconciliation

A crash can occur after S3 upload or database commit but before the task is published. Use a transactional outbox—record the image/job state and outbox event in one database transaction, then publish from a dispatcher—or implement an equivalent durable reconciliation mechanism.

The outbox does not make S3 transactional with PostgreSQL. Track upload states and reconcile abandoned or incomplete uploads separately.

### Acceptance criteria

- Celery messages contain no raw image bytes.
- API memory does not grow linearly with a large upload batch.
- Workers can run on hosts without a shared API filesystem.
- A job can be retried from the S3 original.
- Duplicate task execution does not create duplicate logical results.
- Temporary storage remains bounded and stale files are cleaned up.

---

## 5. CRIT-02 — FAISS Index Consistency and Concurrency

### Problem

An API process may retain a stale in-memory index after a worker updates an index file. Modification-time polling can help detect changes, but it does not solve concurrent writers, partial file publication, lost updates, or expensive index reloads.

### Recommended implementation

#### A. Establish index ownership

- Define the index partition key, for example tenant + collection/event or another explicit partition.
- Ensure each partition has one logical writer at a time.
- Multiple writers may operate in parallel only when they own different partitions or use a correctly coordinated update mechanism.
- Do not allow API search processes and arbitrary Celery workers to independently mutate and overwrite the same index file.

#### B. Persist vector identity and metadata

Maintain a durable mapping containing appropriate identifiers such as:

- `tenant_id`
- `image_id`
- `face_id`
- stable application-level `vector_id`
- `model_version`
- processing/version status

Use database uniqueness constraints and idempotent upserts to prevent duplicate logical records. Define deletion and reprocessing behavior explicitly.

#### C. Publish safe index versions

For snapshot-based indexes:

1. Build/update a candidate index under controlled writer ownership.
2. Write to a new temporary or immutable versioned artifact.
3. Flush and validate the artifact.
4. Publish the complete version atomically where the storage system supports it, or use a version registry/manifest that points only to completed artifacts.
5. Allow readers to switch to the new version safely.
6. Retain the previous valid version until it is safe to retire.
7. Record the published version and make updates replayable.

Do not overwrite a file that readers may be loading unless the storage and synchronization semantics guarantee safe behavior.

#### D. Avoid rebuilding the entire index for every image

For larger indexes, consider micro-batching, a controlled mutable index, periodic snapshots, and replayable incremental updates. Benchmark the selected FAISS index type and update rate before choosing the strategy.

#### E. Reader refresh

Modification timestamps can be used as an optimization, not as the source of correctness. Prefer an explicit published index version, generation number, notification, or controlled refresh policy. Synchronize index replacement with concurrent searches.

#### F. Reconciliation

Because PostgreSQL and FAISS cannot share a normal atomic transaction, record durable vector-update work and provide a way to replay it. Periodically compare expected vector records with index state or rebuild an index from authoritative metadata/embeddings when necessary.

### Deployment guidance

- **Single host:** a shared persistent volume can work with a single writer, locking, and safe publication.
- **Multiple hosts:** do not assume local Docker volumes share state. Use an explicit storage/publication and ownership design or a dedicated vector-search service.
- **Large scale:** evaluate partitioning or a vector database based on measured workload, reliability, and operational cost—not simply because FAISS is in-memory.

### Acceptance criteria

- Two concurrent updates to the same partition cannot silently overwrite each other.
- Search readers never load a partially written index.
- A published version can be identified and monitored.
- A failed vector update can be replayed.
- New vectors become searchable within a defined consistency objective.
- Delete/reprocess operations do not leave indefinitely visible stale vectors.

---

## 6. CRIT-03 — Tenant Isolation and IDOR

### Required fix

Remove the caller-controlled `tenant_id` override from tenant-sensitive job endpoints. Derive the tenant from a validated identity and an authorized membership/organization selection.

### Apply this rule throughout the system

- Authenticate protected routes.
- Validate JWT signature, issuer, audience, expiration, and other required claims.
- Check organization membership and role permissions.
- Scope every job, image, face, and metadata query to the authorized tenant.
- Validate tenant ownership before generating presigned URLs.
- Apply tenant constraints to vector search and result resolution—not just the final response.
- Set and clear tenant context correctly in reused Celery worker processes.
- Never trust a tenant ID from a task payload without verifying it against durable records.

PostgreSQL Row-Level Security (RLS) can provide defense in depth if tenant context is set correctly for each transaction and connection. It does not replace application authorization.

Returning `404` for a resource that is missing or belongs to another tenant can reduce resource enumeration, provided this matches the application's API conventions.

### Tests

- Tenant A requests Tenant B's job ID.
- Tenant A requests Tenant B's image and face metadata.
- Tenant A attempts to obtain a signed URL for Tenant B's object.
- Tenant A searches vectors that belong to Tenant B.
- A reused Celery worker processes consecutive jobs from different tenants.
- A user with multiple memberships selects an organization they are not authorized to access.

Every test must demonstrate that no unauthorized data is returned.

---

## 7. CRIT-04 — CORS and Request Security

### Required fix

Remove the permissive origin regex and configure an explicit allowlist for the frontend origins that actually need access.

Example environment variable:

```env
CORS_ALLOWED_ORIGINS=https://your-frontend.example,http://localhost:3000
```

Example configuration:

```python
import os

from fastapi.middleware.cors import CORSMiddleware

allowed_origins = [
    value.strip()
    for value in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if value.strip()
]

# Validate this configuration at startup in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

Replace the example domain with the real frontend origin. Configure and validate origins per environment.

Also:

- Avoid wildcard origins when using credentialed CORS.
- Apply CSRF defenses when authentication relies on cookies.
- Keep server-side authentication and authorization; CORS is not an access-control mechanism.
- Test preflight requests and expected allowed/disallowed origins.
- Review whether any additional headers or methods are genuinely required.

---

## 8. CRIT-05 — Legacy Worker Code and Redis Lists

Before deleting legacy functions or Redis list writes:

1. Search the repository for all imports and references.
2. Check Celery schedules, scripts, deployment commands, dashboards, and operational tooling.
3. Verify whether production processes or older deployments still consume the lists.
4. Confirm that PostgreSQL retains the job history and status functions needed by the API.
5. Plan a safe migration/cleanup for existing list entries.
6. Remove the dead code and unconsumed writes.
7. Add tests that verify the intended job lifecycle.

### Target responsibilities

- **PostgreSQL:** authoritative job state and history.
- **Celery:** task execution and delivery/retry orchestration.
- **Redis:** broker and explicitly defined cache responsibilities.
- **S3:** original image storage.

Do not keep two independent queues representing the same work unless there is a documented reason and a synchronization design.

---

## 9. CRIT-06 — Import Hygiene

Move imports to module scope where required by `AGENTS.md` and repository conventions. Before moving any inline import, check whether it deliberately avoids a circular dependency or delays an optional heavyweight import.

Run:

- The project's formatter and linter.
- Import/startup checks.
- Unit and integration tests.
- A search for prohibited inline imports, if required by the repository rules.

Treat this as maintainability work, not as a substitute for security or distributed-systems fixes.

---

## 10. Idempotency, Retries, and Job State

Celery tasks may run more than once. Design processing around that reality.

### Suggested logical job lifecycle

```text
PENDING_UPLOAD
      |
      v
UPLOADED
      |
      v
QUEUED
      |
      v
PROCESSING
   /      \
  v        v
FAILED   COMPLETED
```

This is an illustrative lifecycle. Add retry/waiting states if needed, and define which transitions are allowed.

### Implementation requirements

- Use stable job and image identifiers.
- Use unique constraints for logical face/embedding records.
- Make database writes idempotent.
- Use bounded retries with exponential backoff for transient failures.
- Do not retry permanent validation or authorization failures indefinitely.
- Record attempts, error categories, timestamps, and processing versions.
- Define how a failed job can be retried manually.
- Define how a partially completed job resumes or safely reruns.
- Reconcile PostgreSQL records, S3 objects, and FAISS state.

Avoid marking a job completed until the application's defined durable outputs have been persisted and the required indexing step has reached its agreed completion condition.

---

## 11. Backpressure, Capacity, and Observability

Reducing Celery message size does not automatically prevent overload. The system also needs bounded work in flight.

### Resource controls

- Maximum upload size and decoded image dimensions.
- Bounded concurrent S3 downloads.
- Bounded temporary disk usage.
- Worker concurrency appropriate to CPU/RAM/GPU capacity.
- GPU inference batching where benchmarks show a benefit.
- Queue-depth and queue-age alerts.
- Retry limits and failed-job handling.
- Periodic cleanup of abandoned temporary files.
- Per-tenant quotas/rate limits if needed.

### Metrics to collect

| Metric | Why |
|---|---|
| Queue depth and oldest-job age | Detect backlog |
| Job success/failure and retry rate | Detect reliability problems |
| S3 download latency and bytes | Identify transfer bottlenecks |
| Image decode and inference latency | Identify CPU/GPU bottlenecks |
| Worker RAM, GPU memory, and disk usage | Prevent resource exhaustion |
| Embeddings processed per second | Measure throughput |
| Index published version and update lag | Detect stale search state |
| Outbox age and unpublished count | Detect job-dispatch failures |
| Tenant authorization failures | Detect misuse and regressions |

Tune batch size and concurrency from measurements rather than assuming one fixed batch size will be optimal for all image sizes and hardware.

---

## 12. Revised Implementation Sequence

### Phase 1 — Security

- [ ] Remove caller-controlled tenant overrides.
- [ ] Audit tenant scoping across database, object storage, and vector search.
- [ ] Restrict CORS to explicit trusted origins.
- [ ] Add cross-tenant regression tests.

### Phase 2 — Reliable ingestion

- [ ] Remove raw image bytes from Celery task arguments.
- [ ] Prefer direct-to-S3 uploads where suitable.
- [ ] Use a small job ID as the Celery payload.
- [ ] Store durable job/image state in PostgreSQL.
- [ ] Implement a transactional outbox or equivalent reconciliation.
- [ ] Add worker-local temporary storage and stale-file cleanup.
- [ ] Add idempotency and bounded retry behavior.

### Phase 3 — FAISS consistency

- [ ] Document current index location, index type, and process ownership.
- [ ] Define the partition key and one logical writer per partition.
- [ ] Introduce durable vector IDs and metadata mappings.
- [ ] Prevent concurrent writers from overwriting the same index state.
- [ ] Implement safe versioned index publication.
- [ ] Implement reader refresh/switching.
- [ ] Add durable update replay and reconciliation.
- [ ] Test concurrent updates, reader reloads, deletion, and recovery.

### Phase 4 — Cleanup and operations

- [ ] Verify legacy queue consumers and remove unused list writes.
- [ ] Remove dead code only after reference and migration checks.
- [ ] Fix import hygiene.
- [ ] Add queue, disk, inference, and index metrics.
- [ ] Load-test bounded batch processing.
- [ ] Document recovery and operational procedures.

---

## 13. Verification Checklist

Do not mark a fix complete just because the code was changed. Verify behavior.

- [ ] Full existing test suite passes.
- [ ] New security regression tests pass.
- [ ] Celery task payloads contain no raw image bytes.
- [ ] Large batches do not cause unbounded API memory or worker disk growth.
- [ ] Jobs recover when queue publication or a worker fails.
- [ ] Duplicate delivery does not create duplicate logical results.
- [ ] Concurrent FAISS updates do not lose vectors.
- [ ] Search readers never load partial index artifacts.
- [ ] New vectors become searchable within the defined consistency target.
- [ ] Tenant A cannot retrieve Tenant B's resources or vectors.
- [ ] Temporary files are removed after success and eventually cleaned after crashes.
- [ ] Metrics and alerts reveal queue backlog and indexing failures.

Use the repository's actual test commands and deployment setup. A passing unit suite alone does not prove multi-process consistency; include integration tests that exercise separate API and worker processes.

---

## 14. Final Engineering Decisions

The recommended baseline for PhotoFinder is:

1. **S3 is the durable source for original images.**
2. **Celery messages carry lightweight identifiers, not image bytes.**
3. **AI workers use their own temporary storage and process bounded amounts of work.**
4. **PostgreSQL owns durable image metadata, job state, and vector metadata.**
5. **FAISS updates have explicit writer ownership, safe publication, and a recovery path.**
6. **Tenant authorization is enforced at every data-access boundary.**
7. **The pipeline tolerates duplicate task execution and partial failures.**
8. **Concurrency, temporary storage, and retries are bounded and observable.**

These decisions preserve the benefits of your current FastAPI/Celery/Redis/S3/FAISS stack without prematurely introducing unnecessary services.

### Decisions to confirm before implementation

The following details are not established by the remediation plan and should be verified in the repository:

- Is the FAISS directory local to each container, a shared Docker volume, or a network-mounted filesystem?
- Which FAISS index types are used, and which operations mutate them?
- Are there multiple API workers or Celery processes writing the same index?
- Is PostgreSQL already the authoritative job store?
- Can uploads be changed to direct-to-S3, or must the API accept multipart files?
- What are the expected image volume, average file size, index size, and acceptable search freshness?

These answers determine the safest implementation details. The architecture above is the recommended direction; exact code changes should follow a source-code review and tests.
