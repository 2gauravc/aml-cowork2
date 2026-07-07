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

## Run

Live API call:

```bash
python tools/members.py --company-name "Ubizense Limited" --jurisdiction HK
```

By default, the tool waits up to 5 minutes for the created case to become ready:

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
```

Offline cleanup test using the saved sample response:

```bash
python tools/members.py --from-file notebooks/members.json
```

## Output

The command prints JSON to the screen. On success, it includes cleaned member
lists and case metadata. On failure, it returns a JSON object with an `error`
field and context so an LLM can explain or recover from the issue.
