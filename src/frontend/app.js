const { useEffect, useMemo, useRef, useState } = React;

const FALLBACK_JURISDICTIONS = ["GB", "HK", "US", "SG"];
const TOOL_WORKSPACES = [
  { id: "csp", label: "CSP Detection" },
  { id: "digital-footprint", label: "Digital Footprint" },
  { id: "document-extraction", label: "Document Extraction" },
  { id: "idv-document-generation", label: "ID&V Document Generation" },
];

function App() {
  const [sessionId, setSessionId] = useState(null);
  const [demoMode, setDemoMode] = useState(false);
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
  const [caseReviewSummary, setCaseReviewSummary] = useState(null);
  const [caseReviewDecision, setCaseReviewDecision] = useState(null);
  const [reviewDecisionDraft, setReviewDecisionDraft] = useState("request_information");
  const [reviewNote, setReviewNote] = useState("");
  const [caseReviewLoading, setCaseReviewLoading] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [documentRequirements, setDocumentRequirements] = useState([]);
  const [generationStatus, setGenerationStatus] = useState("");
  const [activeWorkspace, setActiveWorkspace] = useState("cdd");
  const [caseStatus, setCaseStatus] = useState({
    cdd_generation: "not_started",
    risk_summary: { by_category: {}, totals: { yes: 0, inconclusive: 0, no: 0 } },
  });
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [cspCompanyName, setCspCompanyName] = useState("");
  const [cspAddress, setCspAddress] = useState("");
  const [cspResult, setCspResult] = useState(null);
  const [cspError, setCspError] = useState("");
  const [cspAssessing, setCspAssessing] = useState(false);
  const [cspSkill, setCspSkill] = useState("");
  const [cspSkillLoading, setCspSkillLoading] = useState(false);
  const [digitalFootprintForm, setDigitalFootprintForm] = useState({ company_name: "", jurisdiction: "", registration_number: "", known_domain: "", registered_address: "" });
  const [digitalFootprintResult, setDigitalFootprintResult] = useState(null);
  const [digitalFootprintError, setDigitalFootprintError] = useState("");
  const [digitalFootprintAssessing, setDigitalFootprintAssessing] = useState(false);
  const [digitalFootprintSkill, setDigitalFootprintSkill] = useState("");
  const [digitalFootprintSkillLoading, setDigitalFootprintSkillLoading] = useState(false);
  const [extractionFile, setExtractionFile] = useState(null);
  const [extractionResult, setExtractionResult] = useState(null);
  const [extractionError, setExtractionError] = useState("");
  const [extractingDocument, setExtractingDocument] = useState(false);
  const [idvDocumentForm, setIdvDocumentForm] = useState({
    full_name: "",
    document_type: "passport",
    nationality: "",
    issuing_country: "",
    address: "",
  });
  const [idvDocumentResult, setIdvDocumentResult] = useState(null);
  const [idvDocumentError, setIdvDocumentError] = useState("");
  const [generatingIdvDocument, setGeneratingIdvDocument] = useState(false);
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
  const extractionInputRef = useRef(null);
  const chatLauncherRef = useRef(null);
  const chatCloseRef = useRef(null);
  const toolsMenuRef = useRef(null);
  const toolsMenuButtonRef = useRef(null);
  const cddRunEpochRef = useRef(0);

  const profile = cdd?.company_business_profile?.customer_static || {};
  const ownership = cdd?.ownership_and_control || {};
  const idv = cdd?.individual_identity_verification || {};
  const risks = useMemo(() => riskFlags(riskFlagRecords), [riskFlagRecords]);
  const capital = capitalDisplay(profile);
  const fieldSources = profile.source || {};
  const cddMetadata = {
    customer: profile.name || customerName || "-",
    date: formatDateTime(cdd?.completed_at || cdd?.started_at),
    generationStatus: caseStatus.cdd_generation || "not_started",
    riskSummary: caseStatus.risk_summary?.totals || { yes: 0, inconclusive: 0, no: 0 },
  };
  const pipelineStatusText = pipelineProgress
    ? formatPipelineProgress(pipelineProgress)
    : latestAssistantMessage(messages) || "Setting up";
  const pipelineRunning = pipelineStatus === "running" || pipelineStatus === "awaiting_documents";
  const missingDocumentRequirements = useMemo(
    () => documentRequirements.filter((requirement) => requirement.status === "not_found"),
    [documentRequirements],
  );
  const cddPausedForDocuments = pipelineStatus === "awaiting_documents";
  const chatWorkspaceActive = activeWorkspace === "cdd" || activeWorkspace === "case-review";
  const activeToolWorkspace = TOOL_WORKSPACES.some((tool) => tool.id === activeWorkspace);
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
    let ignore = false;
    async function loadDemoMode() {
      try {
        const response = await fetch("/api/demo/status");
        const data = await readJsonResponse(response, "Demo Mode status request failed");
        if (!ignore) setDemoMode(Boolean(data.demo_mode));
      } catch (err) {
        if (!ignore) setError(err.message);
      }
    }
    loadDemoMode();
    return () => { ignore = true; };
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!chatWorkspaceActive) setChatOpen(false);
  }, [chatWorkspaceActive]);

  useEffect(() => {
    if (!chatOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setChatOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [chatOpen]);

  useEffect(() => {
    if (chatOpen) {
      chatCloseRef.current?.focus();
    } else if (chatWorkspaceActive) {
      chatLauncherRef.current?.focus();
    }
  }, [chatOpen, chatWorkspaceActive]);

  useEffect(() => {
    if (!toolsMenuOpen) return undefined;

    const closeMenu = (event) => {
      if (event.type === "keydown" && event.key === "Escape") {
        setToolsMenuOpen(false);
        toolsMenuButtonRef.current?.focus();
      } else if (event.type === "mousedown" && !toolsMenuRef.current?.contains(event.target)) {
        setToolsMenuOpen(false);
      }
    };

    document.addEventListener("keydown", closeMenu);
    document.addEventListener("mousedown", closeMenu);
    return () => {
      document.removeEventListener("keydown", closeMenu);
      document.removeEventListener("mousedown", closeMenu);
    };
  }, [toolsMenuOpen]);

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
    setCaseStatus(data.case_status || { cdd_generation: "not_started", risk_summary: { by_category: {}, totals: { yes: 0, inconclusive: 0, no: 0 } } });
    setCaseReviewSummary(data.case_review_summary || null);
    setCaseReviewDecision(data.case_review_decision || null);
    if (data.demo_csp_result) setCspResult(data.demo_csp_result);
    setDocuments(data.documents || []);
    setDocumentRequirements(data.document_requirements || []);
    setDocumentLinks((current) => {
      const keys = new Set([
        ...(data.documents || []).map((document) => documentKey(document)),
        ...(data.document_requirements || []).map((requirement) => documentKey(requirement.cache_document)),
      ].filter(Boolean));
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
    if (typeof data.demo_mode === "boolean") setDemoMode(data.demo_mode);
    if (data.error) setError(data.error);
  }

  function resetCddRunDisplay() {
    cddRunEpochRef.current += 1;
    setCdd(null);
    setRiskFlagRecords([]);
    setCaseStatus({
      cdd_generation: "in_progress",
      risk_summary: { by_category: {}, totals: { yes: 0, inconclusive: 0, no: 0 } },
    });
    setCaseReviewSummary(null);
    setCaseReviewDecision(null);
    setReviewNote("");
    setDocuments([]);
    setDocumentRequirements([]);
    setDocumentLinks({});
    setRefreshingDocumentKey(null);
    setPdfUrl(null);
    setPipelineProgress(null);
    setPipelineStatus("running");
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
    if (!demoMode && (!customerName.trim() || !jurisdiction.trim())) return;
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
      if (data.status === "running") resetCddRunDisplay();
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

  async function loadDemoCase() {
    setPipelineLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/demo/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      applyResponse(await readJsonResponse(response, "Unable to load demo case"));
      setActiveWorkspace("cdd");
    } catch (err) {
      setError(err.message);
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

  async function refreshCaseReview() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/case-review/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      applyResponse(await readJsonResponse(response, "Case review refresh failed"));
    } catch (err) {
      setError(err.message);
    } finally {
      setCaseReviewLoading(false);
    }
  }

  async function saveCaseReviewDecision() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/case-review/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          decision: reviewDecisionDraft,
          note: reviewNote,
        }),
      });
      applyResponse(await readJsonResponse(response, "Unable to record reviewer decision"));
    } catch (err) {
      setError(err.message);
    } finally {
      setCaseReviewLoading(false);
    }
  }

  async function refreshDocumentLink(document) {
    const key = documentKey(document);
    if (!sessionId || !key) return;
    const runEpoch = cddRunEpochRef.current;
    const activeSessionId = sessionId;
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
      if (runEpoch === cddRunEpochRef.current && activeSessionId === sessionId) {
        setDocumentLinks((current) => ({ ...current, [key]: data }));
      }
    } catch (err) {
      if (runEpoch === cddRunEpochRef.current) setError(err.message);
    } finally {
      if (runEpoch === cddRunEpochRef.current) setRefreshingDocumentKey(null);
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

  async function loadDigitalFootprintSkill() {
    if (digitalFootprintSkill || digitalFootprintSkillLoading) return;
    setDigitalFootprintSkillLoading(true);
    try {
      const response = await fetch("/api/digital-footprint/skill");
      const data = await readJsonResponse(response, "Unable to load Digital Footprint skill");
      setDigitalFootprintSkill(data.skill || "");
    } catch (err) {
      setDigitalFootprintError(err.message);
    } finally {
      setDigitalFootprintSkillLoading(false);
    }
  }

  function updateDigitalFootprintForm(field, value) {
    setDigitalFootprintForm((current) => ({ ...current, [field]: value }));
  }

  async function assessDigitalFootprint() {
    if (!digitalFootprintForm.company_name.trim()) return;
    setDigitalFootprintAssessing(true);
    setDigitalFootprintError("");
    setDigitalFootprintResult(null);
    try {
      const response = await fetch("/api/digital-footprint/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(Object.entries(digitalFootprintForm).map(([key, value]) => [key, value.trim() || null]))),
      });
      setDigitalFootprintResult(await readJsonResponse(response, "Digital Footprint assessment failed"));
    } catch (err) {
      setDigitalFootprintError(err.message);
    } finally {
      setDigitalFootprintAssessing(false);
    }
  }

  function selectExtractionFile(event) {
    setExtractionFile(event.target.files?.[0] || null);
    setExtractionResult(null);
    setExtractionError("");
  }

  async function extractStandaloneDocument() {
    if (!extractionFile) return;
    setExtractingDocument(true);
    setExtractionError("");
    setExtractionResult(null);
    try {
      const body = new FormData();
      body.append("file", extractionFile);
      const response = await fetch("/api/document-extraction/extract", { method: "POST", body });
      setExtractionResult(await readJsonResponse(response, "Document extraction failed"));
    } catch (err) {
      setExtractionError(err.message);
    } finally {
      setExtractingDocument(false);
    }
  }

  function updateIdvDocumentForm(field, value) {
    setIdvDocumentForm((current) => ({ ...current, [field]: value }));
    setIdvDocumentResult(null);
    setIdvDocumentError("");
  }

  async function generateStandaloneIdvDocument() {
    if (!idvDocumentForm.full_name.trim()) return;
    setGeneratingIdvDocument(true);
    setIdvDocumentError("");
    setIdvDocumentResult(null);
    try {
      const response = await fetch("/api/idv-document-generation/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...idvDocumentForm,
          full_name: idvDocumentForm.full_name.trim(),
          nationality: idvDocumentForm.nationality.trim() || null,
          issuing_country: idvDocumentForm.issuing_country.trim() || null,
          address: idvDocumentForm.address.trim() || null,
        }),
      });
      const result = await readJsonResponse(response, "ID&V document generation failed");
      await downloadStandaloneIdvDocument(result);
      setIdvDocumentResult(result);
    } catch (err) {
      setIdvDocumentError(err.message);
    } finally {
      setGeneratingIdvDocument(false);
    }
  }

  async function downloadStandaloneIdvDocument(result) {
    const response = await fetch(result.pdf_url);
    if (!response.ok) throw new Error("Generated document download failed");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `synthetic-${result.document_type || "identity-document"}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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
        {demoMode && <span className="badge demo">Demo Mode — no external services</span>}
      </header>

      <div className="workspace">
        <main className="main">
          <nav className="workspace-tabs" aria-label="Workspace">
            <button
              className={`workspace-tab ${activeWorkspace === "cdd" ? "active" : ""}`}
              onClick={() => setActiveWorkspace("cdd")}
            >
              CDD
            </button>
            <button
              className={`workspace-tab ${activeWorkspace === "case-review" ? "active" : ""}`}
              onClick={() => setActiveWorkspace("case-review")}
            >
              Case Review
            </button>
            <button
              className={`workspace-tab ${activeWorkspace === "generation" ? "active" : ""}`}
              onClick={() => setActiveWorkspace("generation")}
            >
              Documents
            </button>
            <div className="workspace-tools" ref={toolsMenuRef}>
              <button
                className={`workspace-tab workspace-tools-trigger ${activeToolWorkspace ? "active" : ""}`}
                ref={toolsMenuButtonRef}
                aria-expanded={toolsMenuOpen}
                aria-controls="workspace-tools-menu"
                aria-haspopup="menu"
                onClick={() => setToolsMenuOpen((open) => !open)}
              >
                Tools <span aria-hidden="true">▾</span>
              </button>
              {toolsMenuOpen && (
                <div className="workspace-tools-menu" id="workspace-tools-menu" role="menu">
                  {TOOL_WORKSPACES.map((tool) => (
                    <button
                      key={tool.id}
                      className={activeWorkspace === tool.id ? "active" : ""}
                      role="menuitem"
                      onClick={() => {
                        setActiveWorkspace(tool.id);
                        setToolsMenuOpen(false);
                      }}
                    >
                      {tool.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </nav>

          <div className="workspace-tab-panel">
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
                disabled={pipelineLoading || (!demoMode && !customerName.trim())}
                onClick={() => runPipeline()}
              >
                Run Full CDD Pipeline
              </button>
              {demoMode && <button className="secondary" disabled={pipelineLoading} onClick={loadDemoCase}>Load Demo Case</button>}
            </div>
            {pipelineLoading && <p className="empty">{pipelineStatusText}</p>}
          </Section>

          {cddPausedForDocuments && (
            <section className="pipeline-paused-callout" aria-live="polite">
              <div>
                <strong>CDD paused — documents required</strong>
                <p>
                  {`${missingDocumentRequirements.length} required ID&V ${missingDocumentRequirements.length === 1 ? "document is" : "documents are"} unavailable.`}
                  {" Generate the missing documents or upload them to continue the CDD pipeline."}
                </p>
              </div>
              <button onClick={() => setActiveWorkspace("generation")}>Review required documents</button>
            </section>
          )}

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
              <span>CDD Generation</span>
              <strong>{generationStatusLabel(cddMetadata.generationStatus)}</strong>
            </div>
            <div className="metadata-item">
              <span>Risk Flags</span>
              <strong className="risk-summary">
                <span className={cddMetadata.riskSummary.yes > 0 ? "risk-flags-present" : ""}>{`${cddMetadata.riskSummary.yes} Yes`}</span>
                <span className={cddMetadata.riskSummary.inconclusive > 0 ? "risk-flags-inconclusive" : ""}>{`${cddMetadata.riskSummary.inconclusive} Inconclusive`}</span>
                <span>{`${cddMetadata.riskSummary.no} No`}</span>
              </strong>
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
                      <strong>{`${riskCategoryLabel(risk.category)}${risk.subject?.name ? ` — ${risk.subject.name}` : ""}`}</strong>
                      <span>{`Evaluation: ${statusLabel(risk.evaluation)}. Severity: ${statusLabel(risk.severity)}. ${risk.description || ""}`}</span>
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
                demoMode={demoMode}
              />
            ) : activeWorkspace === "case-review" ? (
              <CaseReview
                summary={caseReviewSummary}
                decision={caseReviewDecision}
                decisionDraft={reviewDecisionDraft}
                note={reviewNote}
                loading={caseReviewLoading}
                hasCdd={Boolean(cdd)}
                onRefresh={refreshCaseReview}
                onDecisionChange={setReviewDecisionDraft}
                onNoteChange={setReviewNote}
                onSaveDecision={saveCaseReviewDecision}
                demoMode={demoMode}
              />
            ) : activeWorkspace === "csp" ? (
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
                demoMode={demoMode}
              />
            ) : activeWorkspace === "digital-footprint" ? (
              <DigitalFootprint
                form={digitalFootprintForm}
                result={digitalFootprintResult}
                error={digitalFootprintError}
                assessing={digitalFootprintAssessing}
                skill={digitalFootprintSkill}
                skillLoading={digitalFootprintSkillLoading}
                onChange={updateDigitalFootprintForm}
                onSkillToggle={(open) => { if (open) loadDigitalFootprintSkill(); }}
                onAssess={assessDigitalFootprint}
                demoMode={demoMode}
              />
            ) : activeWorkspace === "document-extraction" ? (
              <DocumentExtraction
                file={extractionFile}
                result={extractionResult}
                error={extractionError}
                extracting={extractingDocument}
                inputRef={extractionInputRef}
                onFileChange={selectExtractionFile}
                onExtract={extractStandaloneDocument}
                demoMode={demoMode}
              />
            ) : (
              <IDVDocumentGeneration
                form={idvDocumentForm}
                result={idvDocumentResult}
                error={idvDocumentError}
                generating={generatingIdvDocument}
                onChange={updateIdvDocumentForm}
                onGenerate={generateStandaloneIdvDocument}
                demoMode={demoMode}
              />
            )}
          </div>
        </main>

        {chatWorkspaceActive && (
          <>
            <button
              className="chat-launcher"
              ref={chatLauncherRef}
              aria-label="Open onboarding chat"
              aria-expanded={chatOpen}
              aria-controls="onboarding-chat"
              onClick={() => setChatOpen(true)}
            >
              <span aria-hidden="true">💬</span>
              <span className="chat-launcher-label">Chat</span>
            </button>

            {chatOpen && (
              <aside
                className="chat"
                id="onboarding-chat"
                role="dialog"
                aria-label="Onboarding chat"
              >
                <div className="chat-head">
                  <h1>Onboarding Chat - for deeper probing</h1>
                  <button ref={chatCloseRef} className="chat-close" aria-label="Close onboarding chat" onClick={() => setChatOpen(false)}>×</button>
                </div>

                <div className="messages">
                  {messages.map((item, index) => (
                    <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                      <MarkdownMessage content={item.content} />
                    </div>
                  ))}
                  {loading && <div className="message assistant">Thinking...</div>}
                </div>

                <div className="composer">
                  <textarea
                    aria-label="Message"
                    placeholder='Try "what test cases are available in GB?" or "fetch the org chart for Cropwell Bishop Creamery Limited, GB"'
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) sendChat();
                    }}
                  />
                  <div className="send-row">
                    <button disabled={loading || demoMode} onClick={() => sendChat()}>Ask</button>
                  </div>
                  {error && <div className="risk">{error}</div>}
                </div>
              </aside>
            )}
          </>
        )}
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

function CaseReview({
  summary,
  decision,
  decisionDraft,
  note,
  loading,
  hasCdd,
  onRefresh,
  onDecisionChange,
  onNoteChange,
  onSaveDecision,
  demoMode,
}) {
  if (!hasCdd) {
    return (
      <Section title="Case Review">
        <p className="empty">Run a CDD case to generate an evidence-grounded reviewer brief.</p>
      </Section>
    );
  }

  const evidenceById = Object.fromEntries((summary?.evidence_index || []).map((item) => [item.id, item]));
  return (
    <>
      <Section title="Case Review">
        <div className="case-review-header">
          <div>
            <p className="review-disclaimer">Decision support only. A human reviewer remains responsible for the case decision.</p>
          </div>
          <button disabled={loading || demoMode} onClick={onRefresh}>
            {demoMode ? "Fixture summary" : (loading ? "Refreshing…" : summary ? "Refresh summary" : "Generate summary")}
          </button>
        </div>
        {!summary ? (
          <p className="empty">No case review has been generated yet.</p>
        ) : (
          <>
            {summary.status === "unavailable" && <p className="risk">The generated review is unavailable. The recorded CDD evidence remains available for review.</p>}
            <h3>Executive summary</h3>
            <p>{summary.executive_summary}</p>
          </>
        )}
      </Section>

      {summary && (
        <>
          <Section title="Key Evidence">
            {summary.key_evidence?.length ? (
              <div className="review-list">
                {summary.key_evidence.map((item, index) => (
                  <div className="review-item" key={`${item.category}-${index}`}>
                    <strong>{item.category}</strong>
                    <p>{item.finding}</p>
                    {item.source_refs?.length > 0 && (
                      <small>
                        Evidence: {item.source_refs.map((sourceRef, sourceIndex) => {
                          const evidenceItem = evidenceById[sourceRef];
                          const url = evidenceItem?.urls?.[0];
                          return (
                            <React.Fragment key={sourceRef}>
                              {sourceIndex > 0 && ", "}
                              {url ? <a href={url} target="_blank" rel="noreferrer">{sourceRef}</a> : sourceRef}
                            </React.Fragment>
                          );
                        })}
                      </small>
                    )}
                  </div>
                ))}
              </div>
            ) : <p className="empty">No evidence summary was generated.</p>}
          </Section>

          <Section title="Uncertainty & Limitations">
            <BulletList items={summary.limitations} empty="No material limitations were recorded." />
          </Section>

          <Section title="Recommended Analyst Actions">
            <BulletList items={summary.recommended_actions} empty="No additional analyst actions were recommended." />
          </Section>

          <Section title="Request for Information">
            {summary.requests_for_information?.length ? (
              <div className="review-list">
                {summary.requests_for_information.map((item, index) => (
                  <div className="review-item" key={`${item.request}-${index}`}>
                    <strong>{item.request}</strong>
                    <p>{item.reason}</p>
                    <small>{`Addresses: ${item.risk_or_gap} · Priority: ${item.priority}`}</small>
                  </div>
                ))}
              </div>
            ) : <p className="empty">No customer information is currently requested.</p>}
          </Section>
        </>
      )}

      <Section title="Reviewer Decision">
        <div className="review-decision">
          <label>
            Decision
            <select value={decisionDraft} onChange={(event) => onDecisionChange(event.target.value)}>
              <option value="approve">Approve</option>
              <option value="request_information">Request information</option>
              <option value="escalate">Escalate</option>
            </select>
          </label>
          <label>
            Reviewer note
            <textarea value={note} onChange={(event) => onNoteChange(event.target.value)} placeholder="Optional rationale or follow-up note" />
          </label>
          <button disabled={loading} onClick={onSaveDecision}>Record decision</button>
          {decision && <p className="review-recorded">Recorded: {decisionLabel(decision.decision)}{decision.recorded_at ? ` on ${formatDateTime(decision.recorded_at)}` : ""}</p>}
        </div>
      </Section>
    </>
  );
}

function BulletList({ items, empty }) {
  return items?.length ? <ul className="review-bullets">{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <p className="empty">{empty}</p>;
}

function decisionLabel(value) {
  return ({ approve: "Approve", request_information: "Request information", escalate: "Escalate" })[value] || value;
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
  demoMode,
}) {
  const assessment = result?.assessment || {};
  const presentation = result
    ? riskPresentation({ category: "csp_address", evidence: result })
    : null;
  return (
    <>
      <Section title="CSP Detection">
        {demoMode && <p className="empty">Demo Mode uses the CSP evidence in the loaded case; live address assessment is disabled.</p>}
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
          <button disabled={demoMode || assessing || !address.trim()} onClick={onAssess}>
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

function DigitalFootprint({ form, result, error, assessing, skill, skillLoading, onChange, onSkillToggle, onAssess, demoMode }) {
  const assessment = result?.assessment || {};
  const adverseNews = assessment.adverse_news || {};
  const footprint = result?.business_footprint || {};
  return (
    <>
      <Section title="Digital Footprint">
        {demoMode && <p className="empty">Digital Footprint assessment is disabled in Demo Mode.</p>}
        <p className="empty">Research a company independently of any CDD case. Results are public-web research support, not a compliance decision.</p>
        <details className="skill-details" onToggle={(event) => onSkillToggle(event.currentTarget.open)}>
          <summary>Assessment skill</summary>
          {skillLoading ? <p className="empty">Loading skill…</p> : <pre className="skill-content">{skill || "Open this section to load the current skill."}</pre>}
        </details>
        <div className="csp-form digital-footprint-form">
          <input aria-label="Company legal name" placeholder="Company legal name" value={form.company_name} disabled={demoMode || assessing} onChange={(event) => onChange("company_name", event.target.value)} />
          <input aria-label="Jurisdiction" placeholder="Jurisdiction (optional)" value={form.jurisdiction} disabled={demoMode || assessing} onChange={(event) => onChange("jurisdiction", event.target.value)} />
          <input aria-label="Registration number" placeholder="Registration number (optional)" value={form.registration_number} disabled={demoMode || assessing} onChange={(event) => onChange("registration_number", event.target.value)} />
          <input aria-label="Known website or domain" placeholder="Known website or domain (optional)" value={form.known_domain} disabled={demoMode || assessing} onChange={(event) => onChange("known_domain", event.target.value)} />
          <textarea aria-label="Registered address" placeholder="Registered address (optional)" value={form.registered_address} disabled={demoMode || assessing} onChange={(event) => onChange("registered_address", event.target.value)} />
          <button disabled={demoMode || assessing || !form.company_name.trim()} onClick={onAssess}>{assessing ? "Assessing…" : "Assess footprint"}</button>
        </div>
        {error && <p className="risk">{error}</p>}
      </Section>

      {result && (
        <>
          <Section title="Footprint Assessment">
            <dl className="field-list">
              <div><dt>Strength</dt><dd>{assessment.footprint_strength || "-"}</dd></div>
              <div><dt>Confidence</dt><dd>{assessment.confidence || "-"}</dd></div>
              <div><dt>Adverse news</dt><dd>{adverseNews.status || "-"}</dd></div>
              <div><dt>Adverse-news confidence</dt><dd>{adverseNews.confidence || "-"}</dd></div>
            </dl>
            <div className="review-list">
              {Object.entries(assessment.dimensions || {}).map(([name, item]) => <div className="review-item" key={name}><strong>{name.replaceAll("_", " ")}</strong><p>{`${item.rating || "-"}: ${item.rationale || "No rationale provided."}`}</p></div>)}
            </div>
          </Section>
          <Section title="Adverse News">
            {adverseNews.items?.length ? <div className="review-list">{adverseNews.items.map((item, index) => <div className="review-item" key={`${item.subject}-${index}`}><strong>{`${item.subject} — ${item.disposition}`}</strong><p>{item.summary}</p><small>{item.category}</small></div>)}</div> : <p className="empty">No material adverse-news items were returned. Review search coverage limitations below.</p>}
          </Section>
          <Section title="Business Footprint">
            <p><strong>Nature of business:</strong> {footprint.nature_of_business?.publicly_observed || "Unavailable"}</p>
            <p><strong>Consistency:</strong> {footprint.nature_of_business?.consistency || "Unavailable"}</p>
            <BulletList items={assessment.limitations} empty="No limitations recorded." />
            <BulletList items={assessment.recommended_actions} empty="No additional actions recommended." />
          </Section>
          <Section title="Sources">
            <div className="csp-sources">{(result.sources || []).map((source) => <div key={source.id}><a href={source.url} target="_blank" rel="noreferrer">{source.title || source.url || source.id}</a><small>{` — ${source.query}`}</small></div>)}</div>
          </Section>
          <Section title="Digital Footprint JSON"><pre className="json-view">{JSON.stringify(result, null, 2)}</pre></Section>
        </>
      )}
    </>
  );
}

function DocumentExtraction({ file, result, error, extracting, inputRef, onFileChange, onExtract, demoMode }) {
  return (
    <>
      <Section title="Document Extraction">
        {demoMode && <p className="empty">Document extraction is disabled in Demo Mode.</p>}
        <p className="empty">Upload a PDF or image to classify it and extract supported document data without changing the active CDD case.</p>
        <div className="csp-form">
          <input
            ref={inputRef}
            aria-label="Document file"
            type="file"
            accept="application/pdf,image/png,image/jpeg,image/webp,image/gif,.pdf,.png,.jpg,.jpeg,.webp,.gif"
            disabled={demoMode || extracting}
            onChange={onFileChange}
          />
          <button disabled={demoMode || extracting || !file} onClick={onExtract}>
            {extracting ? "Extracting…" : "Extract"}
          </button>
        </div>
        {file && <p className="upload-note">Selected: {file.name}</p>}
        {error && <p className="risk">{error}</p>}
      </Section>

      {result && (
        <>
          <Section title="Classification">
            <dl className="field-list">
              <div><dt>Document type</dt><dd>{result.classification?.document_type || "Unknown"}</dd></div>
              <div><dt>Confidence</dt><dd>{result.classification?.confidence ?? "-"}</dd></div>
              <div><dt>Reason</dt><dd>{result.classification?.reason || "-"}</dd></div>
            </dl>
          </Section>
          <Section title="Extracted JSON">
            <pre className="json-view">{JSON.stringify(result.extraction, null, 2)}</pre>
          </Section>
        </>
      )}
    </>
  );
}

function IDVDocumentGeneration({ form, result, error, generating, onChange, onGenerate, demoMode }) {
  return (
    <>
      <Section title="ID&V Document Generation">
        {demoMode && <p className="empty">ID&V document generation is disabled in Demo Mode.</p>}
        <p className="empty">Generate a synthetic demo identity document. It is not valid for identity verification.</p>
        <div className="idv-generation-form">
          <input aria-label="Full name" placeholder="Full name" value={form.full_name} disabled={demoMode || generating} onChange={(event) => onChange("full_name", event.target.value)} />
          <select aria-label="Document type" value={form.document_type} disabled={demoMode || generating} onChange={(event) => onChange("document_type", event.target.value)}>
            <option value="passport">Passport</option>
            <option value="national_id">National ID</option>
          </select>
          <input aria-label="Nationality" placeholder="Nationality (optional)" value={form.nationality} disabled={demoMode || generating} onChange={(event) => onChange("nationality", event.target.value)} />
          <input aria-label="Issuing country" placeholder="Issuing country (optional)" value={form.issuing_country} disabled={demoMode || generating} onChange={(event) => onChange("issuing_country", event.target.value)} />
          {form.document_type === "national_id" && <input aria-label="Address" placeholder="Address (optional)" value={form.address} disabled={demoMode || generating} onChange={(event) => onChange("address", event.target.value)} />}
          <button disabled={demoMode || generating || !form.full_name.trim()} onClick={onGenerate}>
            {generating ? "Generating…" : "Generate document"}
          </button>
        </div>
        {error && <p className="risk">{error}</p>}
      </Section>

      {result && (
        <Section title="Generated Document">
          <p className="risk">{result.notice}</p>
          <p><strong>{result.person_name}</strong> — {documentLabel(result.document_type)}</p>
          <p className="empty">The PDF download has started. The generated server files are now removed.</p>
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
  demoMode,
}) {
  const missing = (requirements || []).filter((requirement) => requirement.status === "not_found");
  const hasProcessableDocuments = (requirements || []).some((requirement) =>
    ["cache_found", "provided", "received"].includes(requirement.status),
  );
  return (
    <Section title="Document Management">
      <div className="document-actions">
        <button className="secondary" disabled={demoMode} onClick={onUploadClick}>Upload Documents</button>
        <input
          ref={uploadInputRef}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={onUploadChange}
        />
        {uploadNotice && <span className="upload-note">{uploadNotice}</span>}
        <button disabled={demoMode || loading || !missing.length} onClick={onGenerate}>Generate Missing Documents</button>
        <button disabled={demoMode || loading || !hasProcessableDocuments} onClick={onProcess}>Process Documents</button>
      </div>

      {missing.length > 0 && (
        <p className="document-required-note">
          {`${missing.length} required document${missing.length === 1 ? " is" : "s are"} unavailable. Generate the missing ID&V documents or upload customer-provided PDFs; CDD resumes automatically once all requirements are available.`}
        </p>
      )}

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
              const demoLink = requirement.demo_url;
              return (
                <tr key={requirement.id}>
                  <td>{documentLabel(requirement.document_type)} — {requirement.entity_name}</td>
                  <td>
                    {foundInCache && cacheLink?.url ? (
                      <a className="download-link" href={cacheLink.url} target="_blank" rel="noreferrer">Yes</a>
                    ) : demoLink ? (
                      <a className="download-link" href={demoLink} target="_blank" rel="noreferrer">Demo</a>
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

function generationStatusLabel(status) {
  return {
    not_started: "Not started",
    in_progress: "In Progress",
    completed: "Completed",
    incomplete: "Incomplete",
    failed: "Failed",
  }[status] || "Not started";
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

function riskCategoryLabel(category) {
  return {
    ownership: "Ownership Risk",
    aml: "AML Risk",
    csp_address: "CSP Risk",
  }[category] || "Risk Finding";
}

function RiskEvidenceTooltip({ risk }) {
  const evidence = risk.evidence || {};
  const sources = evidence.sources || [];
  const review = risk.case_review || null;
  const detail = risk.description || "No detailed explanation is available.";
  return (
    <span className="source-tip risk-evidence-tip" tabIndex="0" aria-label="View risk evidence">
      i
      <span className="source-tooltip risk-evidence-tooltip" role="tooltip">
        <strong>{`${riskCategoryLabel(risk.category)} — ${statusLabel(risk.evaluation)}`}</strong>
        {risk.subject?.name && <span>{`Subject: ${risk.subject.name}`}</span>}
        <span>{`Severity: ${statusLabel(risk.severity)}`}</span>
        <span>{detail}</span>
        {review ? (
          <>
            <span>{`Confidence: ${statusLabel(review.confidence)}. ${review.confidence_rationale}`}</span>
            <span>{`Potential impact: ${review.potential_impact_risk}`}</span>
            {review.recommended_action_or_rfi?.type !== "none" && (
              <span>{`${review.recommended_action_or_rfi?.type === "rfi" ? "RFI" : "Recommended action"}: ${review.recommended_action_or_rfi?.text}`}</span>
            )}
          </>
        ) : <span>Case Review assessment pending.</span>}
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
