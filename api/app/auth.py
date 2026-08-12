"""Who is allowed to use this, checked here rather than assumed from the URL.

The edge is reachable over a Tailscale Funnel address. That address is not a
secret and must never be the thing standing between the pipeline and the
internet: the tool takes arbitrary links and runs them on somebody's desktop,
so an unauthenticated caller must be turned away by a check, not by nobody
having guessed the hostname.

The choice made here, over putting oauth2-proxy in front of everything:

- The interesting part stays in the application, which is where the target
  stack would put it too, and where it can be read and tested.
- One fewer service to keep alive on a machine that is already often off.
- `/health` has to answer without a token, because the front end uses it to
  decide whether the backend is reachable at all. A proxy in front of
  everything would either block that or need a hole punched in it, and a hole
  in the thing doing your authentication is worth avoiding.

The split below is deliberate. `decide` is the policy, pure and testable with
no network and no Google. `verify` is the part that needs Google's keys, and it
takes the verifier as an argument so the policy can be exercised without it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Google signs its ID tokens under one of these. Checked because a token from
# somewhere else, however well formed, says nothing about a Google account.
_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class AuthError(Exception):
    """Refused. The message is safe to show a caller."""


@dataclass(frozen=True)
class Principal:
    """The person behind a request, once their token has been believed."""

    email: str
    name: str | None = None


def identify(claims: dict[str, object], client_id: str) -> Principal:
    """Who this token says they are, with no view on whether they may be here.

    Split out from `decide` for the one case that needs the identity without
    the policy: somebody redeeming an invitation is by definition not on the
    allowlist yet, and the whole point of the invitation is to put them there.
    Every check on the token itself still applies; the only thing skipped is
    the question the invitation is the answer to.
    """
    if not client_id:
        raise AuthError("this edge has no Google client configured, so nobody can sign in")

    issuer = str(claims.get("iss", ""))
    if issuer not in _ISSUERS:
        raise AuthError("that token was not issued by Google")

    # Belt and braces: a verifier is asked to check the audience, and checking
    # it again here means a misconfigured verifier cannot quietly accept a
    # token minted for somebody else's application.
    audience = str(claims.get("aud", ""))
    if audience != client_id:
        raise AuthError("that token was issued for a different application")

    email = str(claims.get("email", "")).strip().lower()
    if not email:
        raise AuthError("that token carries no email address")

    # Google sets this false for an address it has not confirmed belongs to
    # the account. An allowlist keyed on an unverified address is not one.
    if claims.get("email_verified") is not True:
        raise AuthError("that Google account has not verified its email address")

    name = claims.get("name")
    return Principal(email=email, name=str(name) if name else None)


def decide(claims: dict[str, object], allowed: frozenset[str],
           client_id: str) -> Principal:
    """Turn verified claims into a principal, or refuse and say why.

    Pure. Everything here is a check on a dictionary, so the rules that decide
    who gets in can be read and tested without a network or a Google account.
    """
    if not allowed:
        raise AuthError("this edge has an empty allowlist, so nobody can sign in")
    who = identify(claims, client_id)
    if who.email not in allowed:
        raise AuthError("that account is not on this edge's allowlist")
    return who


def verify(token: str, allowed: frozenset[str], client_id: str,
           verifier: Callable[[str, str], dict[str, object]]) -> Principal:
    """Check a token's signature, then apply the policy.

    `verifier` does the cryptography and is injected so this module has no
    import-time dependency on Google's libraries and no network in its tests.
    """
    if not token:
        raise AuthError("no credentials were presented")
    try:
        claims = verifier(token, client_id)
    except AuthError:
        raise
    except Exception as exc:  # the verifier's own failures, whatever library
        raise AuthError(f"that token could not be verified ({exc})") from exc
    return decide(claims, allowed, client_id)


def verify_identity(token: str, client_id: str,
                    verifier: Callable[[str, str], dict[str, object]]) -> Principal:
    """`verify`, without the allowlist. For redeeming an invitation."""
    if not token:
        raise AuthError("no credentials were presented")
    try:
        claims = verifier(token, client_id)
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"that token could not be verified ({exc})") from exc
    return identify(claims, client_id)


def google_verifier(token: str, client_id: str) -> dict[str, object]:
    """The real one. Imported lazily so the rest stays testable without it."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return dict(id_token.verify_oauth2_token(
        token, google_requests.Request(), client_id))
