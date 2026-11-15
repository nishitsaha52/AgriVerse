"""Verified TLS using OS trust, with an optional additional organization CA bundle."""

import atexit
import ssl
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def ssl_context(ca_bundle: str | None = None) -> ssl.SSLContext:
    # On Windows this includes the Windows certificate store. Verification and
    # hostname checks stay enabled; an organization bundle adds trusted roots.
    context = ssl.create_default_context()
    if ca_bundle:
        context.load_verify_locations(cafile=ca_bundle)
    return context


@lru_cache(maxsize=8)
def trusted_ca_file(ca_bundle: str | None = None) -> str:
    """Expose the same public CA roots to requests/botocore OTLP exporters."""
    certificates = ssl_context(ca_bundle).get_ca_certs(binary_form=True)
    if not certificates:
        raise RuntimeError("No trusted CA certificates available")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", prefix="agriverse-public-ca-", delete=False, encoding="ascii"
    ) as bundle:
        path = Path(bundle.name)
        bundle.write("".join(ssl.DER_cert_to_PEM_cert(cert) for cert in certificates))
    atexit.register(path.unlink, missing_ok=True)
    return str(path)
