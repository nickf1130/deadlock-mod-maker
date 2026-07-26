from __future__ import annotations

import json
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import StudioError
from ..paths import AppPaths
from .router import BackendRouter


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class ProtocolWriter:
    def __init__(self) -> None:
        self.lock = threading.Lock()

    def send(self, payload: dict[str, Any]) -> None:
        with self.lock:
            sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def run_worker() -> None:
    paths = AppPaths.resolve()
    file_handler = RotatingFileHandler(
        paths.logs / "python-worker.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            file_handler,
        ],
    )
    writer = ProtocolWriter()
    router = BackendRouter(paths, writer.send)
    build_threads: set[threading.Thread] = set()

    def execute(request: Request) -> None:
        try:
            result = router.dispatch(request.method, request.params)
            writer.send({"id": request.id, "ok": True, "result": result})
        except ValidationError as error:
            writer.send(
                {
                    "id": request.id,
                    "ok": False,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Request validation failed.",
                        "details": {"errors": error.errors(include_url=False)},
                    },
                }
            )
        except StudioError as error:
            writer.send({"id": request.id, "ok": False, "error": error.as_payload()})
        except Exception:
            logging.exception(
                "Unhandled backend error while running %s", request.method
            )
            writer.send(
                {
                    "id": request.id,
                    "ok": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected backend error occurred.",
                        "details": {},
                    },
                }
            )

    try:
        for line in sys.stdin:
            try:
                request = Request.model_validate_json(line)
            except ValidationError as error:
                writer.send(
                    {
                        "id": None,
                        "ok": False,
                        "error": {
                            "code": "INVALID_REQUEST",
                            "message": "Malformed protocol request.",
                            "details": {"errors": error.errors(include_url=False)},
                        },
                    }
                )
                continue
            if request.method == "build.start":
                thread = threading.Thread(target=execute, args=(request,), daemon=True)
                build_threads.add(thread)
                thread.start()
                build_threads = {value for value in build_threads if value.is_alive()}
            else:
                execute(request)
    finally:
        for thread in build_threads:
            thread.join(timeout=2)
        router.close()
