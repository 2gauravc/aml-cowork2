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
TAVILY_API_KEY=tvly-your_tavily_key
```

## Members Tool

`src/tools/members.py` creates a KYC company case from a company name and
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

`src/tools/orgchart.py` creates a KYC company case from a company name and
jurisdiction, waits for the case to become ready, then prints cleaned recursive
ownership tree JSON for the company org chart.

The LLM-facing function is:

```python
get_company_org_chart_by_name(company_name, jurisdiction)
```

## Customer Static Tool

`src/tools/customer_static.py` creates a KYC company case from a company name and
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

`src/tools/case_finder.py` helps inspect the sandbox case list without dumping the
entire JSON file. It returns summary counts, a small set of selected cases, and
notes when more matches are available.

The LLM-facing function is:

```python
find_test_cases(query=None, jurisdiction=None, country=None, origin=None)
```

Examples:

```bash
python src/tools/case_finder.py
python src/tools/case_finder.py --jurisdiction HK
python src/tools/case_finder.py --query ubizense
python src/tools/case_finder.py --origin golden
```

## LangGraph CDD Agent

`src/agents/graph.py` runs the full CDD graph. It creates or reuses one KYC case,
fetches customer static data, org-chart data, and members data, then returns the
final `CDD` JSON object from graph state.

Run the full graph with a company name and jurisdiction:

```bash
python -m src.agents.graph \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB
```

Generate a PDF report in `outputs/cdd/` while running the graph:

```bash
python -m src.agents.graph \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB \
  --generate-pdf true
```

Reuse an existing KYC case to avoid creating and polling a new case:

```bash
python -m src.agents.graph \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB \
  --case-id 1000000690
```

You can combine `--case-id` and `--generate-pdf true`:

```bash
python -m src.agents.graph \
  --customer-name "CROPWELL BISHOP CREAMERY LIMITED" \
  --jurisdiction GB \
  --case-id 1000000690 \
  --generate-pdf true
```

If customer name or jurisdiction is missing, the graph returns an incomplete
CDD JSON object showing the missing required inputs instead of calling the API.

## Chatbot Web App

The chatbot UI is served by FastAPI from `src/backend/app.py`. It provides a React
chat panel, structured CDD workspace, PDF generation, and PDF download.

Start the web app:

```bash
python -m uvicorn src.backend.app:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

The backend keeps the KYC and OpenAI API keys server-side through `.env`.
Generated document PDFs are uploaded to S3 when `.env` includes
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The default document bucket URL
is `https://onbo-bkt.s3.us-east-1.amazonaws.com`; override it with
`S3_DOCUMENT_BUCKET_URL` or `AWS_S3_BUCKET_URL` if needed.

The UI separates two modes:

- Open-ended chat: always available through `/api/chat`. The LLM router can use
  the LLM-facing tools directly: `find_test_cases`,
  `get_customer_static_by_name`, `get_company_members_by_name`, and
  `get_company_org_chart_by_name`. This lets a user ask for test entities or
  partial KYC data before running a full case.
- Deterministic CDD pipeline: launched from the workspace panel through
  `/api/pipeline/run`, or by asking the chat to run full CDD. This executes the
  LangGraph nodes and writes the final `CDD` JSON into the session.

After a CDD run, follow-up questions are answered from the full graph session
state: the final `CDD` JSON, risk flags, tagged evidence captured from the
underlying KYC tool calls, and any previous individual tool results. OpenAI is
used automatically for richer natural-language explanations when
`OPENAI_API_KEY` is configured; set `OPENAI_QA_ENABLED=false` to force
deterministic CDD/evidence lookup.

## Red Flags and CSP Address Assessment

The CDD graph delegates red-flag checks to a focused subgraph. Its current
indicators cover missing UBOs, AML-positive controlling members, and whether a
registered address appears to be used by a company service provider (CSP).
CSP searches use Tavily and an OpenAI structured assessment; the cited results
and assessment are retained as evidence. A CSP indicator is a review item, not
proof of wrongdoing.

Run the CSP check independently:

```bash
python -m src.tools.csp_detector \
  --address "1 Example Street, London" \
  --company-name "Example Ltd"
```

## Run

Live API call:

```bash
python src/tools/members.py --company-name "Ubizense Limited" --jurisdiction HK
python src/tools/orgchart.py --company-name "Ubizense Limited" --jurisdiction HK
python src/tools/customer_static.py --company-name "Ubizense Limited" --jurisdiction HK
```

By default, the API-backed tools wait up to 5 minutes for the created case to
become ready:

```text
60 attempts x 5 seconds = 300 seconds
```

Override the wait if needed:

```bash
python src/tools/members.py \
  --company-name "Ubizense Limited" \
  --jurisdiction HK \
  --poll-attempts 120 \
  --poll-interval-seconds 5

python src/tools/orgchart.py \
  --company-name "Ubizense Limited" \
  --jurisdiction HK \
  --poll-attempts 120 \
  --poll-interval-seconds 5

python src/tools/customer_static.py \
  --company-name "Ubizense Limited" \
  --jurisdiction HK \
  --poll-attempts 120 \
  --poll-interval-seconds 5
```

Offline cleanup test using the saved sample response:

```bash
python src/tools/members.py --from-file notebooks/members.json
python src/tools/orgchart.py --from-file notebooks/org-chart.json
python src/tools/customer_static.py --from-file company-detail.json
```

## Output

The commands print JSON to the screen. On success, the members tool includes
cleaned member lists and case metadata, the org-chart tool includes a cleaned
recursive ownership tree and case metadata, and the customer-static tool
includes cleaned static company profile fields and case metadata. On failure,
they return a JSON object with an `error` field and context so an LLM can
explain or recover from the issue.
