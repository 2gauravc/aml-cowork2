"""Ensure unsupported AML fields from KYC responses never enter CDD state."""

import json

from src.tools.members import clean_members_response
from src.tools.orgchart import clean_org_chart_response


def test_member_normalization_excludes_kyc_aml_fields() -> None:
    result = clean_members_response(
        {
            "controllingEntitiesAndIndividuals": [
                {
                    "member": {"name": "Example Director"},
                    "isKYCed": True,
                    "isCaseAMLPositive": True,
                    "caseAmlSummary": {"worldCheckSummary": {"sic": "HasMatches"}},
                }
            ]
        }
    )

    member = result["controlling_members"][0]
    assert member["kyc"] == {"is_kyced": True}
    assert "aml" not in json.dumps(result).casefold()


def test_org_chart_normalization_excludes_kyc_aml_fields() -> None:
    result = clean_org_chart_response(
        {
            "name": "Example Limited",
            "isUnresolvedAML": True,
            "isUpdatedAML": True,
            "validation": "complete",
        }
    )

    assert result["org_chart"]["kyc"] == {"validation": "complete"}
    assert "aml" not in json.dumps(result).casefold()
