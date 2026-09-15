import json
import re
import shlex
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from app.models.tracked_api import HttpMethod


@dataclass
class ResolvedTarget:
    url: str
    base_url: str
    endpoint_path: str
    method: HttpMethod
    headers: Dict[str, str]
    payload: Optional[Dict[str, Any]]
    inferred_name: str
    auth_token: Optional[str]
    is_sandbox: bool
    detected_provider: str


def parse_curl_command(curl_str: str) -> Dict[str, Any]:
    """Extracts URL, method, headers, and body from a cURL command."""
    cleaned = curl_str.strip()
    try:
        tokens = shlex.split(cleaned)
    except Exception:
        tokens = cleaned.split()

    url = ""
    method = "GET"
    headers: Dict[str, str] = {}
    data_str = ""

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.lower() == "curl":
            i += 1
            continue

        if token in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 2
            continue

        if token in ("-H", "--header") and i + 1 < len(tokens):
            header_val = tokens[i + 1]
            if ":" in header_val:
                k, v = header_val.split(":", 1)
                headers[k.strip()] = v.strip()
            i += 2
            continue

        if token in ("-d", "--data", "--data-raw", "--data-binary") and i + 1 < len(tokens):
            data_str = tokens[i + 1]
            method = "POST"
            i += 2
            continue

        if token.startswith("http://") or token.startswith("https://"):
            url = token.strip("'\"")
            i += 1
            continue

        i += 1

    payload = None
    if data_str:
        try:
            payload = json.loads(data_str)
        except Exception:
            payload = None

    return {
        "url": url,
        "method": method,
        "headers": headers,
        "payload": payload
    }


def resolve_api_input(
    raw_input: str,
    method_override: Optional[HttpMethod] = None,
    auth_token_override: Optional[str] = None
) -> ResolvedTarget:
    """Intelligently resolves any raw input into an actionable target.
    
    Supports:
    1. Raw API Keys:
       - Google Gemini API Key (`AIza...`) -> `https://generativelanguage.googleapis.com/v1beta/models?key=...`
       - OpenAI Key (`sk-...`, `sk-proj-...`) -> `https://api.openai.com/v1/models`
       - Anthropic Claude Key (`sk-ant-...`) -> `https://api.anthropic.com/v1/models`
       - GitHub PAT (`ghp_...`, `github_pat_...`) -> `https://api.github.com/user`
       - Stripe Key (`sk_test_...`, `sk_live_...`, `rk_...`) -> `https://api.stripe.com/v1/charges`
    2. cURL commands (extracts method, headers, payload, URL)
    3. AI APIs requiring default payloads (Gemini generateContent, OpenAI chat completions)
    4. Naked domains / paths (auto-prepends https://)
    """
    cleaned = raw_input.strip()
    headers: Dict[str, str] = {}
    payload: Optional[Dict[str, Any]] = None
    auth_token: Optional[str] = auth_token_override
    detected_provider = "Custom API"
    inferred_name = "Target API"
    method = method_override or HttpMethod.GET
    is_sandbox = False

    # 1. Detect Raw API Key Patterns
    if cleaned.startswith("AIza") and len(cleaned) >= 30 and not cleaned.startswith("http"):
        # Google Gemini API Key
        detected_provider = "Google Gemini"
        inferred_name = "Google Gemini Models API"
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={cleaned}"
        auth_token = cleaned
        method = HttpMethod.GET

    elif (cleaned.startswith("sk-") or cleaned.startswith("sk-proj-")) and not cleaned.startswith("sk-ant-") and not cleaned.startswith("http"):
        # OpenAI API Key
        detected_provider = "OpenAI"
        inferred_name = "OpenAI Models API"
        url = "https://api.openai.com/v1/models"
        auth_token = cleaned
        headers["Authorization"] = f"Bearer {cleaned}"
        method = HttpMethod.GET

    elif cleaned.startswith("sk-ant-") and not cleaned.startswith("http"):
        # Anthropic Claude API Key
        detected_provider = "Anthropic Claude"
        inferred_name = "Anthropic Claude Models API"
        url = "https://api.anthropic.com/v1/models"
        auth_token = cleaned
        headers["x-api-key"] = cleaned
        headers["anthropic-version"] = "2023-06-01"
        method = HttpMethod.GET

    elif (cleaned.startswith("ghp_") or cleaned.startswith("github_pat_")) and not cleaned.startswith("http"):
        # GitHub Access Token
        detected_provider = "GitHub"
        inferred_name = "GitHub REST API"
        url = "https://api.github.com/user"
        auth_token = cleaned
        headers["Authorization"] = f"Bearer {cleaned}"
        method = HttpMethod.GET

    elif (cleaned.startswith("sk_test_") or cleaned.startswith("sk_live_") or cleaned.startswith("rk_")) and not cleaned.startswith("http"):
        # Stripe API Key
        detected_provider = "Stripe"
        inferred_name = "Stripe Charges Sandbox"
        url = "https://api.stripe.com/v1/charges"
        auth_token = cleaned
        headers["Authorization"] = f"Bearer {cleaned}"
        method = HttpMethod.GET
        is_sandbox = True

    # 2. Detect cURL command
    elif cleaned.lower().startswith("curl"):
        curl_info = parse_curl_command(cleaned)
        url = curl_info["url"]
        headers.update(curl_info["headers"])
        payload = curl_info["payload"]
        if curl_info.get("method"):
            try:
                method = HttpMethod(curl_info["method"])
            except ValueError:
                method = HttpMethod.POST if payload else HttpMethod.GET

        # Check for Authorization header in curl
        for hk, hv in curl_info["headers"].items():
            if hk.lower() == "authorization" and hv.lower().startswith("bearer "):
                auth_token = hv[7:].strip()
            elif hk.lower() == "x-api-key":
                auth_token = hv.strip()

    else:
        # Standard URL or Domain
        url = cleaned
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"

    # Apply auth token if given
    if auth_token and "Authorization" not in headers and not url.startswith("https://generativelanguage.googleapis.com"):
        headers["Authorization"] = f"Bearer {auth_token}"

    # Parse final URL structure
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    endpoint_path = parsed.path or "/"
    if parsed.query:
        endpoint_path += f"?{parsed.query}"

    # Provider & Inferred Name Detection from Host/Path
    netloc_lower = parsed.netloc.lower()
    path_lower = parsed.path.lower()

    if "googleapis.com" in netloc_lower or "generativelanguage" in netloc_lower:
        detected_provider = "Google Gemini"
        if "generatecontent" in path_lower:
            inferred_name = "Google Gemini GenerateContent API"
            method = HttpMethod.POST
            is_sandbox = True
            if not payload:
                payload = {
                    "contents": [{"parts": [{"text": "Health check and contract validation probe"}]}]
                }
        else:
            inferred_name = "Google Gemini Models API"

    elif "openai.com" in netloc_lower:
        detected_provider = "OpenAI"
        if "chat/completions" in path_lower:
            inferred_name = "OpenAI Chat Completions API"
            method = HttpMethod.POST
            is_sandbox = True
            if not payload:
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5
                }
        else:
            inferred_name = "OpenAI Models API"

    elif "anthropic.com" in netloc_lower:
        detected_provider = "Anthropic Claude"
        headers["anthropic-version"] = headers.get("anthropic-version", "2023-06-01")
        if "messages" in path_lower:
            inferred_name = "Anthropic Claude Messages API"
            method = HttpMethod.POST
            is_sandbox = True
            if not payload:
                payload = {
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ping"}]
                }
        else:
            inferred_name = "Anthropic Claude Models API"

    elif "stripe.com" in netloc_lower:
        detected_provider = "Stripe"
        inferred_name = "Stripe API"
        is_sandbox = True

    elif "github.com" in netloc_lower:
        detected_provider = "GitHub"
        inferred_name = "GitHub REST API"

    elif inferred_name == "Target API":
        parts = parsed.netloc.split(".")
        host_slug = parts[-2].capitalize() if len(parts) >= 2 else parsed.netloc
        path_slug = parsed.path.strip("/").replace("/", " ").replace("-", " ").replace("_", " ").title()
        inferred_name = f"{host_slug} {path_slug}" if path_slug else f"{host_slug} Root API"

    if any(k in url.lower() for k in ["test", "sandbox", "staging", "dev", "mock"]):
        is_sandbox = True

    return ResolvedTarget(
        url=url,
        base_url=base_url,
        endpoint_path=endpoint_path,
        method=method,
        headers=headers,
        payload=payload,
        inferred_name=inferred_name,
        auth_token=auth_token,
        is_sandbox=is_sandbox,
        detected_provider=detected_provider
    )
