from types import SimpleNamespace
import unittest

from web_app.backend.auth import ClerkTokenVerifier


class ClerkOriginTests(unittest.TestCase):
    def test_allowed_origins_star_allows_any_authorized_party(self) -> None:
        verifier = ClerkTokenVerifier(
            SimpleNamespace(
                clerk_allowed_origins=("*",),
                clerk_frontend_api_url=None,
                clerk_jwt_key=None,
                clerk_jwks_url=None,
            )
        )

        self.assertTrue(verifier._is_authorized_party_allowed("http://127.0.0.1:8002"))


if __name__ == "__main__":
    unittest.main()
