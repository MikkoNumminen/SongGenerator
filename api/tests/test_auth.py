"""Who gets in, and every reason somebody does not.

No network and no Google account: the policy is a function over a dictionary,
so each refusal can be stated as a case. That is the point of separating it
from the signature check, because these are the rules worth reading.
"""

from __future__ import annotations

import pytest
from app.auth import AuthError, Principal, decide, verify

CLIENT = "1234.apps.googleusercontent.com"
ALLOWED = frozenset({"owner@example.invalid"})


def claims(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT,
        "email": "owner@example.invalid",
        "email_verified": True,
        "name": "The Owner",
    }
    base.update(overrides)
    return base


def test_an_allowlisted_account_gets_in():
    who = decide(claims(), ALLOWED, CLIENT)
    assert who == Principal(email="owner@example.invalid", name="The Owner")


def test_an_account_not_on_the_list_is_refused():
    """The whole point. Any Google account must not be enough, because the
    pipeline takes arbitrary links and runs them on somebody's desktop."""
    with pytest.raises(AuthError, match="allowlist"):
        decide(claims(email="stranger@example.invalid"), ALLOWED, CLIENT)


def test_an_unverified_email_is_refused():
    """An allowlist keyed on an address Google has not confirmed belongs to
    the account is not an allowlist."""
    with pytest.raises(AuthError, match="verified"):
        decide(claims(email_verified=False), ALLOWED, CLIENT)


def test_a_missing_verified_flag_is_refused_not_assumed():
    with pytest.raises(AuthError, match="verified"):
        decide(claims(email_verified=None), ALLOWED, CLIENT)


def test_a_token_for_another_application_is_refused():
    """Checked here as well as in the verifier, so a misconfigured verifier
    cannot quietly accept a token minted for somebody else's app."""
    with pytest.raises(AuthError, match="different application"):
        decide(claims(aud="9999.apps.googleusercontent.com"), ALLOWED, CLIENT)


def test_a_token_from_another_issuer_is_refused():
    with pytest.raises(AuthError, match="not issued by Google"):
        decide(claims(iss="https://login.example.invalid"), ALLOWED, CLIENT)


def test_an_email_with_different_case_still_matches():
    """Addresses arrive however the user typed them into Google."""
    who = decide(claims(email="Owner@Example.Invalid"), ALLOWED, CLIENT)
    assert who.email == "owner@example.invalid"


def test_an_empty_allowlist_lets_nobody_in():
    """Misconfiguration must fail closed. An edge started with no allowlist is
    not an open edge."""
    with pytest.raises(AuthError, match="empty allowlist"):
        decide(claims(), frozenset(), CLIENT)


def test_no_client_id_lets_nobody_in():
    with pytest.raises(AuthError, match="no Google client"):
        decide(claims(), ALLOWED, "")


def test_a_token_with_no_email_is_refused():
    with pytest.raises(AuthError, match="no email"):
        decide(claims(email=""), ALLOWED, CLIENT)


# ---------------------------------------------------------------------------
# The signature step, with the verifier injected
# ---------------------------------------------------------------------------

def test_an_absent_token_is_refused_without_calling_the_verifier():
    called = False

    def verifier(token: str, client_id: str) -> dict[str, object]:
        nonlocal called
        called = True
        return claims()

    with pytest.raises(AuthError, match="no credentials"):
        verify("", ALLOWED, CLIENT, verifier)
    assert called is False


def test_a_verifier_failure_becomes_a_refusal_not_a_crash():
    """Whatever the library raises on a bad signature, the caller gets a
    refusal it can show, not a stack trace."""
    def verifier(token: str, client_id: str) -> dict[str, object]:
        raise ValueError("Token expired")

    with pytest.raises(AuthError, match="could not be verified"):
        verify("something", ALLOWED, CLIENT, verifier)


def test_the_policy_still_applies_after_a_good_signature():
    """A validly signed token from an account nobody allowed is still refused.
    Signature and permission are different questions."""
    def verifier(token: str, client_id: str) -> dict[str, object]:
        return claims(email="stranger@example.invalid")

    with pytest.raises(AuthError, match="allowlist"):
        verify("valid-token", ALLOWED, CLIENT, verifier)


def test_the_verifier_is_told_which_application_to_expect():
    seen: list[str] = []

    def verifier(token: str, client_id: str) -> dict[str, object]:
        seen.append(client_id)
        return claims()

    verify("t", ALLOWED, CLIENT, verifier)
    assert seen == [CLIENT]
