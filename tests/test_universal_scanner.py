import pytest
from app.models.tracked_api import HttpMethod
from app.services.universal_scanner import resolve_api_input, parse_curl_command


def test_gemini_api_key_resolution():
    gemini_key = "AIzaSyCwAi_bJ8NKuH4dn2gudySh03riLZeHEIM"
    target = resolve_api_input(gemini_key)
    assert target.detected_provider == "Google Gemini"
    assert "generativelanguage.googleapis.com" in target.url
    assert "key=AIzaSy" in target.url
    assert target.inferred_name == "Google Gemini Models API"
    assert target.method == HttpMethod.GET
    assert target.auth_token == gemini_key


def test_openai_api_key_resolution():
    openai_key = "sk-proj-1234567890abcdef1234567890abcdef"
    target = resolve_api_input(openai_key)
    assert target.detected_provider == "OpenAI"
    assert target.url == "https://api.openai.com/v1/models"
    assert target.headers["Authorization"] == f"Bearer {openai_key}"
    assert target.method == HttpMethod.GET


def test_anthropic_api_key_resolution():
    claude_key = "sk-ant-api03-abcdef123456789"
    target = resolve_api_input(claude_key)
    assert target.detected_provider == "Anthropic Claude"
    assert target.url == "https://api.anthropic.com/v1/models"
    assert target.headers["x-api-key"] == claude_key
    assert target.headers["anthropic-version"] == "2023-06-01"


def test_github_token_resolution():
    gh_token = "ghp_1234567890abcdef1234567890abcdef"
    target = resolve_api_input(gh_token)
    assert target.detected_provider == "GitHub"
    assert target.url == "https://api.github.com/user"
    assert target.headers["Authorization"] == f"Bearer {gh_token}"


def test_stripe_key_resolution():
    stripe_key = "sk_test_51AbcDef123456"
    target = resolve_api_input(stripe_key)
    assert target.detected_provider == "Stripe"
    assert target.url == "https://api.stripe.com/v1/charges"
    assert target.is_sandbox is True


def test_curl_command_parsing():
    curl_cmd = (
        'curl -X POST https://api.openai.com/v1/chat/completions '
        '-H "Authorization: Bearer sk-secret" '
        '-H "Content-Type: application/json" '
        '-d \'{"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}\''
    )
    target = resolve_api_input(curl_cmd)
    assert target.detected_provider == "OpenAI"
    assert target.url == "https://api.openai.com/v1/chat/completions"
    assert target.method == HttpMethod.POST
    assert target.headers["Authorization"] == "Bearer sk-secret"
    assert target.payload == {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


def test_gemini_generate_content_payload_auto_injection():
    gemini_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=dummy"
    target = resolve_api_input(gemini_url)
    assert target.detected_provider == "Google Gemini"
    assert target.method == HttpMethod.POST
    assert target.payload is not None
    assert "contents" in target.payload
