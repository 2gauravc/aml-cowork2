const { useEffect, useMemo, useRef, useState } = React;

const FALLBACK_JURISDICTIONS = ["GB", "HK", "US", "SG"];
const ACCOUNT_OPENING_LOCATIONS = ["SG", "HK", "GB"];
const TOOL_WORKSPACES = [
  { id: "adverse-news", label: "Adverse News" },
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
  const [jurisdiction, setJurisdiction] = useState("");
  const [accountLocation, setAccountLocation] = useState("");
  const [jurisdictions, setJurisdictions] = useState(FALLBACK_JURISDICTIONS);
  const [message, setMessage] = useState("");
  const [cdd, setCdd] = useState(null);
  const [cddState, setCddState] = useState(null);
  const [caseAssessmentSummary, setCaseAssessmentSummary] = useState(null);
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
  const [digitalFootprintMode, setDigitalFootprintMode] = useState("independent");
  const [digitalFootprintResult, setDigitalFootprintResult] = useState(null);
  const [digitalFootprintError, setDigitalFootprintError] = useState("");
  const [digitalFootprintAssessing, setDigitalFootprintAssessing] = useState(false);
  const [digitalFootprintSkill, setDigitalFootprintSkill] = useState("");
  const [digitalFootprintSkillLoading, setDigitalFootprintSkillLoading] = useState(false);
  const [digitalFootprintAttaching, setDigitalFootprintAttaching] = useState(false);
  const [adverseNewsMode, setAdverseNewsMode] = useState("independent");
  const [adverseNewsResult, setAdverseNewsResult] = useState(null);
  const [adverseNewsNames, setAdverseNewsNames] = useState("");
  const [adverseNewsError, setAdverseNewsError] = useState("");
  const [adverseNewsRunning, setAdverseNewsRunning] = useState(false);
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
  const [jsonCopyStatus, setJsonCopyStatus] = useState("");
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
  const capital = capitalDisplay(profile);
  const fieldSources = profile.source || {};
  const principalBusinessActivity = latestAssessment(cddState, "digital_footprint")?.digital_business_profile?.business_activity || "";
  const cddMetadata = {
    customer: profile.name || customerName || "-",
    date: formatDateTime(cdd?.completed_at || cdd?.started_at),
    generationStatus: caseStatus.cdd_generation || "not_started",
  };
  const formattedCddState = cddState ? JSON.stringify(cddState, null, 2) : "";
  const pipelineStatusText = pipelineProgress
    ? formatPipelineProgress(pipelineProgress)
    : latestAssistantMessage(messages) || "Setting up";
  const pipelineRunning = pipelineStatus === "running" || pipelineStatus === "awaiting_documents";
  const missingDocumentRequirements = useMemo(
    () => documentRequirements.filter((requirement) => (requirement.gap || {}).status === "outstanding"),
    [documentRequirements],
  );
  const cddPausedForDocuments = pipelineStatus === "awaiting_documents";
  const chatWorkspaceActive = activeWorkspace === "cdd" || activeWorkspace === "case-review" || (activeWorkspace === "adverse-news" && adverseNewsMode === "cdd") || (activeWorkspace === "digital-footprint" && digitalFootprintMode === "cdd");
  const activeToolWorkspace = TOOL_WORKSPACES.some((tool) => tool.id === activeWorkspace);
  const documentKeyList = useMemo(
    () => documents.map((document) => documentKey(document)).filter(Boolean).join("|"),
    [documents],
  );

  async function copyCddStateJson() {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard access is unavailable");
      }
      await navigator.clipboard.writeText(formattedCddState);
      setJsonCopyStatus("Copied JSON to clipboard.");
    } catch {
      setJsonCopyStatus("Unable to copy JSON. Please select and copy it manually.");
    }
  }

  useEffect(() => {
    let ignore = false;

    async function loadJurisdictions() {
      try {
        const response = await fetch("/api/jurisdictions");
        const data = await readJsonResponse(response, "Jurisdictions request failed");
        if (!ignore && Array.isArray(data.jurisdictions) && data.jurisdictions.length) {
          setJurisdictions(data.jurisdictions);
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
      const key = documentKey(requirement);
      if (key && !documentLinks[key]) refreshDocumentLink(requirement);
    });
  }, [sessionId, documentRequirements, documentLinks]);

  function applyResponse(data) {
    setSessionId(data.session_id);
    setMessages(data.messages || []);
    setCdd(data.cdd || null);
    setCddState(data.cdd_state || null);
    setCaseStatus(data.case_status || { cdd_generation: "not_started" });
    setCaseAssessmentSummary(data.case_assessment_summary || null);
    setCaseReviewDecision(data.case_review_decision || null);
    if (data.demo_csp_result) setCspResult(data.demo_csp_result);
    setDocuments(data.documents || []);
    setDocumentRequirements((data.documents || []).filter((document) => document.purpose));
    setDocumentLinks((current) => {
      const keys = new Set([
        ...(data.documents || []).map((document) => documentKey(document)),
      ].filter(Boolean));
      return Object.fromEntries(
        Object.entries(current).filter(([key]) => keys.has(key)),
      );
    });
    setPdfUrl(data.pdf_url || null);
    if (data.customer_name) setCustomerName(data.customer_name);
    if (data.jurisdiction) setJurisdiction(data.jurisdiction);
    setPipelineProgress(data.pipeline_progress || null);
    setPipelineStatus(data.pipeline_status || data.status || null);
    if (typeof data.demo_mode === "boolean") setDemoMode(data.demo_mode);
    if (data.error) setError(data.error);
  }

  function resetCddRunDisplay() {
    cddRunEpochRef.current += 1;
    setCdd(null);
    setCddState(null);
    setCaseStatus({ cdd_generation: "in_progress" });
    setCaseAssessmentSummary(null);
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
    if (!demoMode && (!customerName.trim() || !jurisdiction || !accountLocation)) return;
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
          account_location: accountLocation,
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
      applyResponse(await readJsonResponse(response, "Case Assessment refresh failed"));
    } catch (err) {
      setError(err.message);
    } finally {
      setCaseReviewLoading(false);
    }
  }

  async function runCDDCompleteness() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/cdd-completeness/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      applyResponse(await readJsonResponse(response, "CDD Completeness check failed"));
    } catch (err) {
      setError(err.message);
    } finally {
      setCaseReviewLoading(false);
    }
  }

  async function runEvidenceQuality() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/evidence-quality/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      applyResponse(await readJsonResponse(response, "Evidence Quality check failed"));
    } catch (err) {
      setError(err.message);
    } finally {
      setCaseReviewLoading(false);
    }
  }

  async function runOtherRiskFactors() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/other-risk-factors/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      applyResponse(await readJsonResponse(response, "Other Risk Factors check failed"));
    } catch (err) {
      setError(err.message);
    } finally {
      setCaseReviewLoading(false);
    }
  }

  async function runShellCompanyRisk() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true); setError(null);
    try {
      const response = await fetch("/api/shell-company-risk/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) });
      applyResponse(await readJsonResponse(response, "Shell Company Risk check failed"));
    } catch (err) { setError(err.message); } finally { setCaseReviewLoading(false); }
  }

  async function runRiskRating() {
    if (!sessionId || !cdd) return;
    setCaseReviewLoading(true); setError(null);
    try {
      const response = await fetch("/api/risk-rating/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) });
      applyResponse(await readJsonResponse(response, "Risk Rating assessment failed"));
    } catch (err) { setError(err.message); } finally { setCaseReviewLoading(false); }
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
    const missing = documentRequirements.filter((requirement) => (requirement.gap || {}).status === "outstanding");
    if (!missing.length) return;
    setLoading(true);
    setError(null);
    try {
      for (const requirement of missing) {
        setGenerationStatus(`Generating ${documentLabel(requirement.document_type)} for ${(requirement.subject || {}).name}...`);
        await new Promise((resolve) => window.requestAnimationFrame(resolve));
        const response = await fetch("/api/documents/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, requirement_ids: [requirement.document_id] }),
        });
        applyResponse(await readJsonResponse(response, "Document generation failed"));
      }
      setGenerationStatus(`Generated ${missing.length} document${missing.length === 1 ? "" : "s"}.`);
    } catch (err) {
      setError(err.message);
      setGenerationStatus("Document generation failed.");
      try {
        const response = await fetch(`/api/session/${sessionId}`);
        applyResponse(await readJsonResponse(response, "Unable to refresh document status"));
      } catch (refreshError) {
        setError(`${err.message} Unable to refresh document status: ${refreshError.message}`);
      }
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

  function selectDigitalFootprintMode(mode) {
    setDigitalFootprintMode(mode);
    setDigitalFootprintError("");
    if (mode === "independent") setDigitalFootprintResult(null);
  }

  function loadDigitalFootprintFromCdd() {
    setDigitalFootprintMode("cdd");
    setDigitalFootprintResult(digitalFootprintRecords(cddState));
    setDigitalFootprintError("");
    setActiveWorkspace("digital-footprint");
  }

  async function attachDigitalFootprint() {
    if (!sessionId || !cdd || !digitalFootprintResult) return;
    setDigitalFootprintAttaching(true);
    setDigitalFootprintError("");
    try {
      const response = await fetch("/api/digital-footprint/attach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, result: digitalFootprintResult }),
      });
      applyResponse(await readJsonResponse(response, "Digital Footprint attachment failed"));
    } catch (err) {
      setDigitalFootprintError(err.message);
    } finally {
      setDigitalFootprintAttaching(false);
    }
  }

  function loadAdverseNewsFromCdd() {
    setAdverseNewsMode("cdd");
    setAdverseNewsResult(adverseNewsRecords(cddState));
    setAdverseNewsError("");
    setActiveWorkspace("adverse-news");
  }

  async function assessIndependentAdverseNews() {
    const entity_names = adverseNewsNames.split(/[\n,]/).map((name) => name.trim()).filter(Boolean);
    if (!entity_names.length) return;
    setAdverseNewsRunning(true);
    setAdverseNewsError("");
    setAdverseNewsResult(null);
    try {
      const response = await fetch("/api/adverse-news/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_names }),
      });
      setAdverseNewsResult(await readJsonResponse(response, "Adverse-news screening failed"));
    } catch (err) {
      setAdverseNewsError(err.message);
    } finally {
      setAdverseNewsRunning(false);
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
              CDD Maker
            </button>
            <button
              className={`workspace-tab ${activeWorkspace === "case-review" ? "active" : ""}`}
              onClick={() => setActiveWorkspace("case-review")}
            >
              CDD Checker
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
                        if (tool.id === "adverse-news") setAdverseNewsMode("independent");
                        if (tool.id === "digital-footprint") selectDigitalFootprintMode("independent");
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
          <Section title="Run CDD Maker">
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
                <option value="" disabled>Jurisdiction</option>
                {jurisdictions.map((code) => (
                  <option value={code} key={code}>{code}</option>
                ))}
              </select>
              <select
                aria-label="Account opening location"
                value={accountLocation}
                onChange={(event) => setAccountLocation(event.target.value)}
              >
                <option value="" disabled>AO Location</option>
                {ACCOUNT_OPENING_LOCATIONS.map((code) => (
                  <option value={code} key={code}>{code}</option>
                ))}
              </select>
              <button
                disabled={pipelineLoading || (!demoMode && (!customerName.trim() || !jurisdiction || !accountLocation))}
                onClick={() => runPipeline()}
              >
                Run CDD Maker
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
          </section>

          <Section title="Customer Business Profile">
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
              <Field className="field-full-width" label="Principal Business Activity" value={principalBusinessActivity} source={{ source: "Digital Footprint", field: "digital_business_profile.business_activity" }} />
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

          <AdverseNewsScreening cddState={cddState} onOpenTool={loadAdverseNewsFromCdd} />

          <DigitalFootprintScreening cddState={cddState} onOpenTool={loadDigitalFootprintFromCdd} />

          {showJson && cddState && (
            <Section title="CDDState JSON">
              <div className="json-view-header">
                <button className="secondary" onClick={copyCddStateJson} aria-label="Copy CDDState JSON to clipboard">
                  Copy JSON
                </button>
                <span className="json-copy-status" role="status" aria-live="polite">{jsonCopyStatus}</span>
              </div>
              <pre className="json-view">{formattedCddState}</pre>
            </Section>
          )}
              </>
            ) : activeWorkspace === "generation" ? (
              <DocumentManagement
                requirements={documentRequirements}
                links={documentLinks}
                loading={loading}
                error={error}
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
                cddState={cddState}
                summary={caseAssessmentSummary}
                decision={caseReviewDecision}
                decisionDraft={reviewDecisionDraft}
                note={reviewNote}
                loading={caseReviewLoading}
                hasCdd={Boolean(cdd)}
                onRefresh={refreshCaseReview}
                onRunCompleteness={runCDDCompleteness}
                onRunEvidenceQuality={runEvidenceQuality}
                onRunOtherRiskFactors={runOtherRiskFactors}
                onRunShellCompanyRisk={runShellCompanyRisk}
                onRunRiskRating={runRiskRating}
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
                mode={digitalFootprintMode}
                form={digitalFootprintForm}
                result={digitalFootprintResult}
                error={digitalFootprintError}
                assessing={digitalFootprintAssessing}
                skill={digitalFootprintSkill}
                skillLoading={digitalFootprintSkillLoading}
                onChange={updateDigitalFootprintForm}
                onSkillToggle={(open) => { if (open) loadDigitalFootprintSkill(); }}
                onAssess={assessDigitalFootprint}
                canLoadFromCdd={Boolean(cddState)}
                onLoadFromCdd={loadDigitalFootprintFromCdd}
                onModeChange={selectDigitalFootprintMode}
                canAttach={Boolean(sessionId && cdd)}
                attaching={digitalFootprintAttaching}
                onAttach={attachDigitalFootprint}
                demoMode={demoMode}
              />
            ) : activeWorkspace === "adverse-news" ? (
              <AdverseNewsTool
                mode={adverseNewsMode}
                result={adverseNewsResult}
                names={adverseNewsNames}
                error={adverseNewsError}
                running={adverseNewsRunning}
                canLoadFromCdd={Boolean(cddState)}
                onLoadFromCdd={loadAdverseNewsFromCdd}
                onModeChange={setAdverseNewsMode}
                onNamesChange={setAdverseNewsNames}
                onAssess={assessIndependentAdverseNews}
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
  cddState,
  summary,
  decision,
  decisionDraft,
  note,
  loading,
  hasCdd,
  onRefresh,
  onRunCompleteness,
  onRunEvidenceQuality,
  onRunOtherRiskFactors,
  onRunShellCompanyRisk,
  onRunRiskRating,
  onDecisionChange,
  onNoteChange,
  onSaveDecision,
  demoMode,
}) {
  if (!hasCdd) {
    return (
      <Section title="Case Assessment">
        <p className="empty">Run a CDD case to generate an evidence-grounded reviewer brief.</p>
      </Section>
    );
  }

  const evidenceById = Object.fromEntries((summary?.evidence_index || []).map((item) => [item.id, item]));
  return (
    <>
      <RiskFlags findings={cddState?.findings || []} evidence={cddState?.evidence || []} assessments={assessmentsByType(cddState, "risk_rating")} loading={loading} demoMode={demoMode} onRun={onRunRiskRating} />
      <CDDCompleteness assessments={assessmentsByType(cddState, "cdd_completeness")} findings={(cddState?.findings || []).filter((finding) => finding.category === "cdd_completeness")} loading={loading} demoMode={demoMode} onRun={onRunCompleteness} />
      <EvidenceQuality assessments={assessmentsByType(cddState, "evidence_quality")} findings={(cddState?.findings || []).filter((finding) => finding.category === "evidence_quality")} evidence={cddState?.evidence || []} loading={loading} demoMode={demoMode} onRun={onRunEvidenceQuality} />
      <ShellCompanyRisk assessments={assessmentsByType(cddState, "shell_company_risk")} findings={(cddState?.findings || []).filter((finding) => finding.category === "shell_company_risk")} riskFlags={(cddState?.risk_flags || []).filter((flag) => flag.category === "csp_address")} evidence={cddState?.evidence || []} loading={loading} demoMode={demoMode} onRun={onRunShellCompanyRisk} />
      <OtherRiskFactors assessments={assessmentsByType(cddState, "other_risk_factors")} findings={(cddState?.findings || []).filter((finding) => finding.category === "other_risk_factors")} evidence={cddState?.evidence || []} loading={loading} demoMode={demoMode} onRun={onRunOtherRiskFactors} />

      <Section title="Case Assessment">
        <div className="case-assessment-header">
          <div>
            <p className="review-disclaimer">Decision support only. A human reviewer remains responsible for the case decision.</p>
          </div>
          <button disabled={loading || demoMode} onClick={onRefresh}>
            {demoMode ? "Fixture summary" : (loading ? "Refreshing…" : summary ? "Refresh summary" : "Generate summary")}
          </button>
        </div>
        {!summary ? (
          <p className="empty">No case assessment has been generated yet.</p>
        ) : (
          <>
            {summary.status === "unavailable" && <p className="risk">The generated assessment is unavailable. The recorded CDD evidence remains available for review.</p>}
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

function RiskFlags({ findings, evidence, assessments, loading, demoMode, onRun }) {
  const rating = assessments[assessments.length - 1];
  const evidenceById = Object.fromEntries(evidence.map((item) => [item.evidence_id, item]));
  return <Section title="Risk Flags"><div className="case-assessment-header"><div><h3>Risk Rating</h3>{rating ? <div className="adverse-news-summary"><strong>{statusLabel(rating.rating)}</strong><span>{rating.summary || "No rationale was recorded."}</span><span>{`Monitoring: ${rating.monitoring_posture || "Not recorded."}`}</span>{rating.matched_criteria?.length ? <span>{`Matched criteria: ${rating.matched_criteria.join("; ")}`}</span> : null}{rating.limitations?.length ? <span>{`Limitations: ${rating.limitations.join(" ")}`}</span> : null}</div> : <p className="empty">No Risk Rating assessment is available.</p>}</div><button disabled={loading || demoMode} onClick={onRun}>{loading ? "Assessing…" : (rating ? "Re-run Risk Rating" : "Run Risk Rating")}</button></div><h3>Findings</h3>{findings.length ? <div className="review-list">{findings.map((finding) => <div className="review-item" key={finding.finding_id}><strong>{finding.title || finding.category || "Finding"}</strong><p>{finding.summary || "No summary was recorded."}</p><small>{`Confidence: ${statusLabel(finding.confidence?.level)} · Severity: ${statusLabel(finding.severity?.level)}`}</small>{finding.recommended_action_rfi?.internal_actions?.length ? <p className="risk">{`Recommended action: ${finding.recommended_action_rfi.internal_actions.join(" ")}`}</p> : null}{finding.recommended_action_rfi?.rfi?.length ? <BulletList items={finding.recommended_action_rfi.rfi.map((item) => `${item.request} — ${item.reason} (${item.priority})`)} /> : null}{(finding.relevant_evidence_ids || []).length ? <EvidenceReview evidence={finding.relevant_evidence_ids.map((id) => evidenceById[id] || { evidence_id: id, description: "Referenced evidence is not currently retained." })} /> : null}<small>{`Source: ${finding.source?.producer_name || "Not recorded"}${finding.source?.created_at ? ` · ${formatDateTime(finding.source.created_at)}` : ""}`}</small></div>)}</div> : <p className="empty">No canonical findings are currently recorded.</p>}</Section>;
}

function CDDCompleteness({ assessments, findings, loading, demoMode, onRun }) {
  if (!assessments.length) {
    return <Section title="CDD Completeness"><p className="empty">No completeness assessment is available.</p><button disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Run CDD Completeness Check"}</button></Section>;
  }
  return (
    <Section title="CDD Completeness">
      <button className="secondary" disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Re-run CDD Completeness Check"}</button>
      <div className="review-list">
        {assessments.slice().sort((left, right) => (left.display_order || 0) - (right.display_order || 0)).map((assessment) => {
          const finding = findings.find((item) => item.assessment_id === assessment.assessment_id);
          return <div className="review-item" key={assessment.assessment_id}>
            <strong>{assessment.title}</strong>
            <p>{assessment.summary}</p>
            {assessment.detail?.missing_items?.length ? <small>{`Missing: ${assessment.detail.missing_items.join(", ")}`}</small> : null}
            {finding ? <p className="risk">{`${statusLabel(finding.severity?.level)}: ${finding.recommended_action_rfi?.internal_actions?.join(" ") || "Action required."}`}</p> : <small>Complete — no finding raised.</small>}
          </div>;
        })}
      </div>
    </Section>
  );
}

function EvidenceQuality({ assessments, findings, evidence, loading, demoMode, onRun }) {
  if (!assessments.length) {
    return <Section title="Evidence Quality"><p className="empty">No Evidence Quality assessment is available.</p><button disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Run Evidence Quality Check"}</button></Section>;
  }
  return (
    <Section title="Evidence Quality">
      <button className="secondary" disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Re-run Evidence Quality Check"}</button>
      <div className="review-list">
        {EVIDENCE_SECTION_ORDER.map((section) => {
          const sectionAssessments = assessments.filter((assessment) => assessment.cdd_section === section || assessment.definition?.cdd_section === section);
          if (!sectionAssessments.length) return null;
          return <div className="evidence-quality-section" key={section}>
            <h3>{EVIDENCE_SECTION_LABELS[section]}</h3>
            {sectionAssessments.slice().sort((left, right) => (left.display_order || 0) - (right.display_order || 0)).map((assessment) => {
          const finding = findings.find((item) => item.assessment_id === assessment.assessment_id);
          const sources = assessment.selected_evidence || [];
          const evidenceById = Object.fromEntries(evidence.map((item) => [item.evidence_id, item]));
          return <div className="review-item" key={assessment.assessment_id}>
            <strong>{assessment.title}</strong>
            <p>{assessment.summary}</p>
            <div className="evidence-quality-dimensions">
              {(assessment.definition?.dimensions || []).map((dimension) => {
                const result = assessment.dimensions?.[dimension.key] || {};
                return <div className="evidence-quality-dimension" key={dimension.key}>
                  <div><span className="evidence-quality-tag">{dimension.label}</span><span className="evidence-quality-outcome">{evidenceQualityOutcomeLabel(result.outcome)}</span></div>
                  <small>{result.rationale || "No explanation was recorded."}</small>
                </div>;
              })}
            </div>
            {sources.length ? <EvidenceReview evidence={sources.map((item) => evidenceById[item.evidence_id] || item)} /> : null}
            {finding ? <p className="risk">{`${statusLabel(finding.severity?.level)}: ${finding.recommended_action_rfi?.internal_actions?.join(" ") || "Action required."}`}</p> : <small>No finding raised.</small>}
          </div>;
            })}
          </div>;
        })}
      </div>
    </Section>
  );
}

function OtherRiskFactors({ assessments, findings, evidence, loading, demoMode, onRun }) {
  if (!assessments.length) {
    return <Section title="Other Risk Factors"><p className="empty">No Other Risk Factors assessment is available.</p><button disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Run Other Risk Factors Check"}</button></Section>;
  }
  const evidenceById = Object.fromEntries(evidence.map((item) => [item.evidence_id, item]));
  return <Section title="Other Risk Factors">
    <button className="secondary" disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Re-run Other Risk Factors Check"}</button>
    <div className="review-list">{EVIDENCE_SECTION_ORDER.map((section) => {
      const group = assessments.filter((assessment) => assessment.cdd_section === section || assessment.definition?.cdd_section === section);
      if (!group.length) return null;
      return <div className="evidence-quality-section" key={section}><h3>{EVIDENCE_SECTION_LABELS[section]}</h3>{group.slice().sort((left, right) => (left.display_order || 0) - (right.display_order || 0)).map((assessment) => {
        const finding = findings.find((item) => item.assessment_id === assessment.assessment_id);
        const reviewed = (assessment.selected_evidence || []).map((item) => evidenceById[item.evidence_id] || item);
        const upstreamCount = (assessment.upstream_assessment_ids || []).length + (assessment.upstream_finding_ids || []).length;
        const indicators = assessment.detail?.matched_indicators || [];
        return <div className="review-item" key={assessment.assessment_id}><strong>{assessment.title}</strong><p>{assessment.summary}</p>{indicators.map((indicator, index) => <small key={`${indicator.evidence_id}-${indicator.field_path}-${index}`}>{`Matched evidence: ${indicator.evidence_id} · ${indicator.field_path} · ${indicator.value}`}</small>)}{upstreamCount ? <small>{`Related retained screening records: ${upstreamCount}.`}</small> : null}{reviewed.length ? <EvidenceReview evidence={reviewed} /> : null}{finding ? <p className="risk">{`${statusLabel(finding.severity?.level)}: ${finding.recommended_action_rfi?.internal_actions?.join(" ") || "Action required."}`}</p> : <small>No finding raised.</small>}</div>;
      })}</div>;
    })}</div>
  </Section>;
}

function ShellCompanyRisk({ assessments, findings, riskFlags, evidence, loading, demoMode, onRun }) {
  const evidenceById = Object.fromEntries(evidence.map((item) => [item.evidence_id, item]));
  const cspEvidence = evidence.filter((item) => item.tool === "csp_address_assessment");
  if (!assessments.length && !riskFlags.length) return <Section title="Shell Company Risk"><p className="empty">No Shell Company Risk assessment is available.</p><button disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Run Shell Company Risk Check"}</button></Section>;
  return <Section title="Shell Company Risk"><button className="secondary" disabled={loading || demoMode} onClick={onRun}>{loading ? "Checking…" : "Re-run Shell Company Risk Check"}</button><div className="review-list">{EVIDENCE_SECTION_ORDER.map((section) => {
    const group = assessments.filter((assessment) => assessment.cdd_section === section || assessment.definition?.cdd_section === section); if (!group.length) return null;
    return <div className="evidence-quality-section" key={section}><h3>{EVIDENCE_SECTION_LABELS[section]}</h3>{group.slice().sort((left, right) => (left.display_order || 0) - (right.display_order || 0)).map((assessment) => { const finding = findings.find((item) => item.assessment_id === assessment.assessment_id); const reviewed = (assessment.selected_evidence || []).map((item) => evidenceById[item.evidence_id] || item); return <div className="review-item" key={assessment.assessment_id}><strong>{assessment.title}</strong><p>{assessment.summary}</p>{reviewed.length ? <EvidenceReview evidence={reviewed} /> : null}{finding ? <p className="risk">{`${statusLabel(finding.severity?.level)}: ${finding.recommended_action_rfi?.internal_actions?.join(" ") || "Action required."}`}</p> : <small>No finding raised.</small>}</div>; })}</div>;
  })}<div className="evidence-quality-section"><h3>Screening</h3><strong>CSP Address</strong>{riskFlags.length ? riskFlags.map((flag) => <div className="review-item" key={flag.finding_id}><p>{flag.description || "CSP assessment recorded."}</p><small>{`Outcome: ${flag.evaluation || "inconclusive"} · severity: ${flag.severity || "not recorded"}. This is the existing CSP record; no duplicate Shell Company Risk finding was created.`}</small></div>) : <p className="empty">No upstream CSP assessment is available.</p>}{cspEvidence.length ? <EvidenceReview evidence={cspEvidence} /> : null}</div></div></Section>;
}

const EVIDENCE_SECTION_ORDER = ["customer_business_profile", "ownership_and_control", "identity_verification", "screening"];
const EVIDENCE_SECTION_LABELS = {
  customer_business_profile: "Customer Business Profile",
  ownership_and_control: "Ownership & Control",
  identity_verification: "ID&V",
  screening: "Screening",
};

function evidenceSection(item) {
  if (item.cdd_section) return item.cdd_section;
  if (["get_customer_static_by_case_id", "create_company_case", "generate_registry_document", "extract_registry_document"].includes(item.tool)) return "customer_business_profile";
  if (["get_company_org_chart_by_case_id", "get_company_members_by_case_id"].includes(item.tool)) return "ownership_and_control";
  if (["establish_idv_requirements", "generate_idv_documents", "extract_idv_documents"].includes(item.tool)) return "identity_verification";
  return "screening";
}

function EvidenceReview({ evidence }) {
  const groups = EVIDENCE_SECTION_ORDER.map((section) => [section, evidence.filter((item) => evidenceSection(item) === section)]).filter(([, items]) => items.length);
  return <details className="evidence-review"><summary>{`Evidence reviewed (${evidence.length})`}</summary>{groups.map(([section, items]) => <div className="evidence-review-group" key={section}><h4>{EVIDENCE_SECTION_LABELS[section]}</h4>{items.map((item) => <EvidenceReviewItem item={item} key={item.evidence_id} />)}</div>)}</details>;
}

function EvidenceReviewItem({ item }) {
  const url = item.source_url || item.url || item.data?.url || item.storage?.url;
  const retained = item.data || item;
  return <div className="evidence-review-item">
    <strong>{item.source || "Source not recorded"}</strong>
    <span>{item.description || item.evidence_area || "Retained evidence"}</span>
    <small>{[item.evidence_area, item.collected_at ? `Collected ${formatDateTime(item.collected_at)}` : null].filter(Boolean).join(" · ")}</small>
    <div>{url ? <a href={url} target="_blank" rel="noreferrer">View source</a> : <small>No external source link retained.</small>}</div>
    <details><summary>Retained evidence details</summary><pre className="evidence-record">{JSON.stringify(retained, null, 2)}</pre><small>{`Audit reference: ${item.evidence_id}`}</small></details>
  </div>;
}

function evidenceQualityOutcomeLabel(outcome) {
  return {
    not_triggered: "Confirmed from available evidence",
    gap: "More evidence needed",
    unavailable: "Unable to confirm from available evidence",
    invalid: "Unable to confirm from available evidence",
    inconclusive: "Unable to confirm from available evidence",
    not_applicable: "Not assessed",
  }[outcome] || "Unable to confirm from available evidence";
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

function DigitalFootprint({ mode, form, result, error, assessing, skill, skillLoading, onChange, onSkillToggle, onAssess, canLoadFromCdd, onLoadFromCdd, onModeChange, canAttach, attaching, onAttach, demoMode }) {
  return (
    <>
      <Section title="Digital Footprint">
        <div className="actions">
          <button className={mode === "cdd" ? "" : "secondary"} disabled={!canLoadFromCdd} onClick={() => { onModeChange("cdd"); onLoadFromCdd(); }}>Load from CDD</button>
          <button className={mode === "independent" ? "" : "secondary"} onClick={() => onModeChange("independent")}>Run independent Digital Footprint Check</button>
        </div>
        {mode === "cdd" ? <p className="empty">Loaded from the active CDD state. The chatbot remains available for this case.</p> : <>
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
          <p className="empty">Independent results are not attached to the active CDD case. The chatbot is disabled.</p>
        </>}
        {error && <p className="risk">{error}</p>}
      </Section>

      {result && (
        <>
          <DigitalFootprintAssessment result={result} />
          <Section title="Findings">
            {(result.findings || []).length ? (result.findings || []).map((finding, index) => <AdverseNewsFinding key={finding.finding_id || index} finding={finding} evidenceById={Object.fromEntries((result.evidence || []).map((item) => [item.evidence_id, item]))} popoverId={`digital-footprint-${index}`} />) : <p className="empty">No material digital-footprint findings were identified.</p>}
          </Section>
          <Section title="Sources">
            <div className="csp-sources">{(result.evidence || []).map((source) => <div key={source.evidence_id}><a href={source.source_url || source.data?.url} target="_blank" rel="noreferrer">{source.description || source.source_url || "Source"}</a><small>{` — ${source.data?.query || ""}`}</small></div>)}</div>
          </Section>
          <Section title="Digital Footprint JSON"><pre className="json-view">{JSON.stringify(result, null, 2)}</pre></Section>
          <Section title="CDD evidence">
            {mode === "cdd" ? <p className="empty">This assessment is already loaded from the active CDD case.</p> : canAttach ? <button disabled={attaching || demoMode} onClick={onAttach}>{attaching ? "Attaching…" : "Attach validated result to active CDD case"}</button> : <p className="empty">This result is standalone. Run a CDD case before attaching it as case evidence.</p>}
          </Section>
        </>
      )}
    </>
  );
}

const LEGACY_DIGITAL_PRESENCE_DIMENSIONS = [
  { key: "professional_website", label: "Professional website" }, { key: "active_linkedin", label: "Active LinkedIn" },
  { key: "independent_references", label: "Independent references" }, { key: "recent_business_activity", label: "Recent business activity" },
  { key: "basic_website", label: "Website with basic information" }, { key: "credible_online_presence", label: "Credible online presence" },
  { key: "evidence_of_operations", label: "Evidence of operations" }, { key: "website_currency", label: "Website currency/completeness" },
];

function digitalPresenceDimensions(definition) {
  const section = (definition?.sections || []).find((item) => item.id === "presence_and_visibility" && item.type === "scorecard");
  return Array.isArray(section?.dimensions) && section.dimensions.length ? section.dimensions : LEGACY_DIGITAL_PRESENCE_DIMENSIONS;
}

function DigitalPresenceBreakdown({ indicators, definition }) {
  const dimensions = digitalPresenceDimensions(definition);
  if (!indicators) return null;
  return <div className="digital-presence-breakdown">{dimensions.map(({ key, label }) => { const item = indicators[key] || {}; return <div className="digital-presence-row" key={key}><strong>{label}</strong><span className={`digital-presence-status ${item.status || "unknown"}`}>{statusLabel(item.status)}</span><span>{item.rationale || "Not assessed."}</span>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">View Source</a> : null}</div>; })}</div>;
}

function assessmentsByType(result, assessmentType) {
  return (result?.assessments || []).filter((assessment) => assessment.assessment_type === assessmentType);
}

function latestAssessment(result, assessmentType) {
  return assessmentsByType(result, assessmentType).reduce((latest, assessment) => {
    if (!latest || String(assessment.created_at || "") >= String(latest.created_at || "")) return assessment;
    return latest;
  }, null);
}

function DigitalFootprintAssessment({ result }) {
  const assessment = latestAssessment(result, "digital_footprint");
  if (!assessment) return <Section title="Assessment"><p className="risk">Digital Footprint assessment unavailable.</p></Section>;
  const profile = assessment.digital_business_profile || {};
  return <><Section title="Presence and Visibility"><div className="adverse-news-summary"><strong>{assessment.company_inputs?.company_name || "Company"}</strong><span>{`Overall score: ${statusLabel(assessment.presence_and_visibility?.indicator)}`}</span><span>{assessment.presence_and_visibility?.rationale || "No presence assessment was recorded."}</span><span>{`Confidence: ${statusLabel(assessment.confidence?.level)}`}</span><span>{`${(assessment.queries || []).length} queries; ${(assessment.source_evidence_ids || []).length} retained sources.`}</span>{assessment.limitations?.length ? <span>{`Limitations: ${assessment.limitations.join(" ")}`}</span> : null}</div><DigitalPresenceBreakdown indicators={assessment.presence_and_visibility?.indicators} definition={assessment.definition} /></Section><Section title="Business Profile"><div className="adverse-news-summary"><span><LinkedAdverseNewsText text={profile.summary || "No business profile was recorded."} evidence={result.evidence || []} /></span><span>{`Business activity: ${profile.business_activity || "Not identified."}`}</span><span>{`Geographic presence: ${(profile.geographic_presence || []).join(", ") || "Not identified."}`}</span><span>{`Key people: ${(profile.key_people || []).join(", ") || "Not identified."}`}</span><span>{`Commercial relationships: ${(profile.commercial_relationships || []).join(", ") || "Not identified."}`}</span></div></Section></>;
}

function digitalFootprintRecords(cddState) {
  return {
    evidence: (cddState?.evidence || []).filter((item) => item.tool === "digital_footprint_assessment"),
    assessments: assessmentsByType(cddState, "digital_footprint"),
    findings: (cddState?.findings || []).filter((finding) => finding.category === "digital_footprint"),
  };
}

function DigitalFootprintScreening({ cddState, onOpenTool }) {
  const result = digitalFootprintRecords(cddState);
  const assessment = latestAssessment(result, "digital_footprint");

  if (!assessment) {
    return <Section title="Digital Footprint"><p className="empty">Not run.</p></Section>;
  }

  if (assessment.outcome === "unavailable") {
    return <Section title="Digital Footprint"><p className="risk">{`Assessment unavailable. ${assessment.limitations?.[0] || "No reason was recorded."}`}</p></Section>;
  }

  return (
    <Section title="Digital Footprint">
      <div className="adverse-news-summary">
        <strong>{assessment.company_inputs?.company_name || "Company"}</strong>
        <span>{`Overall presence and visibility: ${statusLabel(assessment.presence_and_visibility?.indicator)}`}</span>
        <span>{assessment.presence_and_visibility?.rationale || "No presence assessment was recorded."}</span>
        <span>{`Confidence: ${statusLabel(assessment.confidence?.level)}`}</span>
        {assessment.limitations?.length ? <span>{`Limitations: ${assessment.limitations.join(" ")}`}</span> : null}
        <button className="secondary adverse-news-tool-link" onClick={onOpenTool}>Review in Digital Footprint tool</button>
      </div>
    </Section>
  );
}

function ManifestFootprintSection({ section, result }) {
  const generated = (result.custom_sections || []).find((item) => item.id === section.id);
  return <DynamicFootprintSection section={generated} sources={result.sources || []} />;
}

function DynamicFootprintSection({ section, sources }) {
  if (!section) return <p className="empty">No supported evidence was returned.</p>;
  const sourceById = Object.fromEntries(sources.map((source) => [source.id, source]));
  const links = (refs) => refs?.length ? <small>Evidence: {refs.map((ref, index) => <React.Fragment key={ref}>{index > 0 && ", "}{sourceById[ref]?.url ? <a href={sourceById[ref].url} target="_blank" rel="noreferrer">{ref}</a> : ref}</React.Fragment>)}</small> : null;
  if (section.type === "narrative") return <div className="review-item"><p>{section.content.text}</p>{links(section.source_refs)}</div>;
  if (section.type === "findings") return <div className="review-list">{section.content.items.map((item, index) => <div className="review-item" key={index}><p>{item.finding}</p>{links(item.source_refs)}</div>)}</div>;
  if (section.type === "table") return <div><h3>{section.title}</h3><table><thead><tr>{section.content.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{section.content.rows.map((row, index) => <tr key={index}>{row.cells.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table>{links(section.source_refs)}</div>;
  return null;
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
  error,
  generationStatus,
  demoMode,
}) {
  const missing = (requirements || []).filter((requirement) => (requirement.gap || {}).status === "outstanding");
  const hasProcessableDocuments = (requirements || []).some((requirement) =>
    ["located", "received", "processing"].includes(requirement.status),
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
              const foundInCache = Boolean((requirement.acquisition || {}).artifact?.reused_from_s3)
                || (requirement.acquisition || {}).source === "S3 document cache";
              const provided = !foundInCache && ["customer_upload", "generated"].includes((requirement.acquisition || {}).source);
              const cacheLink = foundInCache ? links[documentKey(requirement)] : null;
              const demoLink = requirement.demo_url;
              return (
                <tr key={requirement.document_id}>
                  <td>{documentLabel(requirement.document_type)} — {(requirement.subject || {}).name}</td>
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
      {error && <p className="risk">{error}</p>}
    </Section>
  );
}

function Field({ label, value, source, className = "" }) {
  const sourceText = sourceTooltip(source);
  return (
    <div className={`field ${className}`.trim()}>
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
  const cache = progress.cache_source
    ? ` (reading from ${progress.cache_source === "s3" ? "S3" : "local"} cache)`
    : progress.using_cache ? " (using cache)" : "";
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

function AdverseNewsScreening({ cddState, onOpenTool }) {
  const evidence = Array.isArray(cddState?.evidence) ? cddState.evidence : [];
  const findings = (Array.isArray(cddState?.findings) ? cddState.findings : [])
    .filter((finding) => finding.category === "adverse_news");
  const assessment = adverseNewsAssessment(cddState);

  if (!assessment) {
    return (
      <Section title="Adverse News Screening">
        <p className="empty">Not run.</p>
      </Section>
    );
  }

  if (assessment.outcome === "unavailable") {
    return (
      <Section title="Adverse News Screening">
        <p className="risk">{`Screening unavailable. ${assessment.limitations?.[0] || "No reason was recorded."}`}</p>
      </Section>
    );
  }

  const entities = Array.isArray(assessment.screened_entities) ? assessment.screened_entities : [];
  const sourceCount = Array.isArray(assessment.source_evidence_ids) ? assessment.source_evidence_ids.length : 0;
  const queryCount = Array.isArray(assessment.queries) ? assessment.queries.length : 0;
  const evidenceById = Object.fromEntries(evidence.map((item) => [item.evidence_id, item]));

  return (
    <Section title="Adverse News Screening">
      <div className="adverse-news-summary">
        <strong>{assessment.outcome === "completed_with_findings" ? "Screening completed with findings" : "Screening completed"}</strong>
        <span><LinkedAdverseNewsText text={assessment.summary || "No material attributable adverse-news findings were identified in the retained results."} evidence={evidence} /></span>
        <span>{`Screened ${entities.length} ${entities.length === 1 ? "entity" : "entities"}:`}</span>
        {entities.length ? (
          <ul className="adverse-news-entity-list">
            {entities.map((entity, index) => <li key={entity.key || `${entity.name || "entity"}-${index}`}>{entity.name || "Unnamed entity"}</li>)}
          </ul>
        ) : <span>None recorded.</span>}
        <span>{`${entities.length} ${entities.length === 1 ? "entity was" : "entities were"} searched using ${queryCount} ${queryCount === 1 ? "query" : "queries"} — one query for each screened entity.`}</span>
        <span>{`${sourceCount} unique ${sourceCount === 1 ? "source result was" : "source results were"} retained.`}</span>
        {assessment.limitations?.length ? <span>{`Limitations: ${assessment.limitations.join(" ")}`}</span> : null}
        <span>{`Screened ${formatDateTime(assessment.created_at)}.`}</span>
        <button className="secondary adverse-news-tool-link" onClick={onOpenTool}>Review in Adverse News tool</button>
      </div>
      {findings.length ? (
        <div className="adverse-news-findings">
          {findings.map((finding, index) => (
            <AdverseNewsFinding
              evidenceById={evidenceById}
              finding={finding}
              key={finding.finding_id || `${finding.subject?.name || "finding"}-${index}`}
              popoverId={`adverse-news-sources-${index}`}
            />
          ))}
        </div>
      ) : <p className="empty">No material attributable adverse-news findings were identified in the retained results.</p>}
    </Section>
  );
}

function adverseNewsRecords(cddState) {
  return {
    findings: (cddState?.findings || []).filter((finding) => finding.category === "adverse_news"),
    evidence: (cddState?.evidence || []).filter((item) => item.tool === "adverse_news_screening"),
    assessments: assessmentsByType(cddState, "adverse_news"),
  };
}

function adverseNewsAssessment(result) {
  const assessment = latestAssessment(result, "adverse_news");
  return assessment;
}

function LinkedAdverseNewsText({ text, evidence }) {
  const sourceByReference = Object.fromEntries((evidence || [])
    .filter((item) => item.data?.id)
    .map((item) => [item.data.id, item]));
  return String(text || "").split(/(source:\d+)/gi).map((part, index) => {
    const source = sourceByReference[part.toLowerCase()];
    const url = source?.source_url || source?.data?.url;
    return url ? <a key={`${part}-${index}`} href={url} target="_blank" rel="noreferrer">{part}</a> : <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>;
  });
}

function AdverseNewsTool({ mode, result, names, error, running, canLoadFromCdd, onLoadFromCdd, onModeChange, onNamesChange, onAssess }) {
  const [entityIndex, setEntityIndex] = useState(0);
  const assessment = adverseNewsAssessment(result);
  const entities = assessment?.screened_entities || [];
  const entity = entities[entityIndex] || null;
  const entityName = entity?.name || "";
  const findings = (result?.findings || []).filter((finding) => String(finding.subject?.name || "").toUpperCase() === entityName.toUpperCase());
  const evidence = (result?.evidence || []).filter((item) => item.data?.entity_key === entity?.key);
  const entityOutcome = (assessment?.entity_outcomes || []).find((outcome) => outcome.entity_key === entity?.key);

  useEffect(() => setEntityIndex(0), [result, mode]);

  return (
    <>
      <Section title="Adverse News">
        <div className="actions">
          <button className={mode === "cdd" ? "" : "secondary"} disabled={!canLoadFromCdd} onClick={() => { onModeChange("cdd"); onLoadFromCdd(); }}>Load from CDD</button>
          <button className={mode === "independent" ? "" : "secondary"} onClick={() => onModeChange("independent")}>Run independent Adverse News Check</button>
        </div>
        {mode === "cdd" ? <p className="empty">Loaded from the active CDD state. The chatbot remains available for this case.</p> : (
          <div className="csp-form adverse-news-form">
            <textarea aria-label="Entity names" placeholder="One entity name per line" value={names} onChange={(event) => onNamesChange(event.target.value)} disabled={running} />
            <button disabled={running || !names.trim()} onClick={onAssess}>{running ? "Screening…" : "Run check"}</button>
          </div>
        )}
        {mode === "independent" && <p className="empty">Independent results are not attached to the active CDD case. The chatbot is disabled.</p>}
        {error && <p className="risk">{error}</p>}
      </Section>

      {result && (
        <>
          <Section title="Screening Summary">
            {assessment?.outcome === "unavailable" ? <p className="risk">{`Screening unavailable. ${assessment.limitations?.[0] || "No reason was recorded."}`}</p> : assessment ? <div className="adverse-news-summary"><strong>{assessment.outcome === "completed_with_findings" ? "Screening completed with findings" : "Screening completed"}</strong><span><LinkedAdverseNewsText text={assessment.summary || "No material attributable adverse-news findings were identified in the retained results."} evidence={result.evidence || []} /></span><span>{`${entities.length} ${entities.length === 1 ? "entity" : "entities"} screened; ${(assessment.source_evidence_ids || []).length} retained sources.`}</span>{assessment.limitations?.length ? <span>{`Limitations: ${assessment.limitations.join(" ")}`}</span> : null}</div> : <p className="empty">No screening assessment is available.</p>}
          </Section>
          {entity && (
            <Section title="Entity Screening">
              <div className="adverse-news-navigation">
                <button className="secondary" disabled={entityIndex === 0} onClick={() => setEntityIndex((index) => index - 1)}>← Previous</button>
                <strong>{`${entityIndex + 1} of ${entities.length} — ${entityName}`}</strong>
                <button className="secondary" disabled={entityIndex === entities.length - 1} onClick={() => setEntityIndex((index) => index + 1)}>Next →</button>
              </div>
              <h3>Assessment</h3>
              <p><LinkedAdverseNewsText text={entityOutcome?.summary || "No entity-level assessment was recorded."} evidence={result.evidence || []} /></p>
              {entityOutcome?.limitations?.length ? <p className="empty">{`Limitations: ${entityOutcome.limitations.join(" ")}`}</p> : null}
              <h3>Findings</h3>
              {findings.length ? findings.map((finding, index) => <AdverseNewsFinding key={finding.finding_id || index} finding={finding} evidenceById={Object.fromEntries((result.evidence || []).map((item) => [item.evidence_id, item]))} popoverId={`tool-adverse-news-${entityIndex}-${index}`} />) : <p className="empty">No material attributable adverse-news findings were identified in the retained results for this entity.</p>}
              <h3>Evidence</h3>
              {evidence.length ? <div className="csp-sources">{evidence.map((item) => <a key={item.evidence_id} href={item.source_url || item.data?.url} target="_blank" rel="noreferrer">{item.description || item.source_url || "Source"}</a>)}</div> : <p className="empty">No retained source evidence for this entity.</p>}
            </Section>
          )}
        </>
      )}
    </>
  );
}

function AdverseNewsFinding({ evidenceById, finding, popoverId }) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const sourceButtonRef = useRef(null);
  const evidenceItems = (finding.relevant_evidence_ids || [])
    .map((evidenceId) => evidenceById[evidenceId])
    .filter(Boolean);
  const subject = finding.subject?.name || "Screened entity";

  function closeSources({ returnFocus = false } = {}) {
    setSourcesOpen(false);
    if (returnFocus) sourceButtonRef.current?.focus();
  }

  return (
    <article className="adverse-news-finding">
      <div className="adverse-news-finding-content">
        <strong>{`${subject}${finding.title ? ` — ${finding.title}` : ""}`}</strong>
        <span>{finding.summary || "No summary was recorded."}</span>
        <div className="adverse-news-finding-tags">
          <span className="adverse-news-finding-tag confidence-tag">{`Confidence: ${statusLabel(finding.confidence?.level)}`}</span>
          <span className={`adverse-news-finding-tag severity-tag severity-${finding.severity?.level || "unknown"}`}>{`Severity: ${statusLabel(finding.severity?.level)}`}</span>
          <small>{`Source: ${finding.source?.producer_name || "adverse_news_screening"}.`}</small>
        </div>
      </div>
      <div className="adverse-news-source-control">
        <button
          aria-controls={popoverId}
          aria-expanded={sourcesOpen}
          aria-label={`View sources for ${subject}`}
          className="adverse-news-source-button"
          onClick={() => setSourcesOpen((open) => !open)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              closeSources({ returnFocus: true });
            }
          }}
          ref={sourceButtonRef}
          type="button"
        >
          i
        </button>
        {sourcesOpen && (
          <div
            aria-label={`Sources for ${subject}`}
            className="adverse-news-source-popover"
            id={popoverId}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                closeSources({ returnFocus: true });
              }
            }}
            role="dialog"
          >
            <div className="adverse-news-source-popover-header">
              <strong>Sources</strong>
              <button type="button" className="adverse-news-source-close" onClick={() => closeSources({ returnFocus: true })} aria-label="Close sources">×</button>
            </div>
            {evidenceItems.length ? evidenceItems.map((item) => {
              const source = item.data || {};
              const url = item.source_url || source.url;
              const title = item.description || source.title || url || "Source";
              const publishedAt = item.published_at || source.published_date;
              return (
                <div className="adverse-news-source" key={item.evidence_id}>
                  {url ? <a href={url} target="_blank" rel="noreferrer">{title}</a> : <span>{title}</span>}
                  <small>{`${item.source || "Web source"}${publishedAt ? ` · ${formatDateTime(publishedAt)}` : ""}`}</small>
                </div>
              );
            }) : <span>No cited sources were retained for this finding.</span>}
          </div>
        )}
      </div>
    </article>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
