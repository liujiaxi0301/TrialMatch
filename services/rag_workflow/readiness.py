"""Read-only readiness diagnostics; never create vectors or make model requests."""

import threading
import time
from datetime import UTC, datetime

from .index import VectorIndex
from .providers import ProviderError


class ReadinessProbe:
    def __init__(self, settings, workflow, ttl=30):
        self.settings, self.workflow, self.ttl = settings, workflow, ttl
        self._lock = threading.Lock()
        self._expires, self._report = 0, None

    def check(self):
        with self._lock:
            if self._report is not None and time.monotonic() < self._expires:
                return self._report
            report = {
                "ready": False,
                "mode": self.settings.mode,
                "check_scope": "data_and_index",
                "checked_at": datetime.now(UTC).isoformat(),
                "cache_ttl_seconds": self.ttl,
                "model_access": "NOT_PROBED",
                "note": "Readiness does not prove Gemini permissions, quota or inference availability.",
                "checks": {},
            }
            stage = "data"
            try:
                service = self.workflow()
                manifest = service.store.manifest()
                report["checks"]["data"] = {"status": "PASS"}
                stage = "index"
                if self.settings.mode == "offline":
                    report["checks"]["index"] = {"status": "NOT_REQUIRED"}
                    report["model_access"] = "NOT_REQUIRED"
                else:
                    if not self.settings.project:
                        raise ProviderError("MISSING_GCP_PROJECT", "Project is not configured")
                    if (
                        not self.settings.chroma_host
                        and not (self.settings.artifacts / "chroma").is_dir()
                    ):
                        raise ProviderError("INDEX_NOT_READY", "No existing local vector database")
                    index = VectorIndex(self.settings, service.store, manifest)
                    state = index.status()
                    report["checks"]["index"] = {
                        "status": "PASS",
                        "index_version": state["index_version"],
                        "vector_count": state["vector_count"],
                    }
                report["ready"] = True
            except ProviderError as exc:
                report["checks"][stage] = {"status": "FAIL", "code": exc.code}
            except FileNotFoundError:
                report["checks"][stage] = {"status": "FAIL", "code": "MISSING_ARTIFACT"}
            except (ValueError, TypeError, KeyError):
                report["checks"][stage] = {"status": "FAIL", "code": "INVALID_ARTIFACT"}
            except Exception:  # noqa: BLE001 -- Dependency boundary; never expose raw connection errors.
                report["checks"][stage] = {"status": "FAIL", "code": "DEPENDENCY_UNAVAILABLE"}
            self._report, self._expires = report, time.monotonic() + self.ttl
            return report
