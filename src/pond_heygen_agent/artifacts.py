"""Short-lived, bearer-free download capabilities for Pond MP4 artifacts."""

import hashlib
import hmac
import re
import time

ARTIFACT_PATTERN = re.compile(r"art_[0-9a-f]{40}")


class ArtifactSigner:
    def __init__(self, key, *, clock=time.time):
        if not key:
            raise ValueError("ARTIFACT_SIGNING_KEY is required")
        self.key, self.clock = key.encode(), clock

    def signature(self, artifact_id, expires):
        if not ARTIFACT_PATTERN.fullmatch(artifact_id):
            raise ValueError("Invalid artifact ID")
        return hmac.new(self.key, f"{artifact_id}:{expires}".encode(), hashlib.sha256).hexdigest()

    def verify(self, artifact_id, expires, signature):
        if not re.fullmatch(r"[0-9]{1,12}", expires) or int(expires) <= self.clock():
            raise ValueError("Expired artifact")
        expected = self.signature(artifact_id, expires)
        if not hmac.compare_digest(expected.encode(), signature.encode()):
            raise ValueError("Invalid signature")

    def url(self, base_url, artifact_id, expires):
        signature = self.signature(artifact_id, expires)
        path = f"{base_url.rstrip('/')}/artifacts/{artifact_id}"
        return f"{path}?expires={expires}&signature={signature}"
