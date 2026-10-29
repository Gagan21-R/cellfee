"""QpiAI QCloud / QpiAI Opt connectivity and run-evidence logging.

Every quantum or optimisation run is written to artifacts/evidence/ with the
backend used, settings, job IDs (cloud runs) and outputs, so judges can audit it.
"""

from __future__ import annotations

import json
import time
import uuid
from functools import lru_cache
from typing import Any

from . import config


_QCLOUD_OK = False


def qcloud_login(attempts: int = 3) -> bool:
    """Log in to QpiAI QCloud if a key is configured; retries network timeouts, caches success only."""
    global _QCLOUD_OK
    if _QCLOUD_OK:
        return True
    if not config.QCLOUD_API_KEY:
        return False
    from qpiai_quantum import QpiAIQuantumAuth

    last = None
    for k in range(attempts):
        try:
            QpiAIQuantumAuth.login(api_key=config.QCLOUD_API_KEY)
            _QCLOUD_OK = True
            return True
        except Exception as exc:  # network timeout / invalid key
            last = exc
            time.sleep(2 * (k + 1))
    log_evidence("qcloud_login_failed", {"error": str(last), "attempts": attempts})
    return False


@lru_cache(maxsize=1)
def opt_client():
    """Return an authenticated QpiAI Opt Client, or None without a key."""
    if not config.OPT_API_KEY:
        return None
    try:
        from qpiai_opt.opt_solvers import Client

        return Client(api_key=config.OPT_API_KEY)
    except Exception as exc:
        log_evidence("opt_client_failed", {"error": str(exc)})
        return None


def run_circuit(circuit, shots: int, device: str):
    """Run on a QCloud device; if the cloud refuses the job (no subscription / credits),
    fall back to the key-free QpiAI-QSV-Local simulator. Returns (result, device_used, note)."""
    if device != "QpiAI-QSV-Local" and qcloud_login():
        try:
            return circuit.run(shots=shots, device_name=device, experiment_name=config.QCLOUD_EXPERIMENT), device, None
        except Exception as exc:
            msg = str(exc)
            i = msg.find("Server response")
            note = f"{device} refused the job ({msg[i:i + 140] if i >= 0 else msg[:140]}); ran on QpiAI-QSV-Local"
            return circuit.run(shots=shots, device_name="QpiAI-QSV-Local"), "QpiAI-QSV-Local", note
    return circuit.run(shots=shots, device_name="QpiAI-QSV-Local"), "QpiAI-QSV-Local", None


def opt_assignment(result, model) -> dict[str, float]:
    """Name -> value from a QpiAI Opt result (variable_assignment dict, or solution list/dict)."""
    va = getattr(result, "variable_assignment", None)
    if isinstance(va, dict) and va:
        return {str(k): float(v) for k, v in va.items()}
    sol = getattr(result, "solution", None)
    if isinstance(sol, dict):
        return {str(k): float(v) for k, v in sol.items()}
    names = [v.name for v in model.variables()]
    return {n: float(v) for n, v in zip(names, sol or [])}


def status() -> dict[str, Any]:
    import qpiai_opt  # noqa: F401  (import check)
    import qpiai_quantum

    return {
        "qpiai_quantum_version": getattr(qpiai_quantum, "__version__", "unknown"),
        "qcloud_key_configured": bool(config.QCLOUD_API_KEY),
        "opt_key_configured": bool(config.OPT_API_KEY),
        "kernel_device": config.KERNEL_DEVICE,
        "qaoa_device": config.QAOA_DEVICE,
        "opt_solver": "QpiAI Opt local solver" if config.OPT_API_KEY else "built-in fallback (HiGHS MILP + annealing)",
    }


def _jsonable(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        if isinstance(obj, dict):
            return {str(k): _jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_jsonable(v) for v in obj]
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return str(obj)


def log_evidence(kind: str, payload: dict[str, Any]) -> str:
    """Append a run record to artifacts/evidence/<kind>_<id>.json and return its id."""
    config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{time.strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    record = {"run_id": run_id, "kind": kind, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload}
    (config.EVIDENCE_DIR / f"{run_id}.json").write_text(json.dumps(_jsonable(record), indent=2))
    return run_id


def list_evidence() -> list[dict[str, Any]]:
    if not config.EVIDENCE_DIR.exists():
        return []
    out = []
    for path in sorted(config.EVIDENCE_DIR.glob("*.json"), reverse=True):
        try:
            rec = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        out.append({k: rec.get(k) for k in ("run_id", "kind", "timestamp", "backend", "device", "job_ids", "summary")})
    return out
