import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from src.backend.app import DocumentPresignRequest, SESSIONS, presign_document


class BackendDocumentTests(unittest.TestCase):
    def setUp(self):
        SESSIONS.clear()

    def tearDown(self):
        SESSIONS.clear()

    def test_presign_document_validates_session_document_key(self):
        SESSIONS["s1"] = {
            "session_id": "s1",
            "messages": [],
            "documents": [
                {
                    "name": "passport.pdf",
                    "storage": {
                        "bucket": "onbo-bkt",
                        "key": "generated_documents/case-1/passport/passport.pdf",
                    },
                }
            ],
        }

        with patch(
            "src.backend.app.presign_document_url",
            return_value="https://example.com/presigned",
        ) as presign:
            body = asyncio.run(
                presign_document(
                    DocumentPresignRequest(
                        session_id="s1",
                        document_key="generated_documents/case-1/passport/passport.pdf",
                    )
                )
            )

        self.assertEqual(body["url"], "https://example.com/presigned")
        self.assertEqual(body["expires_in_seconds"], 900)
        presign.assert_called_once_with(
            bucket="onbo-bkt",
            key="generated_documents/case-1/passport/passport.pdf",
            expires_in_seconds=900,
        )

    def test_presign_document_rejects_unknown_key(self):
        SESSIONS["s1"] = {
            "session_id": "s1",
            "messages": [],
            "documents": [
                {
                    "name": "passport.pdf",
                    "storage": {
                        "bucket": "onbo-bkt",
                        "key": "generated_documents/case-1/passport/passport.pdf",
                    },
                }
            ],
        }

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                presign_document(
                    DocumentPresignRequest(
                        session_id="s1",
                        document_key="generated_documents/case-2/passport/passport.pdf",
                    )
                )
            )

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
