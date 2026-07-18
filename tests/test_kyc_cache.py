import os
import tempfile
import unittest
from unittest.mock import patch

from src.backend.app import _registry_fetch_message
from src.utils.create_case import (
    KycClient,
    _TOKEN_CACHE,
    _TOKEN_CACHE_LOCK,
    create_company_case,
    get_company_detail,
    search_companies,
)
from src.utils.kyc_cache import set_cache_value


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected API call: {method} {path}")
        return FakeResponse(self.responses.pop(0))


def search_response(rawname="EXAMPLE LIMITED"):
    return {
        "companySearch": {
            "results": [
                {
                    "rawname": rawname,
                    "name": "Example Limited",
                    "registrationNumber": "123",
                }
            ]
        }
    }


def company_response(case_id=100, status_id=3):
    return {
        "caseDetail": {
            "details": {
                "common": {
                    "caseCommonId": case_id,
                    "statusId": status_id,
                    "statusName": "Ready" if status_id == 3 else "Processing",
                },
                "company": {
                    "caseCommonId": case_id,
                    "entityName": "Example Limited",
                    "countryCodeISO31662": "HK",
                },
            }
        }
    }


class KycCacheTests(unittest.TestCase):
    def test_search_companies_uses_cache_before_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "kyc-cache.json")
            with patch.dict(os.environ, {"KYC_CACHE_PATH": cache_path}):
                client = FakeClient([search_response()])

                first = search_companies("Example Limited", "HK", client=client)
                second = search_companies("Example Limited", "HK", client=client)

        self.assertEqual(first, second)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1], "/v2/Companies/search")

    def test_get_company_detail_only_caches_ready_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "kyc-cache.json")
            with patch.dict(os.environ, {"KYC_CACHE_PATH": cache_path}):
                client = FakeClient(
                    [
                        company_response(status_id=1),
                        company_response(status_id=3),
                    ]
                )

                first = get_company_detail(100, client=client)
                second = get_company_detail(100, client=client)
                third = get_company_detail(100, client=client)

        self.assertEqual(first["caseDetail"]["details"]["common"]["statusId"], 1)
        self.assertEqual(second["caseDetail"]["details"]["common"]["statusId"], 3)
        self.assertEqual(third["caseDetail"]["details"]["common"]["statusId"], 3)
        self.assertEqual(len(client.calls), 2)

    def test_create_company_case_uses_cached_case_before_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "kyc-cache.json")
            with patch.dict(os.environ, {"KYC_CACHE_PATH": cache_path}):
                client = FakeClient(
                    [
                        search_response(),
                        company_response(case_id=100, status_id=1),
                        company_response(case_id=100, status_id=3),
                    ]
                )
                first = create_company_case(
                    "Example Limited",
                    "HK",
                    client=client,
                    poll_interval_seconds=0,
                )
                second = create_company_case(
                    "Example Limited",
                    "HK",
                    client=FakeClient([]),
                    poll_interval_seconds=0,
                )

        self.assertEqual(first, second)
        self.assertEqual(first["case_id"], 100)
        self.assertTrue(first["ready"])
        self.assertEqual(
            [call[:2] for call in client.calls],
            [
                ("POST", "/v2/Companies/search"),
                ("POST", "/v2/Companies"),
                ("GET", "/v2/Companies/100"),
            ],
        )

    def test_registry_fetch_message_indicates_cache_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "kyc-cache.json")
            with patch.dict(os.environ, {"KYC_CACHE_PATH": cache_path}):
                set_cache_value(
                    "company-case",
                    ["HK", "Example Limited"],
                    {"case_id": 100, "ready": True},
                )

                message = _registry_fetch_message(
                    customer_name="Example Limited",
                    jurisdiction="HK",
                )

        self.assertEqual(message, "Fetching registry information... reading from cache")

    def test_registry_fetch_message_indicates_api_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "kyc-cache.json")
            with patch.dict(os.environ, {"KYC_CACHE_PATH": cache_path}):
                message = _registry_fetch_message(
                    customer_name="Example Limited",
                    jurisdiction="HK",
                )

        self.assertEqual(message, "Fetching registry information... calling API")


class KycTokenCacheTests(unittest.TestCase):
    def setUp(self):
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE.clear()

    def test_token_cache_is_shared_across_client_instances(self):
        with (
            patch("src.utils.create_case.requests.post") as post,
            patch("src.utils.create_case.requests.request") as request,
        ):
            post.return_value = FakeResponse({"access_token": "token-1", "expires_in": 600})
            request.return_value = FakeResponse({"ok": True})

            KycClient("https://kyc.example", "client-id", "secret").request("GET", "/one")
            KycClient("https://kyc.example", "client-id", "secret").request("GET", "/two")

        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            [call.kwargs["headers"]["Authorization"] for call in request.call_args_list],
            ["Bearer token-1", "Bearer token-1"],
        )

    def test_token_cache_refreshes_near_expiry(self):
        with (
            patch("src.utils.create_case.time.time", side_effect=[100.0, 175.0, 175.0]),
            patch("src.utils.create_case.requests.post") as post,
            patch("src.utils.create_case.requests.request") as request,
        ):
            post.side_effect = [
                FakeResponse({"access_token": "token-1", "expires_in": 100}),
                FakeResponse({"access_token": "token-2", "expires_in": 100}),
            ]
            request.return_value = FakeResponse({"ok": True})

            client = KycClient("https://kyc.example", "client-id", "secret")
            client.request("GET", "/one")
            client.request("GET", "/two")

        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            [call.kwargs["headers"]["Authorization"] for call in request.call_args_list],
            ["Bearer token-1", "Bearer token-2"],
        )

    def test_unauthorized_response_forces_token_refresh_and_retry(self):
        auth_headers = []

        def fake_request(*args, **kwargs):
            auth_headers.append(kwargs["headers"]["Authorization"])
            if len(auth_headers) == 1:
                return FakeResponse({"error": "expired"}, status_code=401)
            return FakeResponse({"ok": True})

        with (
            patch("src.utils.create_case.requests.post") as post,
            patch("src.utils.create_case.requests.request") as request,
        ):
            post.side_effect = [
                FakeResponse({"access_token": "token-1", "expires_in": 600}),
                FakeResponse({"access_token": "token-2", "expires_in": 600}),
            ]
            request.side_effect = fake_request

            response = KycClient("https://kyc.example", "client-id", "secret").request(
                "GET",
                "/one",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(auth_headers, ["Bearer token-1", "Bearer token-2"])


if __name__ == "__main__":
    unittest.main()
