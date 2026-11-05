"""Testes com os exemplos da documentação oficial dos inference hooks (lidos em 2026-10-15)."""
import base64
import json

import pytest

from promptshield_inference_hooks import SignatureError, allow, deny, parse_frame, verify
from promptshield_inference_hooks.signature import sign

# exemplo de corpo copiado da documentação ("An example request body")
DOC_EXAMPLE = {
    "type": "prompt", "request_id": "req_abc123", "tenant_id": "11111111-1111-1111-1111-111111111111",
    "actor": {"type": "user", "id": "user_01AbCdEfGhIjKlMnOpQrStUv", "email_address": "alice@example.com"},
    "source": {"application": "claude-ai"}, "session_id": "22222222-2222-2222-2222-222222222222", "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Summarize the attached report."},
        {"type": "attachment", "file_name": "q2-report.pdf", "media_type": "application/pdf", "size_bytes": 48213,
         "text": "Q2 revenue grew 14% quarter over quarter..."}]}],
    "metadata": {},
}
# segredo com '+' e '/' na base64 (o erro clássico é usar decodificador URL-safe)
RAW_KEY = bytes([0xFB, 0xEF, 0xBE, 0xFF, 0xFE, 0x3E] * 6)
SECRET = "whsec_" + base64.b64encode(RAW_KEY).decode()
assert "+" in SECRET or "/" in SECRET
NOW = 1_800_000_000


def signed(body: bytes, secret=SECRET, ts=NOW, mid="req_abc123"):
    return {"Webhook-Id": mid, "Webhook-Timestamp": str(ts), "Webhook-Signature": sign(secret, mid, ts, body)}


def raw(frame=DOC_EXAMPLE):
    return json.dumps(frame).encode()


# ---------- assinatura ----------
def test_valid_signature_accepts_and_headers_are_case_insensitive():
    b = raw()
    verify([SECRET], signed(b), b, now=NOW)
    verify([SECRET], {k.lower(): v for k, v in signed(b).items()}, b, now=NOW)


def test_tampered_body_wrong_secret_and_missing_headers_are_rejected():
    b = raw()
    h = signed(b)
    with pytest.raises(SignatureError, match="inválida"):
        verify([SECRET], h, b + b" ", now=NOW)
    other = "whsec_" + base64.b64encode(b"x" * 32).decode()
    with pytest.raises(SignatureError, match="inválida"):
        verify([other], h, b, now=NOW)
    with pytest.raises(SignatureError, match="sem assinatura"):
        verify([SECRET], {}, b, now=NOW)
    with pytest.raises(SignatureError, match="sem assinatura"):
        verify([SECRET], {"webhook-id": "x", "webhook-timestamp": str(NOW)}, b, now=NOW)


def test_timestamp_tolerance_is_five_minutes_both_ways():
    b = raw()
    verify([SECRET], signed(b, ts=NOW - 299), b, now=NOW)
    verify([SECRET], signed(b, ts=NOW + 299), b, now=NOW)
    for ts in (NOW - 301, NOW + 301):
        with pytest.raises(SignatureError, match="tolerância"):
            verify([SECRET], signed(b, ts=ts), b, now=NOW)
    with pytest.raises(SignatureError, match="timestamp inválido"):
        verify([SECRET], {**signed(b), "webhook-timestamp": "ontem"}, b, now=NOW)


def test_multiple_signatures_and_secret_rotation_accept_old_or_new():
    b = raw()
    new = "whsec_" + base64.b64encode(b"n" * 32).decode()
    h_old = signed(b, secret=SECRET)
    verify([new, SECRET], h_old, b, now=NOW)                                   # estragglers com o segredo antigo
    verify([new, SECRET], signed(b, secret=new), b, now=NOW)
    two = {**h_old, "webhook-signature": "v1,AAAA " + h_old["Webhook-Signature"]}  # vários valores: basta um casar
    verify([SECRET], two, b, now=NOW)
    with pytest.raises(SignatureError):
        verify([], h_old, b, now=NOW)


def test_urlsafe_decoding_would_give_the_wrong_key():
    b = raw()
    url_safe = SECRET.replace("+", "-").replace("/", "_")
    with pytest.raises(SignatureError):
        verify([url_safe], signed(b), b, now=NOW)  # base64 padrão estrito: não aceita URL-safe


def test_malformed_secret_and_non_ascii_signature_do_not_crash():
    b = raw()
    with pytest.raises(SignatureError):
        verify(["whsec_@@@não-é-base64"], signed(b), b, now=NOW)
    bad = {**signed(b), "webhook-signature": "v1,ação"}
    with pytest.raises(SignatureError):
        verify([SECRET], bad, b, now=NOW)


# ---------- frames ----------
def test_doc_example_prompt_frame_becomes_prompt_and_file_upload():
    f = parse_frame(raw())
    assert f.known and not f.is_config_test and f.application == "claude-ai"
    assert f.actor_email == "alice@example.com" and f.request_id == "req_abc123"
    assert [b.kind for b in f.blocks] == ["prompt", "file_upload"]
    assert f.blocks[0].text == "Summarize the attached report."
    assert f.blocks[1].tool_input == {"file_name": "q2-report.pdf", "media_type": "application/pdf", "size_bytes": 48213}
    assert all(b.fingerprint for b in f.blocks) and len({b.fingerprint for b in f.blocks}) == 2


def test_fingerprints_are_stable_and_content_dependent():
    a, b = parse_frame(raw()), parse_frame(raw())
    assert [x.fingerprint for x in a.blocks] == [x.fingerprint for x in b.blocks]
    edited = json.loads(raw())
    edited["messages"][0]["content"][0]["text"] = "Summarize the report."
    assert parse_frame(json.dumps(edited).encode()).blocks[0].fingerprint != a.blocks[0].fingerprint


def test_unknown_type_config_test_unknown_blocks_and_roles_are_tolerated():
    assert parse_frame(raw({**DOC_EXAMPLE, "type": "response"})).known is False
    assert parse_frame(raw({**DOC_EXAMPLE, "type": "response"})).blocks == []
    t = parse_frame(raw({**DOC_EXAMPLE, "source": {"application": "config-test"}}))
    assert t.is_config_test and t.blocks == []
    odd = {**DOC_EXAMPLE, "novo_campo": 1, "actor": {"type": "service", "id": None}, "messages": [
        {"role": "system", "content": [{"type": "text", "text": "ignorado"}]},
        {"role": "user", "content": [{"type": "hologram", "x": 1}, {"type": "text", "text": "oi"}]}]}
    f = parse_frame(raw(odd))
    assert [b.text for b in f.blocks] == ["oi"] and f.actor_id is None


def test_attachment_without_text_is_counted_not_inspected():
    frame = {**DOC_EXAMPLE, "messages": [{"role": "user", "content": [
        {"type": "attachment", "file_name": None, "media_type": "image/png", "size_bytes": 10, "text": None}]}]}
    f = parse_frame(raw(frame))
    assert f.blocks == [] and f.skipped_attachments == 1


def test_assistant_tool_use_and_tool_result_blocks_in_a_prompt_frame():
    frame = {**DOC_EXAMPLE, "source": {"application": "claude-code"}, "messages": [
        {"role": "user", "content": [{"type": "text", "text": "liste os arquivos"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "vou listar"},
                                          {"type": "tool_use", "id": "toolu_1", "tool_name": "bash", "input": {"command": "ls -la"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "tool_name": "bash", "content": "a.txt", "is_error": False}]}]}
    f = parse_frame(raw(frame))
    assert [(b.kind, b.role) for b in f.blocks] == [("prompt", "user"), ("response", "assistant"), ("tool_call", "assistant"), ("tool_result", "user")]
    call = f.blocks[2]
    assert call.tool_name == "bash" and call.tool_input == {"command": "ls -la"}


def test_tool_call_frame_reads_only_the_last_message_and_matches_prompt_frame_fingerprint():
    use = {"type": "tool_use", "id": "toolu_1", "tool_name": "bash", "input": {"command": "cat ~/.aws/credentials"}}
    tool_frame = {**DOC_EXAMPLE, "type": "tool_call", "request_id": "req_tool", "messages": [
        {"role": "user", "content": [{"type": "text", "text": "mensagem antiga que deve ser ignorada"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "vou ler"}, {**use, "tool_info": {"type": "client", "tool_type": "bash_20250124"}}]}]}
    f = parse_frame(raw(tool_frame))
    assert f.type == "tool_call" and [b.kind for b in f.blocks] == ["tool_call"]
    later = parse_frame(raw({**DOC_EXAMPLE, "messages": [{"role": "assistant", "content": [use]}]}))
    assert later.blocks[0].fingerprint == f.blocks[0].fingerprint  # a mesma chamada não é reavaliada no turno seguinte


def test_invalid_bodies_raise_value_error():
    for body in (b"", b"nao e json", b"[1,2]", b'"x"', b"\xff\xfe"):
        with pytest.raises(ValueError):
            parse_frame(body)


# ---------- veredito ----------
def test_verdict_shapes_and_limits():
    assert allow() == {"action": "allow"}
    d = deny("x" * 900, "ps:abc123")
    assert d["action"] == "deny" and len(d["deny_reason"]) == 500 and d["reference_id"] == "ps:abc123"
    assert "reference_id" not in deny("r", "tem espaço")
    assert "reference_id" not in deny("r", "a" * 51)
    assert "reference_id" not in deny("r")
