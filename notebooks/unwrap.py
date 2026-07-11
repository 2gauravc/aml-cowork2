#!/usr/bin/env python3
"""
KYC Public API v2 - full onboarding journey (Python + requests)

Journey: token -> search -> create -> poll to Ready -> members + org-chart
         -> get an individual member -> upload document (good vs forged)
         -> AML view -> close (Approved) -> download report PDF

Requires: pip install requests
Usage:    CLIENT_ID=... CLIENT_SECRET=... python journey.py
"""
import os
import sys
import time
import json

import requests
import os
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

BASE_URL = os.getenv("KYCBASEURL", "https://api.knowyourcustomer.dev")
CLIENT_ID = os.getenv("KYCCLIENTID")
CLIENT_SECRET = os.getenv("KYCCLIENTSECRET")

ISO = "SG"
QUERY = "SC ENGINEERING PRIVATE LIMITED"


class KycClient:
    """Minimal client with an in-memory token cache and refresh-on-401."""

    def __init__(self, base_url, client_id, client_secret):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._expires_at = 0.0

    def _token_value(self):
        if self._token and time.time() < self._expires_at - 30:
            return self._token
        resp = requests.post(
            f"{self.base_url}/connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "PublicApi",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 600))
        return self._token

    def request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token_value()}"
        resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        if resp.status_code == 401:  # token may have expired mid-journey - refresh once
            self._token = None
            headers["Authorization"] = f"Bearer {self._token_value()}"
            resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        return resp


def main():
    client = KycClient(BASE_URL, CLIENT_ID, CLIENT_SECRET)

    # 2. Search the registry
    print(f"==> Searching registry for {QUERY!r} in {ISO}")
    r = client.request("POST", "/v2/Companies/search",
                       json={"codeiso31662": ISO, "query": QUERY})
    r.raise_for_status()
    results = r.json()["companySearch"]["results"]

    if not results:
        sys.exit("No registry results")
    rawname = results[0]["rawname"]
    print(f"    matched: {rawname}")

    # 3. Create the company case
    print("==> Creating company case")
    r = client.request("POST", "/v2/Companies",
                       json={"rawname": rawname, "codeiso31662": ISO})
    r.raise_for_status()
    case_id = r.json()["caseDetail"]["details"]["common"]["caseCommonId"]
    print(f"    caseCommonId: {case_id}")

    # 4. Poll until Ready (statusId == 3)
    print("==> Polling for Ready")
    for _ in range(60):
        r = client.request("GET", f"/v2/Companies/{case_id}")
        r.raise_for_status()
        status = r.json()["caseDetail"]["details"]["common"]["statusId"]
        print(f"    statusId={status}")
        if status == 3:
            break
        if status == 8:
            sys.exit("Case expired/failed")
        time.sleep(5)

    # 5. Members + org-chart
    print("==> Fetching members")
    members = client.request("GET", f"/v2/Companies/{case_id}/members").json()
    members_path = "members.json"
    with open(members_path, "w", encoding="utf-8") as fh:
        json.dump(members, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"    saved members response to {members_path}")
    controlling = members.get("controllingEntitiesAndIndividuals", [])
    print(f"    controlling parties: {len(controlling)}, "
          f"shareholders: {len(members.get('shareholdersAndBeneficialOwners', []))}")

    print("==> Fetching org-chart (recursive ownership tree)")
    org = client.request("GET", f"/v2/Companies/{case_id}/org-chart").json()
    org_chart_path = "org-chart.json"
    with open(org_chart_path, "w", encoding="utf-8") as fh:
        json.dump(org, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"    saved org-chart response to {org_chart_path}")

    # memberType is a STRING ("Individual" / "Company")
    individual = next((m for m in controlling if m.get("memberType") == "Individual"), None)
    if not individual:
        sys.exit("No individual controlling party found")
    indiv_id = individual["member"]["caseCommonId"]
    print(f"    individual member caseCommonId: {indiv_id}")

    # 6. Get the individual + mandatory docs
    print(f"==> Fetching individual member {indiv_id}")
    client.request("GET", f"/v2/Individuals/{indiv_id}").raise_for_status()
    mandatory = client.request(
        "GET", f"/v2/Individuals/{indiv_id}/documents/mandatory").json()
    print(f"    mandatory docs: {mandatory}")  # typically ["photoid","selfie","poa"]

    # 7. Upload a document (multipart) - good then forged
    def upload(file_path, name, label):
        with open(file_path, "rb") as fh:
            r = client.request(
                "POST", f"/v2/Individuals/{indiv_id}/documents/upload",
                data={
                    "name": name,
                    "fileCat": "photoid",
                    "caseCommonId": str(indiv_id),
                    "isCompany": "false",
                },
                files={"file": (os.path.basename(file_path), fh,
                                "application/octet-stream")},
            )
        r.raise_for_status()
        msgs = r.json().get("prevalidationMessages", [])
        print(f"    {label}: prevalidationMessages={msgs}")

    print("==> Uploading a (good) identity document")
    upload("./passport.jpg", "Passport", "good")          # -> []
    print("==> Uploading a (forged) identity document")
    upload("./forged.jpg", "Passport (forged)", "forged")  # -> [{key: IdentityDocumentNotRecognized}]

    # 8. AML view
    print("==> AML checks for the company")
    aml = client.request("GET", f"/v2/Companies/{case_id}/amlchecks").json()
    print(f"    worldChecks={len(aml.get('worldChecks', []))}, "
          f"lexisNexisChecks={len(aml.get('lexisNexisChecks', []))}")

    # 9. Close the case with a decision
    print("==> Recording decision: Approved")
    r = client.request("PATCH", f"/v2/Companies/{case_id}/status",
                       json={"status": "Approved"})
    r.raise_for_status()
    print(f"    {r.json()}")

    # 10. Download the KYC report PDF
    print("==> Downloading KYC report PDF")
    r = client.request("GET", f"/v2/Companies/{case_id}/report",
                       params={"language": "en"})
    if r.status_code == 409:
        sys.exit("Report not ready yet")
    r.raise_for_status()
    out = f"kyc-report-{case_id}.pdf"
    with open(out, "wb") as fh:
        fh.write(r.content)
    print(f"    saved {out}")
    print("==> Done.")


if __name__ == "__main__":
    main()
