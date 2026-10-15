# Visual Search API — Engineering Guidelines & Rules

## Python Import Hygiene & Module Dependencies
- **Top-Level Imports by Default**: All imports must be placed at the top of the file following PEP 8 conventions.
- **Prohibition of Arbitrary Inline Imports**: Never use inline imports (`from ... import ...` inside functions or methods) for common internal services, repositories, or cache utilities (e.g., `get_kv_cache`, `get_repository`, utility helpers).
- **Shared Helpers**: If two worker task modules need the same helper logic, place the helper in a shared base or common module (e.g., `src/tasks/base.py`) rather than relying on cross-module inline imports.
- **Permitted Inline Import Exceptions**:
  1. Heavy vision / deep learning models in lightweight CLI entrypoints.
  2. Genuine circular dependency escape hatches when cross-queuing Celery tasks across worker queues.
  3. Optional platform/hardware-specific libraries (e.g., CUDA / TensorRT checks).

