# aml-cowork2

## Install

From the repo root:

```bash
python -m pip install -r requirements.txt
```

Create a `.env` file or export these environment variables:

```bash
KYCBASEURL=https://api.knowyourcustomer.dev
KYCCLIENTID=your_client_id
KYCCLIENTSECRET=your_client_secret
```

## Members Tool

`tools/members.py` creates a KYC company case from a company name and
jurisdiction, waits for the case to become ready, then prints cleaned ownership
JSON for:

- controlling members
- shareholders / beneficial owners
- ultimate beneficial owners

The LLM-facing function is:

```python
get_company_members_by_name(company_name, jurisdiction)
```

## Org Chart Tool

`tools/orgchart.py` creates a KYC company case from a company name and
jurisdiction, waits for the case to become ready, then prints cleaned recursive
ownership tree JSON for the company org chart.

The LLM-facing function is:

```python
get_company_org_chart_by_name(company_name, jurisdiction)
```

## Customer Static Tool

`tools/customer_static.py` creates a KYC company case from a company name and
jurisdiction, waits for the case to become ready, then prints cleaned static
company profile JSON. Use it for company type, registration number, company
status, registration/incorporation dates, total shares, share capital, activity
type, previous names, and registered address.

The tool normalizes common registry field names into stable output keys and
also includes the raw `registry_properties` block, so registry-specific fields
are still available when a jurisdiction uses different labels.

The LLM-facing function is:

```python
get_customer_static_by_name(company_name, jurisdiction)
```

## Case Finder Tool

`tools/case_finder.py` helps inspect the sandbox case list without dumping the
entire JSON file. It returns summary counts, a small set of selected cases, and
notes when more matches are available.

The LLM-facing function is:

```python
find_test_cases(query=None, jurisdiction=None, country=None, origin=None)
```

Examples:

```bash
python tools/case_finder.py
python tools/case_finder.py --jurisdiction HK
python tools/case_finder.py --query ubizense
python tools/case_finder.py --origin golden
```

## LangGraph CDD Agent

`agents/graph.py` runs the full CDD graph. It creates or reuses one KYC case,
fetches customer static data, org-chart data, and members data, then returns the
final `CDD` JSON object from graph state.

Run the full graph with a company name and jurisdiction:

```bash
python agents/graph.py \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB
```

Generate a PDF report in `outputs/` while running the graph:

```bash
python agents/graph.py \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB \
  --generate-pdf true
```

Reuse an existing KYC case to avoid creating and polling a new case:

```bash
python agents/graph.py \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB \
  --case-id 1000000690
```

You can combine `--case-id` and `--generate-pdf true`:

```bash
python agents/graph.py \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB \
  --case-id 1000000690 \
  --generate-pdf true
```

If customer name or jurisdiction is missing, the graph returns an incomplete
CDD JSON object showing the missing required inputs instead of calling the API.

## Chatbot Web App

The chatbot UI is served by FastAPI from `backend/app.py`. It provides a React
chat panel, structured CDD workspace, PDF generation, and PDF download.

Start the web app:

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

The backend keeps the KYC and OpenAI API keys server-side through `.env`. The
current CDD graph remains deterministic; the chat UI collects inputs and invokes
the graph through `/api/chat`.

## Run

Live API call:

```bash
python tools/members.py --company-name "Ubizense Limited" --jurisdiction HK
python tools/orgchart.py --company-name "Ubizense Limited" --jurisdiction HK
python tools/customer_static.py --company-name "Ubizense Limited" --jurisdiction HK
```

By default, the API-backed tools wait up to 5 minutes for the created case to
become ready:

```text
60 attempts x 5 seconds = 300 seconds
```

Override the wait if needed:

```bash
python tools/members.py \
  --company-name "Ubizense Limited" \
  --jurisdiction HK \
  --poll-attempts 120 \
  --poll-interval-seconds 5

python tools/orgchart.py \
  --company-name "Ubizense Limited" \
  --jurisdiction HK \
  --poll-attempts 120 \
  --poll-interval-seconds 5

python tools/customer_static.py \
  --company-name "Ubizense Limited" \
  --jurisdiction HK \
  --poll-attempts 120 \
  --poll-interval-seconds 5
```

Offline cleanup test using the saved sample response:

```bash
python tools/members.py --from-file notebooks/members.json
python tools/orgchart.py --from-file notebooks/org-chart.json
python tools/customer_static.py --from-file company-detail.json
```

## Output

The commands print JSON to the screen. On success, the members tool includes
cleaned member lists and case metadata, the org-chart tool includes a cleaned
recursive ownership tree and case metadata, and the customer-static tool
includes cleaned static company profile fields and case metadata. On failure,
they return a JSON object with an `error` field and context so an LLM can
explain or recover from the issue.
