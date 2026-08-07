"""Face ID / passkeys (WebAuthn) voor de PWA — STRIKT ADDITIEF.

Bovenop het wachtwoord-login. Wachtwoord blijft altijd de fallback: faalt hier
iets (library, apparaat, iOS-PWA-eigenaardigheid), dan log je gewoon met
wachtwoord in. Daarom:
  * py_webauthn wordt LUI geïmporteerd (binnen de functies) → een ontbrekende of
    kapotte library kan de app-boot nooit slopen.
  * Credentials = alleen PUBLIEKE sleutels, in de GitHub-store (intake_store) →
    overleven Render-deploys (lokale schijf reset daar bij elke deploy).

Eén gedeelde inloggebruiker (APP_USER, bv. 'bebetter'); elk apparaat registreert
zijn eigen passkey onder die gebruiker, dus Jip én Remco kunnen elk hun toestel
koppelen en met Face ID/Touch ID ontgrendelen.
"""
from __future__ import annotations

import base64
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import intake_store                                    # veilig: geen webauthn-import

RP_NAME = "BeBetter Coaching"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    from webauthn import base64url_to_bytes   # lui
    return base64url_to_bytes(s)


def rp_id_from_host(host: str) -> str:
    """RP ID = hostnaam zonder poort (localhost:8000 -> localhost)."""
    return (host or "").split(":")[0] or "localhost"


def _creds() -> dict:
    try:
        return intake_store.load_webauthn() or {}
    except Exception:
        return {}


def has_credentials(user: str) -> bool:
    return bool(_creds().get(user))


def registration_options(user: str, rp_id: str):
    """(options_json, challenge_bytes) voor het koppelen van een nieuw apparaat."""
    import webauthn
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria,
        AuthenticatorAttachment, ResidentKeyRequirement, UserVerificationRequirement,
        PublicKeyCredentialDescriptor)
    bestaand = _creds().get(user, [])
    opts = webauthn.generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME, user_name=user, user_id=user.encode(),
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,   # Face ID/Touch ID
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=_unb64(c["id"])) for c in bestaand],
    )
    return webauthn.options_to_json(opts), opts.challenge


def verify_registration(user: str, credential, challenge: bytes, rp_id: str, origin: str) -> bool:
    import webauthn
    ver = webauthn.verify_registration_response(
        credential=credential, expected_challenge=challenge,
        expected_rp_id=rp_id, expected_origin=origin)
    data = _creds()
    data.setdefault(user, []).append({
        "id": _b64(ver.credential_id),
        "public_key": _b64(ver.credential_public_key),
        "sign_count": ver.sign_count,
        "added": time.strftime("%Y-%m-%d"),
    })
    ok, _ = intake_store.save_webauthn(data)
    return ok


def authentication_options(user: str, rp_id: str):
    """(options_json, challenge_bytes) voor ontgrendelen met een gekoppeld apparaat."""
    import webauthn
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
    creds = _creds().get(user, [])
    opts = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=_unb64(c["id"])) for c in creds],
        user_verification=UserVerificationRequirement.PREFERRED)
    return webauthn.options_to_json(opts), opts.challenge


def verify_authentication(user: str, credential, challenge: bytes, rp_id: str, origin: str) -> bool:
    import webauthn
    data = _creds()
    creds = data.get(user, [])
    cid = credential.get("id") or credential.get("rawId")
    match = None
    for c in creds:
        try:
            if _unb64(c["id"]) == _unb64(cid):
                match = c
                break
        except Exception:
            continue
    if not match:
        return False
    ver = webauthn.verify_authentication_response(
        credential=credential, expected_challenge=challenge,
        expected_rp_id=rp_id, expected_origin=origin,
        credential_public_key=_unb64(match["public_key"]),
        credential_current_sign_count=match.get("sign_count", 0))
    match["sign_count"] = ver.new_sign_count      # replay-bescherming
    intake_store.save_webauthn(data)
    return True
