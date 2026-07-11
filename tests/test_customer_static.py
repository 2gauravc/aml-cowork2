import unittest

from tools.customer_static import clean_customer_static_response


def company_response(properties, *, case_id=123, entity_name="Example Limited"):
    return {
        "caseDetail": {
            "details": {
                "common": {
                    "caseCommonId": case_id,
                    "statusName": "Active",
                },
                "company": {
                    "caseCommonId": case_id,
                    "entityName": entity_name,
                    "countryCodeISO31662": "HK",
                    "properties": properties,
                },
                "caseAddress": {
                    "address": "1 Test Street",
                    "countryCodeISO31662": "HK",
                },
            }
        }
    }


class CustomerStaticCleanerTests(unittest.TestCase):
    def test_share_capital_displays_as_paid_up_capital_with_source(self):
        result = clean_customer_static_response(
            company_response({"Share Capital": "HKD 10,000"}),
            case_id=123,
        )

        profile = result["customer_static"]
        self.assertEqual(profile["display_capital"]["label"], "Paid-up Capital")
        self.assertEqual(profile["display_capital"]["value"], "HKD 10,000")
        self.assertEqual(profile["display_capital"]["source"]["field"], "Share Capital")
        self.assertEqual(
            profile["display_capital"]["source"]["api"],
            "KYC.com GET /v2/Companies/123",
        )
        self.assertEqual(
            profile["source"]["paid_up_capital"],
            profile["display_capital"]["source"],
        )
        self.assertNotIn("field_sources", profile)

    def test_capital_amount_alias_is_detected(self):
        result = clean_customer_static_response(
            company_response({"Capital Amount": "SGD 50,000"}),
            case_id=456,
        )

        profile = result["customer_static"]
        self.assertEqual(profile["display_capital"]["label"], "Paid-up Capital")
        self.assertEqual(profile["display_capital"]["value"], "SGD 50,000")
        self.assertEqual(profile["display_capital"]["source_label"], "Capital Amount")

    def test_missing_capital_is_not_fabricated(self):
        result = clean_customer_static_response(
            company_response(
                {
                    "Company Type": "Private Company Limited by Shares",
                    "Activity Type": "10512 - Butter and cheese production",
                    "Creation Date": "15/01/1941",
                    "Company Status": "Active",
                    "Registration Number": "00364890",
                },
                case_id=1000000690,
                entity_name="CROPWELL BISHOP CREAMERY LIMITED",
            ),
            case_id=1000000690,
        )

        profile = result["customer_static"]
        self.assertNotIn("display_capital", profile)
        self.assertNotIn("paid_up_capital", profile.get("source", {}))
        self.assertEqual(
            profile["source"]["registration_number"]["field"],
            "Registration Number",
        )


if __name__ == "__main__":
    unittest.main()
