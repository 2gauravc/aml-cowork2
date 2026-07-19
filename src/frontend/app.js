const { useEffect, useMemo, useRef, useState } = React;

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
  const [riskFlagRecords, setRiskFlagRecords] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [documentRequirements, setDocumentRequirements] = useState([]);
  const [generationStatus, setGenerationStatus] = useState("");
  const [activeWorkspace, setActiveWorkspace] = useState("cdd");
  const [cspCompanyName, setCspCompanyName] = useState("");
  const [cspAddress, setCspAddress] = useState("");
  const [cspResult, setCspResult] = useState(null);
  const [cspError, setCspError] = useState("");
  const [cspAssessing, setCspAssessing] = useState(false);
  const [cspSkill, setCspSkill] = useState("");
  const [cspSkillLoading, setCspSkillLoading] = useState(false);
  const [documentLinks, setDocumentLinks] = useState({});
  const [refreshingDocumentKey, setRefreshingDocumentKey] = useState(null);
  const [uploadNotice, setUploadNotice] = useState("");
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [pipelineProgress, setPipelineProgress] = useState(null);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [showJson, setShowJson] = useState(false);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(Date.now());
  const uploadInputRef = useRef(null);

  const profile = cdd?.company_business_profile?.customer_static || {};
  const ownership = cdd?.ownership_and_control || {};
  const idv = cdd?.individual_identity_verification || {};
  const risks = useMemo(() => riskFlags(riskFlagRecords), [riskFlagRecords]);
  const capital = capitalDisplay(profile);
  const fieldSources = profile.source || {};
  const cddMetadata = {
    customer: profile.name || customerName || "-",
    date: formatDateTime(cdd?.completed_at || cdd?.started_at),
    status: cdd ? cddStatusLabel(cdd.status) : "-",
  };
  const pipelineStatusText = pipelineProgress
    ? formatPipelineProgress(pipelineProgress)
    : latestAssistantMessage(messages) || "Setting up";
  const pipelineRunning = pipelineStatus === "running" || pipelineStatus === "awaiting_documents";
  const documentKeyList = useMemo(
    () => documents.map((document) => documentKey(document)).filter(Boolean).join("|"),
    [documents],
  );

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

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!sessionId || !documents.length) return;
    documents.forEach((document) => {
      const key = documentKey(document);
      if (key && !documentLinks[key]) {
        refreshDocumentLink(document);
      }
    });
  }, [sessionId, documentKeyList]);

  useEffect(() => {
    if (!sessionId) return;
    documentRequirements.forEach((requirement) => {
      const document = requirement.cache_document;
      const key = documentKey(document);
      if (key && !documentLinks[key]) refreshDocumentLink(document);
    });
  }, [sessionId, documentRequirements, documentLinks]);

  function applyResponse(data) {
    setSessionId(data.session_id);
    setMessages(data.messages || []);
    setCdd(data.cdd || null);
    setRiskFlagRecords(data.risk_flags || []);
    setDocuments(data.documents || []);
    setDocumentRequirements(data.document_requirements || []);
    setDocumentLinks((current) => {
      const keys = new Set((data.documents || []).map((document) => documentKey(document)));
      return Object.fromEntries(
        Object.entries(current).filter(([key]) => keys.has(key)),
      );
    });
    setPdfUrl(data.pdf_url || null);
    if (data.customer_name) setCustomerName(data.customer_name);
    if (data.jurisdiction) setJurisdiction(data.jurisdiction);
    if (data.case_id) setCaseId(String(data.case_id));
    setPipelineProgress(data.pipeline_progress || null);
    setPipelineStatus(data.pipeline_status || data.status || null);
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

  async function refreshDocumentLink(document) {
    const key = documentKey(document);
    if (!sessionId || !key) return;
    setRefreshingDocumentKey(key);
    setError(null);
    try {
      const response = await fetch("/api/documents/presign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          document_key: key,
        }),
      });
      const data = await readJsonResponse(response, "Document link refresh failed");
      setDocumentLinks((current) => ({ ...current, [key]: data }));
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshingDocumentKey(null);
    }
  }

  function openUploadDialog() {
    uploadInputRef.current?.click();
  }

  async function handleUploadPlaceholder(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length || !sessionId) return;
    setLoading(true);
    setError(null);
    try {
      for (const file of files) {
        const body = new FormData();
        body.append("session_id", sessionId);
        body.append("file", file);
        const response = await fetch("/api/documents/upload", { method: "POST", body });
        applyResponse(await readJsonResponse(response, "Document upload failed"));
      }
      setUploadNotice(`${files.length} document${files.length === 1 ? "" : "s"} matched and staged for processing.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    event.target.value = "";
  }

  async function documentAction(endpoint) {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      applyResponse(await readJsonResponse(response, "Document action failed"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function generateMissingDocuments() {
    if (!sessionId) return;
    const missing = documentRequirements.filter((requirement) => requirement.status === "not_found");
    if (!missing.length) return;
    setLoading(true);
    setError(null);
    try {
      for (const requirement of missing) {
        setGenerationStatus(`Generating ${documentLabel(requirement.document_type)} for ${requirement.entity_name}...`);
        await new Promise((resolve) => window.requestAnimationFrame(resolve));
        const response = await fetch("/api/documents/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, requirement_ids: [requirement.id] }),
        });
        applyResponse(await readJsonResponse(response, "Document generation failed"));
      }
      setGenerationStatus(`Generated ${missing.length} document${missing.length === 1 ? "" : "s"}.`);
    } catch (err) {
      setError(err.message);
      setGenerationStatus("Document generation failed.");
    } finally {
      setLoading(false);
    }
  }

  async function loadCspSkill() {
    if (cspSkill || cspSkillLoading) return;
    setCspSkillLoading(true);
    try {
      const response = await fetch("/api/csp/skill");
      const data = await readJsonResponse(response, "Unable to load CSP skill");
      setCspSkill(data.skill || "");
    } catch (err) {
      setCspError(err.message);
    } finally {
      setCspSkillLoading(false);
    }
  }

  async function assessCsp() {
    if (!cspAddress.trim()) return;
    setCspAssessing(true);
    setCspError("");
    setCspResult(null);
    try {
      const response = await fetch("/api/csp/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: cspCompanyName.trim() || null,
          registered_address: cspAddress.trim(),
        }),
      });
      setCspResult(await readJsonResponse(response, "CSP assessment failed"));
    } catch (err) {
      setCspError(err.message);
    } finally {
      setCspAssessing(false);
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
      </header>

      <div className="workspace">
        <aside className="chat">
          <div className="chat-head">
            <h1>Onboarding Chat - for deeper probing</h1>
          </div>

          <div className="messages">
            {messages.map((item, index) => (
              <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                <MarkdownMessage content={item.content} />
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
          <div className="workspace-tabs" role="tablist" aria-label="Workspace">
            <button
              className={`workspace-tab ${activeWorkspace === "cdd" ? "active" : ""}`}
              role="tab"
              aria-selected={activeWorkspace === "cdd"}
              onClick={() => setActiveWorkspace("cdd")}
            >
              CDD
            </button>
            <button
              className={`workspace-tab ${activeWorkspace === "generation" ? "active" : ""}`}
              role="tab"
              aria-selected={activeWorkspace === "generation"}
              onClick={() => setActiveWorkspace("generation")}
            >
              Documents
            </button>
            <button
              className={`workspace-tab ${activeWorkspace === "csp" ? "active" : ""}`}
              role="tab"
              aria-selected={activeWorkspace === "csp"}
              onClick={() => setActiveWorkspace("csp")}
            >
              CSP Detection
            </button>
          </div>

          <div className="workspace-tab-panel" role="tabpanel">
            {activeWorkspace === "cdd" ? (
              <>
          <Section title="Run CDD Worker">
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
            {pipelineLoading && <p className="empty">{pipelineStatusText}</p>}
          </Section>

          <div className="actions">
            <button disabled={!cdd || loading || pipelineRunning} onClick={generatePdf}>Generate PDF</button>
            {pdfUrl && (
              <a href={pdfUrl} target="_blank" rel="noreferrer">
                <button className="secondary">Download PDF</button>
              </a>
            )}
            <button className="secondary" disabled={!cdd || pipelineRunning} onClick={() => setShowJson((value) => !value)}>
              {showJson ? "Hide JSON" : "View JSON"}
            </button>
          </div>

          <section className="cdd-metadata" aria-label="CDD metadata">
            <h2 className="cdd-metadata-title">CDD Metadata</h2>
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
              <Field label="Name" value={profile.name || customerName} source={fieldSources.name} />
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
              title="Shareholders > 10%"
              empty="None identified"
              columns={["Name", "Type", "Effective %"]}
              rows={(ownership.shareholders_over_10_percent || []).map((row) => [
                row.name,
                row.type,
                percent(row.effective_shareholding_percent),
              ])}
            />
            <SubTable
              title="Related Parties"
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

          <Section title="ID&V">
            <SubTable
              empty="No ID&V requirements established"
              columns={[
                "Name",
                "Role(s)",
                "Required",
                "Document",
                "Document No",
                "Nationality",
                "DOB",
                "Expiry",
                "Status",
              ]}
              rows={(idv.required_individuals || []).map((row) => [
                row.name,
                joinList(row.roles),
                joinList(row.required_documents?.map(documentLabel)),
                documentLabel(row.document?.document_type || row.selected_document_type),
                row.document?.document_number,
                row.document?.nationality,
                row.document?.date_of_birth,
                row.document?.expiry_date,
                statusLabel(row.status),
              ])}
            />
          </Section>

          <Section title="Risk Flags">
            {risks.length ? (
              <div className="risk-list">
                {risks.map((risk, index) => (
                  <div className="risk" key={`${risk.category || "risk"}-${index}`}>
                    <div className="risk-content">
                      <strong>{riskPresentation(risk).title}</strong>
                      <span>{`Evaluation: ${riskPresentation(risk).evaluation}. ${riskPresentation(risk).summary}`}</span>
                    </div>
                    <RiskEvidenceTooltip risk={risk} />
                  </div>
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
              </>
            ) : activeWorkspace === "generation" ? (
              <DocumentManagement
                requirements={documentRequirements}
                links={documentLinks}
                loading={loading}
                generationStatus={generationStatus}
                onGenerate={generateMissingDocuments}
                onProcess={() => documentAction("/api/documents/process")}
                onUploadClick={openUploadDialog}
                uploadInputRef={uploadInputRef}
                onUploadChange={handleUploadPlaceholder}
                uploadNotice={uploadNotice}
              />
            ) : (
              <CSPDetection
                companyName={cspCompanyName}
                address={cspAddress}
                result={cspResult}
                error={cspError}
                assessing={cspAssessing}
                skill={cspSkill}
                skillLoading={cspSkillLoading}
                onCompanyNameChange={setCspCompanyName}
                onAddressChange={setCspAddress}
                onSkillToggle={(open) => { if (open) loadCspSkill(); }}
                onAssess={assessCsp}
              />
            )}
          </div>
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

function CSPDetection({
  companyName,
  address,
  result,
  error,
  assessing,
  skill,
  skillLoading,
  onCompanyNameChange,
  onAddressChange,
  onSkillToggle,
  onAssess,
}) {
  const assessment = result?.assessment || {};
  const presentation = result
    ? riskPresentation({ category: "csp_address", evidence: result })
    : null;
  return (
    <>
      <Section title="CSP Detection">
        <details className="skill-details" onToggle={(event) => onSkillToggle(event.currentTarget.open)}>
          <summary>Assessment skill</summary>
          {skillLoading ? <p className="empty">Loading skill…</p> : (
            <pre className="skill-content">{skill || "Open this section to load the current skill."}</pre>
          )}
        </details>

        <div className="csp-form">
          <input
            aria-label="Entity name"
            placeholder="Entity name"
            value={companyName}
            onChange={(event) => onCompanyNameChange(event.target.value)}
          />
          <textarea
            aria-label="Registered address"
            placeholder="Registered address"
            value={address}
            onChange={(event) => onAddressChange(event.target.value)}
          />
          <button disabled={assessing || !address.trim()} onClick={onAssess}>
            {assessing ? "Assessing…" : "Assess"}
          </button>
        </div>
        {error && <p className="risk">{error}</p>}
      </Section>

      {result && (
        <Section title="Assessment Result">
          <div className="risk csp-assessment-result">
            <div className="risk-content">
              <strong>{presentation.title}</strong>
              <span>{`Evaluation: ${presentation.evaluation}. ${presentation.summary}`}</span>
              <p>{assessment.explanation}</p>
            </div>
          </div>
          {(result.sources || []).length > 0 && (
            <div className="csp-sources">
              <strong>Sources</strong>
              {(result.sources || []).map((source, index) => (
                <a key={`${source.url || source.title}-${index}`} href={source.url} target="_blank" rel="noreferrer">
                  {source.title || source.url || "Source"}
                </a>
              ))}
            </div>
          )}
        </Section>
      )}
    </>
  );
}

function DocumentManagement({
  requirements,
  links,
  onUploadClick,
  uploadInputRef,
  onUploadChange,
  uploadNotice,
  onGenerate,
  onProcess,
  loading,
  generationStatus,
}) {
  const missing = (requirements || []).filter((requirement) => requirement.status === "not_found");
  const hasProcessableDocuments = (requirements || []).some((requirement) =>
    ["cache_found", "provided", "received"].includes(requirement.status),
  );
  return (
    <Section title="Document Management">
      <div className="document-actions">
        <button className="secondary" onClick={onUploadClick}>Upload Documents</button>
        <input
          ref={uploadInputRef}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={onUploadChange}
        />
        {uploadNotice && <span className="upload-note">{uploadNotice}</span>}
        <button disabled={loading || !missing.length} onClick={onGenerate}>Generate Missing Documents</button>
        <button disabled={loading || !hasProcessableDocuments} onClick={onProcess}>Process Documents</button>
      </div>

      {requirements.length ? (
        <table>
          <thead>
            <tr>
              <th>Document Name</th>
              <th>Found in Cache</th>
              <th>Provided by Customer</th>
              <th>Processed</th>
            </tr>
          </thead>
          <tbody>
            {requirements.map((requirement) => {
              const foundInCache = Boolean(requirement.cache_document);
              const provided = !foundInCache && ["customer_upload", "generated"].includes(requirement.source);
              const cacheLink = foundInCache ? links[documentKey(requirement.cache_document)] : null;
              return (
                <tr key={requirement.id}>
                  <td>{documentLabel(requirement.document_type)} — {requirement.entity_name}</td>
                  <td>
                    {foundInCache && cacheLink?.url ? (
                      <a className="download-link" href={cacheLink.url} target="_blank" rel="noreferrer">Yes</a>
                    ) : (foundInCache ? "Yes" : "No")}
                  </td>
                  <td className={foundInCache ? "document-muted" : ""}>
                    {foundInCache ? "N/A" : (provided ? "Yes" : "No")}
                  </td>
                  <td>{requirement.status === "processed" ? "Yes" : "No"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : <p className="empty">Run the CDD pipeline to determine required documents.</p>}
      {generationStatus && <p className="empty">{generationStatus}</p>}
    </Section>
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

function MarkdownMessage({ content }) {
  const lines = String(content || "").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }
    const heading = lines[index].match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const Tag = `h${heading[1].length + 2}`;
      blocks.push(<Tag key={`heading-${index}`}>{renderMarkdownInline(heading[2])}</Tag>);
      index += 1;
      continue;
    }
    const unordered = lines[index].match(/^\s*[-*+]\s+(.+)$/);
    const ordered = lines[index].match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const ItemList = unordered ? "ul" : "ol";
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(unordered ? /^\s*[-*+]\s+(.+)$/ : /^\s*\d+[.)]\s+(.+)$/);
        if (!item) break;
        items.push(<li key={`item-${index}`}>{renderMarkdownInline(item[1])}</li>);
        index += 1;
      }
      blocks.push(<ItemList key={`list-${index}`}>{items}</ItemList>);
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim()
      && !/^#{1,3}\s+/.test(lines[index])
      && !/^\s*[-*+]\s+/.test(lines[index])
      && !/^\s*\d+[.)]\s+/.test(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${index}`}>
        {paragraph.flatMap((line, lineIndex) => [
          ...(lineIndex ? [<br key={`break-${lineIndex}`} />] : []),
          ...renderMarkdownInline(line),
        ])}
      </p>,
    );
  }

  return <>{blocks}</>;
}

function renderMarkdownInline(value) {
  const tokens = [];
  const expression = /(\[([^\]]+)\]\(([^\s)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
  let cursor = 0;
  let match;
  while ((match = expression.exec(value)) !== null) {
    if (match.index > cursor) tokens.push(value.slice(cursor, match.index));
    if (match[2]) {
      const href = safeMarkdownHref(match[3]);
      tokens.push(href
        ? <a key={`link-${match.index}`} href={href} target="_blank" rel="noreferrer">{match[2]}</a>
        : match[0]);
    } else if (match[4]) {
      tokens.push(<code key={`code-${match.index}`}>{match[4]}</code>);
    } else {
      tokens.push(<strong key={`strong-${match.index}`}>{match[5]}</strong>);
    }
    cursor = expression.lastIndex;
  }
  if (cursor < value.length) tokens.push(value.slice(cursor));
  return tokens;
}

function safeMarkdownHref(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function SubTable({ title, columns, rows, empty }) {
  return (
    <div className="subtable">
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

function joinList(values) {
  return (values || []).filter(Boolean).join(", ");
}

function documentLabel(value) {
  const labels = {
    passport: "Passport",
    national_id: "National ID",
    registry_document: "Registry Document",
  };
  return labels[value] || value || "-";
}

function documentDescription(document) {
  const label = documentLabel(document.category || document.document_type);
  if (document.person_name) return `${label} of ${document.person_name}`;
  return label === "-" ? document.name || "Case document" : label;
}

function documentKey(document) {
  return document?.storage?.key || "";
}

function secondsRemaining(expiresAt, now) {
  const expiry = new Date(expiresAt).getTime();
  if (Number.isNaN(expiry)) return 0;
  return Math.max(0, Math.floor((expiry - now) / 1000));
}

function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function statusLabel(value) {
  if (!value) return "-";
  return String(value)
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
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
  if (source.source) lines.push(`Source: ${source.source}`);
  else if (source.api) lines.push(`API: ${source.api}`);
  if (source.field) lines.push(`Field: ${source.field}`);
  return lines.length ? lines.join("\n") : null;
}

function latestAssistantMessage(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant" && messages[index].content) {
      return messages[index].content;
    }
  }
  return null;
}

function cddStatusLabel(status) {
  return status === "complete" ? "Complete" : "Incomplete";
}

function formatPipelineProgress(progress) {
  const position = progress.node_number && progress.total_nodes
    ? `Step ${progress.node_number} of ${progress.total_nodes}: `
    : "";
  const cache = progress.using_cache ? " (using cache)" : "";
  const failure = progress.status === "error" && progress.error
    ? ` — ${progress.error}`
    : "";
  return `${position}${progress.message || "Working"}${cache}${failure}`;
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

function riskFlags(records) {
  return Array.isArray(records) ? records : [];
}

function riskPresentation(risk) {
  const assessment = risk.evidence?.assessment || {};
  const evaluation = String(assessment.is_csp || risk.description?.match(/Evaluation:\s*(Yes|No|Inconclusive)/i)?.[1] || "Inconclusive");
  const category = risk.category || "risk";
  const summaries = {
    ownership: {
      title: "Ownership Risk",
      yes: "No individual UBO above 25% was identified.",
      no: "Individual UBOs above 25% were identified.",
      inconclusive: "Ownership review is required.",
    },
    aml: {
      title: "AML Risk",
      yes: "An AML-positive controlling member requires review.",
      no: "No AML-positive controlling member was identified.",
      inconclusive: "AML review is required.",
    },
    csp_address: {
      title: "CSP Risk",
      yes: "The address appears to be used by a company service provider.",
      no: "No company service provider indicator was identified.",
      inconclusive: "The address requires further review.",
    },
  };
  const presentation = summaries[category] || {
    title: "Risk Assessment",
    yes: "A review item was identified.",
    no: "No review item was identified.",
    inconclusive: "Further review is required.",
  };
  const outcome = evaluation.toLowerCase();
  return { title: presentation.title, evaluation, summary: presentation[outcome] || presentation.inconclusive };
}

function RiskEvidenceTooltip({ risk }) {
  const evidence = risk.evidence || {};
  const assessment = evidence.assessment || {};
  const sources = evidence.sources || [];
  const detail = assessment.explanation || risk.description || "No detailed explanation is available.";
  return (
    <span className="source-tip risk-evidence-tip" tabIndex="0" aria-label="View risk evidence">
      i
      <span className="source-tooltip risk-evidence-tooltip" role="tooltip">
        <span>{detail}</span>
        {sources.map((source, index) => (
          <a key={`${source.url || source.title}-${index}`} href={source.url} target="_blank" rel="noreferrer">
            {source.title || source.url || "Source"}
          </a>
        ))}
      </span>
    </span>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
