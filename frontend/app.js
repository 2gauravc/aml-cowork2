const { useEffect, useMemo, useState } = React;

const FALLBACK_JURISDICTIONS = ["GB", "HK", "US", "SG"];

function App() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Ask me to explain evidence, run specific tasks, run full CDD pipeline or search for accounts in sandbox scope.",
    },
  ]);
  const [customerName, setCustomerName] = useState("");
  const [jurisdiction, setJurisdiction] = useState("GB");
  const [jurisdictions, setJurisdictions] = useState(FALLBACK_JURISDICTIONS);
  const [caseId, setCaseId] = useState("");
  const [message, setMessage] = useState("");
  const [cdd, setCdd] = useState(null);
  const [toolResults, setToolResults] = useState([]);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [error, setError] = useState(null);

  const profile = cdd?.company_business_profile?.customer_static || {};
  const ownership = cdd?.ownership_and_control || {};
  const risks = useMemo(() => riskFlags(cdd), [cdd]);
  const capital = capitalDisplay(profile);
  const fieldSources = profile.source || {};
  const cddMetadata = {
    customer: profile.name || customerName || "-",
    date: formatDateTime(cdd?.completed_at || cdd?.started_at),
    status: cdd ? cddStatusLabel(cdd.status) : "-",
  };

  useEffect(() => {
    let ignore = false;

    async function loadJurisdictions() {
      try {
        const response = await fetch("/api/jurisdictions");
        const data = await readJsonResponse(response, "Jurisdictions request failed");
        if (!ignore && Array.isArray(data.jurisdictions) && data.jurisdictions.length) {
          setJurisdictions(data.jurisdictions);
          if (!data.jurisdictions.includes(jurisdiction)) {
            setJurisdiction(data.jurisdictions[0]);
          }
        }
      } catch (err) {
        if (!ignore) setError(err.message);
      }
    }

    loadJurisdictions();
    return () => {
      ignore = true;
    };
  }, []);

  function applyResponse(data) {
    setSessionId(data.session_id);
    setMessages(data.messages || []);
    setCdd(data.cdd || null);
    setToolResults(data.tool_results || []);
    setPdfUrl(data.pdf_url || null);
    if (data.customer_name) setCustomerName(data.customer_name);
    if (data.jurisdiction) setJurisdiction(data.jurisdiction);
    if (data.case_id) setCaseId(String(data.case_id));
    if (data.error) setError(data.error);
  }

  async function sendChat() {
    const outgoing = message.trim();
    if (!outgoing) return;
    setLoading(true);
    setError(null);
    setMessages((current) => [...current, { role: "user", content: outgoing }]);
    setMessage("");

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: outgoing,
        }),
      });
      const data = await readJsonResponse(response, "Chat request failed");
      applyResponse(data);
      if (data.status === "running") {
        await pollSession(data.session_id);
      }
    } catch (err) {
      setError(err.message);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: `Something went wrong: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function runPipeline({ generatePdf = false } = {}) {
    if (!customerName.trim() || !jurisdiction.trim()) return;
    setPipelineLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/pipeline/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          customer_name: customerName.trim(),
          jurisdiction: jurisdiction.trim(),
          case_id: caseId.trim() || null,
          generate_pdf: generatePdf,
        }),
      });
      const data = await readJsonResponse(response, "CDD pipeline failed");
      applyResponse(data);
      if (data.status === "running") {
        await pollSession(data.session_id);
      }
    } catch (err) {
      setError(err.message);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: `Something went wrong: ${err.message}` },
      ]);
    } finally {
      setPipelineLoading(false);
    }
  }

  async function generatePdf() {
    if (!sessionId || !cdd) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await readJsonResponse(response, "PDF generation failed");
      setPdfUrl(data.pdf_url);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function pollSession(activeSessionId) {
    while (activeSessionId) {
      await delay(2000);
      const response = await fetch(`/api/session/${activeSessionId}`);
      const data = await readJsonResponse(response, "CDD pipeline failed");
      applyResponse(data);
      if (data.status !== "running") {
        if (data.error) throw new Error(data.error);
        return data;
      }
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">WBL Bank Onboarding CDD</div>
        <div className="top-status">
          <span className={`badge ${cdd?.status === "complete" ? "complete" : "review"}`}>
            CDD: {cdd?.status || "Draft"}
          </span>
          <span className={`badge ${risks.length ? "review" : "complete"}`}>
            Risk: {risks.length ? "Review" : "Clear"}
          </span>
        </div>
      </header>

      <div className="workspace">
        <aside className="chat">
          <div className="chat-head">
            <h1>Onboarding Chat - for deeper probing</h1>
          </div>

          <div className="messages">
            {messages.map((item, index) => (
              <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                {item.content}
              </div>
            ))}
            {loading && (
              <div className="message assistant">
                Thinking...
              </div>
            )}
          </div>

          <div className="composer">
            <textarea
              aria-label="Message"
              placeholder='Try "what test cases are available in GB?" or "fetch the org chart for Cropwell Bishop Creamery Limited, GB"'
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  sendChat();
                }
              }}
            />
            <div className="send-row">
              <button disabled={loading} onClick={() => sendChat()}>
                Ask
              </button>
            </div>
            {error && <div className="risk">{error}</div>}
          </div>
        </aside>

        <main className="main">
          <Section title="Run Full CDD Pipeline">
            <div className="pipeline-form">
              <input
                aria-label="Company name"
                placeholder="Company name"
                value={customerName}
                onChange={(event) => setCustomerName(event.target.value)}
              />
              <select
                aria-label="Jurisdiction"
                value={jurisdiction}
                onChange={(event) => setJurisdiction(event.target.value)}
              >
                {jurisdictions.map((code) => (
                  <option value={code} key={code}>{code}</option>
                ))}
              </select>
              <input
                aria-label="Case ID"
                placeholder="Case ID optional"
                value={caseId}
                onChange={(event) => setCaseId(event.target.value)}
              />
              <button
                disabled={pipelineLoading || !customerName.trim()}
                onClick={() => runPipeline()}
              >
                Run Full CDD Pipeline
              </button>
            </div>
            {pipelineLoading && <p className="empty">Running the full CDD pipeline. Please wait</p>}
          </Section>

          <div className="actions">
            <button disabled={!cdd || loading} onClick={generatePdf}>Generate PDF</button>
            {pdfUrl && (
              <a href={pdfUrl} target="_blank" rel="noreferrer">
                <button className="secondary">Download PDF</button>
              </a>
            )}
            <button className="secondary" disabled={!cdd} onClick={() => setShowJson((value) => !value)}>
              {showJson ? "Hide JSON" : "View JSON"}
            </button>
          </div>

          <section className="cdd-metadata" aria-label="CDD metadata">
            <div className="metadata-item">
              <span>Customer</span>
              <strong>{cddMetadata.customer}</strong>
            </div>
            <div className="metadata-item">
              <span>CDD Date</span>
              <strong>{cddMetadata.date}</strong>
            </div>
            <div className="metadata-item">
              <span>CDD Status</span>
              <strong>{cddMetadata.status}</strong>
            </div>
          </section>

          <Section title="About the Customer">
            <div className="grid">
              <Field label="Name" value={profile.name} source={fieldSources.name} />
              <Field
                label="Jurisdiction"
                value={profile.jurisdiction || jurisdiction}
                source={fieldSources.jurisdiction}
              />
              <Field label="Status" value={profile.company_status} source={fieldSources.company_status} />
              <Field
                label="Registration No"
                value={profile.registration_number}
                source={fieldSources.registration_number}
              />
              <Field label="Company Type" value={profile.company_type} source={fieldSources.company_type} />
              <Field label={capital.label} value={capital.value} source={capital.source} />
              <Field label="Activity" value={profile.activity_type} source={fieldSources.activity_type} />
              <Field
                label="Incorporation"
                value={profile.incorporation_date}
                source={fieldSources.incorporation_date}
              />
              <Field
                label="Address"
                value={profile.registered_address?.full_address}
                source={fieldSources.registered_address}
              />
            </div>
          </Section>

          <Section title="Ownership & Control">
            <SubTable
              title="UBOs"
              empty="None identified"
              columns={["Name", "Effective %"]}
              rows={(ownership.ubos || []).map((row) => [
                row.name,
                percent(row.effective_shareholding_percent),
              ])}
            />
            <SubTable
              title="Shareholders >10%"
              empty="None identified"
              columns={["Name", "Type", "Effective %"]}
              rows={(ownership.shareholders_over_10_percent || []).map((row) => [
                row.name,
                row.type,
                percent(row.effective_shareholding_percent),
              ])}
            />
          </Section>

          <Section title="Related Parties">
            <SubTable
              empty="None identified"
              columns={["Name", "Role", "Related Entity", "Reason"]}
              rows={(ownership.related_parties || []).map((row) => [
                row.name,
                row.role,
                row.related_entity,
                row.reason,
              ])}
            />
          </Section>

          <Section title="Risk Flags">
            {risks.length ? (
              <div className="risk-list">
                {risks.map((risk, index) => (
                  <div className="risk" key={index}>{risk}</div>
                ))}
              </div>
            ) : (
              <p className="empty">No open risk flags in the current CDD object.</p>
            )}
          </Section>

          <Section title="Tool Results">
            {toolResults.length ? (
              <div className="tool-list">
                {toolResults.slice().reverse().map((item, index) => (
                  <details className="tool-result" key={`${item.tool}-${index}`}>
                    <summary>{item.tool}</summary>
                    <pre className="json-view">{JSON.stringify(item.data, null, 2)}</pre>
                  </details>
                ))}
              </div>
            ) : (
              <p className="empty">No individual tool calls in this session yet.</p>
            )}
          </Section>

          {showJson && cdd && (
            <Section title="CDD JSON">
              <pre className="json-view">{JSON.stringify(cdd, null, 2)}</pre>
            </Section>
          )}
        </main>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, value, source }) {
  const sourceText = sourceTooltip(source);
  return (
    <div className="field">
      <div className="label-row">
        <div className="label">{label}</div>
        {sourceText && (
          <span className="source-tip" tabIndex="0" aria-label={sourceText}>
            i
            <span className="source-tooltip" role="tooltip">{sourceText}</span>
          </span>
        )}
      </div>
      <div className="value">{value || "-"}</div>
    </div>
  );
}

function SubTable({ title, columns, rows, empty }) {
  return (
    <div>
      {title && <h3>{title}</h3>}
      {rows.length ? (
        <table>
          <thead>
            <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell || "-"}</td>)}</tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">{empty}</p>
      )}
    </div>
  );
}

function percent(value) {
  if (value === undefined || value === null || value === "") return "-";
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : value;
}

function capitalDisplay(profile) {
  const display = profile.display_capital;
  if (display?.value) {
    return {
      label: "Paid-up Capital",
      value: display.value,
      source: display.source || profile.source?.paid_up_capital || null,
    };
  }
  return {
    label: "Paid-up Capital",
    value: "-",
    source: profile.source?.paid_up_capital || null,
  };
}

function sourceTooltip(source) {
  if (!source) return null;
  const lines = [];
  if (source.api) lines.push(`API: ${source.api}`);
  if (source.field) lines.push(`Field: ${source.field}`);
  return lines.length ? lines.join("\n") : null;
}

function cddStatusLabel(status) {
  return status === "complete" ? "Complete" : "Incomplete";
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function readJsonResponse(response, fallbackMessage) {
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      throw new Error(`${fallbackMessage}: unexpected server response`);
    }
  }
  if (!response.ok) {
    throw new Error(data.detail || data.error || fallbackMessage);
  }
  if (!text) {
    throw new Error(`${fallbackMessage}: empty response from server`);
  }
  return data;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function riskFlags(cdd) {
  if (!cdd) return [];
  const risks = [];
  const ownership = cdd.ownership_and_control || {};
  if (ownership.status === "complete" && !(ownership.ubos || []).length) {
    risks.push("Medium: No individual UBO above 25% was identified.");
  }
  const members = ownership.members?.controlling_members || [];
  members.forEach((member) => {
    if (member.kyc?.is_aml_positive) {
      risks.push(`High: AML review flag for ${member.name}.`);
    }
  });
  return risks;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
