import unittest

from fastapi import HTTPException

from api.routes.settings import (
    CredentialsPayload,
    _looks_like_masked_credential,
    _reject_masked_credentials,
)


class CredentialSaveSafetyTests(unittest.TestCase):
    def test_recognizes_display_only_secret_shapes(self):
        self.assertTrue(_looks_like_masked_credential("abcd…wxyz"))
        self.assertTrue(_looks_like_masked_credential("••••••••"))
        self.assertTrue(_looks_like_masked_credential("set"))
        self.assertFalse(_looks_like_masked_credential("complete-production-token"))

    def test_rejects_masked_secret_before_it_can_be_persisted(self):
        payload = CredentialsPayload(tradier_market_api_key="abcd…wxyz")

        with self.assertRaises(HTTPException) as raised:
            _reject_masked_credentials(payload)

        self.assertEqual(400, raised.exception.status_code)
        self.assertIn("complete new credential", raised.exception.detail)

    def test_untouched_secret_fields_remain_none(self):
        payload = CredentialsPayload(tradier_live_account_id="6YB84763")

        _reject_masked_credentials(payload)

        self.assertIsNone(payload.tradier_market_api_key)


if __name__ == "__main__":
    unittest.main()
