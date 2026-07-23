from __future__ import annotations

from server.app import create_app
from server.browser_verify import BrowserVerificationResult
from server.codex_backend import MockCodexBackend

app = create_app(
    backend=MockCodexBackend(),
    model_lab_backend=MockCodexBackend(),
    browser_verifier=lambda _artifact: BrowserVerificationResult.passing(),
)
