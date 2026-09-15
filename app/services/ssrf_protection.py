import ipaddress
import socket
from urllib.parse import urlparse


class SSRFValidationError(ValueError):
    """Raised when a URL fails SSRF safety checks."""
    pass


BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "169.254.169.254",
    "instance-data",
}


def validate_target_url(raw_url: str) -> str:
    """Validates that a URL is safe from Server-Side Request Forgery (SSRF).
    
    Rules:
    - Only http/https schemes allowed.
    - Hostnames cannot be local or cloud metadata endpoints.
    - Resolved IP cannot be loopback, private (RFC1918), link-local, or reserved.
    """
    cleaned = raw_url.strip()
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        cleaned = "https://" + cleaned

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise SSRFValidationError(f"Invalid scheme '{parsed.scheme}'. Only http and https are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL does not contain a valid hostname.")

    hostname_lower = hostname.lower().strip()
    if hostname_lower in BLOCKED_HOSTNAMES or hostname_lower.endswith(".local"):
        raise SSRFValidationError(f"Target host '{hostname}' is blocked for security reasons (SSRF Protection).")

    # Resolve IP address to detect internal/private network routing
    try:
        addr_info = socket.getaddrinfo(hostname_lower, None)
        for entry in addr_info:
            ip_str = entry[4][0]
            ip_obj = ipaddress.ip_address(ip_str)

            if (
                ip_obj.is_loopback
                or ip_obj.is_private
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_str in ("0.0.0.0", "169.254.169.254", "::1")
            ):
                raise SSRFValidationError(
                    f"Target host '{hostname}' resolves to restricted internal IP {ip_str} (SSRF Protection)."
                )
    except socket.gaierror:
        # If DNS resolution fails, let standard HTTP client handle network error
        pass

    return cleaned
