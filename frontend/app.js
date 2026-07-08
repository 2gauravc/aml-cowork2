const { useMemo, useState } = React;

function App() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Which company would you like to onboard?" },
  ]);
  const [customerName, setCustomerName] = useState("");
  const [jurisdiction, setJurisdiction] = useState("GB");
  const [message, setMessage] = useState("");
  const [cdd, setCdd] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [error, setError] = useState(null);

  const profile = cdd?.company_business_profile?.customer_static || {};
  const ownership = cdd?.ownership_and_control || {};
  const risks = useMemo(() => riskFlags(cdd), [cdd]);

  async function sendChat({ generatePdf = false } = {}) {
    const outgoing = message.trim();
    if (!outgoing && !customerName.trim()) return;
    setLoading(true);
    setError(null);
    if (outgoing) {
      setMessages((current) => [...current, { role: "user", content: outgoing }]);
    }
    setMessage("");

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: outgoing,
          customer_name: customerName.trim() || null,
          jurisdiction: jurisdiction.trim() || null,
          generate_pdf: generatePdf,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "CDD request failed");
      setSessionId(data.session_id);
      setMessages(data.messages || []);
      setCdd(data.cdd || null);
      setPdfUrl(data.pdf_url || null);
      if (data.customer_name) setCustomerName(data.customer_name);
      if (data.jurisdiction) setJurisdiction(data.jurisdiction);
      if (data.error) setError(data.error);
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
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "PDF generation failed");
      setPdfUrl(data.pdf_url);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">WBL Bank CDD</div>
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
            <h1>Onboarding Chat</h1>
            <p>Provide a company name and jurisdiction to start CDD.</p>
          </div>

          <div className="messages">
            {messages.map((item, index) => (
              <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                {item.content}
              </div>
            ))}
            {loading && <div className="message assistant">Running checks...</div>}
          </div>

          <div className="composer">
            <div className="quick-form">
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
                <option value="GB">GB</option>
                <option value="HK">HK</option>
                <option value="US">US</option>
                <option value="SG">SG</option>
              </select>
            </div>
            <textarea
              aria-label="Message"
              placeholder='Ask, or type "CROPWELL BISHOP CREAMERY LIMITED, GB"'
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  sendChat();
                }
              }}
            />
            <div className="send-row">
              <button className="secondary" disabled={loading} onClick={() => sendChat({ generatePdf: true })}>
                Run + PDF
              </button>
              <button disabled={loading} onClick={() => sendChat()}>
                Start CDD
              </button>
            </div>
            {error && <div className="risk">{error}</div>}
          </div>
        </aside>

        <main className="main">
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

          <Section title="Customer">
            <div className="grid">
              <Field label="Name" value={profile.name} />
              <Field label="Jurisdiction" value={profile.jurisdiction || jurisdiction} />
              <Field label="Status" value={profile.company_status} />
              <Field label="Registration No" value={profile.registration_number} />
              <Field label="Company Type" value={profile.company_type} />
              <Field label="Activity" value={profile.activity_type} />
              <Field label="Incorporation" value={profile.incorporation_date} />
              <Field label="Address" value={profile.registered_address?.full_address} />
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

function Field({ label, value }) {
  return (
    <div className="field">
      <div className="label">{label}</div>
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
