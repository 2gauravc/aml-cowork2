import unittest

from src.agents.businesslogic import build_ownership_tables


class OwnershipBusinessLogicTests(unittest.TestCase):
    def test_multilevel_shareholders_use_effective_percentage(self):
        result = build_ownership_tables(
            {
                "org_chart": {
                    "name": "Cropwell Bishop Creamery Limited",
                    "shareholders": [
                        {
                            "name": "SOMERSET CREAMERIES LIMITED",
                            "case_common_id": "company-1",
                            "jurisdiction_id": 1,
                            "ownership": {"shares": 100},
                            "shareholders": [
                                {
                                    "name": "Jane Creamery",
                                    "case_common_id": "person-1",
                                    "nationality_id": 1,
                                    "ownership": {"shares": 60},
                                },
                                {
                                    "name": "John Creamery",
                                    "case_common_id": "person-2",
                                    "nationality_id": 1,
                                    "ownership": {"shares": 40},
                                },
                            ],
                        }
                    ],
                }
            }
        )

        shareholders = {
            row["name"]: row
            for row in result["shareholders_over_10_percent"]
        }
        self.assertEqual(
            shareholders["SOMERSET CREAMERIES LIMITED"]["effective_shareholding_percent"],
            100,
        )
        self.assertEqual(
            shareholders["Jane Creamery"]["effective_shareholding_percent"],
            60,
        )
        self.assertEqual(
            shareholders["John Creamery"]["effective_shareholding_percent"],
            40,
        )
        self.assertEqual(
            shareholders["Jane Creamery"]["direct_shareholding_percent"],
            60,
        )

    def test_deeper_multilevel_shareholders_multiply_each_layer(self):
        result = build_ownership_tables(
            {
                "org_chart": {
                    "name": "Customer Limited",
                    "shareholders": [
                        {
                            "name": "Holdco Limited",
                            "jurisdiction_id": 1,
                            "ownership": {"shares": 80},
                            "shareholders": [
                                {
                                    "name": "Family Trust Company",
                                    "jurisdiction_id": 1,
                                    "ownership": {"shares": 50},
                                    "shareholders": [
                                        {
                                            "name": "Alex Owner",
                                            "nationality_id": 1,
                                            "ownership": {"shares": 50},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        )

        shareholders = {
            row["name"]: row["effective_shareholding_percent"]
            for row in result["shareholders_over_10_percent"]
        }
        self.assertEqual(shareholders["Holdco Limited"], 80)
        self.assertEqual(shareholders["Family Trust Company"], 40)
        self.assertEqual(shareholders["Alex Owner"], 20)


if __name__ == "__main__":
    unittest.main()
