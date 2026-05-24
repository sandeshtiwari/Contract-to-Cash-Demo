import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  Banknote,
  Bot,
  Boxes,
  CheckCircle2,
  Clock3,
  Database,
  FileSearch,
  GitBranch,
  History,
  FileText,
  ReceiptText,
  KeyRound,
  LockKeyhole,
  Maximize2,
  Play,
  RotateCcw,
  Scale,
  ShieldCheck,
  WalletCards,
  X
} from "lucide-react";

type CaseRow = {
  case_id: string;
  customer: string;
  case_type: string;
  risk: string;
  status: string;
  summary: string;
  lane_story: string;
  expected_decision: string;
  expected_billing_adjustment: string;
  expected_revenue_adjustment: string;
};

type LaneResult = {
  lane: "synapsor_llm" | "postgres_llm" | "postgres_rules";
  title: string;
  decision: string;
  billing_adjustment_cents: number | null;
  revenue_adjustment_cents: number | null;
  reason: string;
  risk_level: string;
  requires_approval: boolean;
  tool_calls: number;
  db_round_trips: number;
  app_glue_lines: number;
  input_tokens: number;
  output_tokens: number;
  elapsed_ms: number;
  evidence_items: number;
  proposal_created: boolean;
  branch_created: boolean;
  replay_available: boolean;
  evidence_handles: string[];
  evidence_details: EvidenceDetail[];
  reason_codes: string[];
  payload_breakdown: Record<string, number>;
  architecture_notes: string[];
  approval?: ApprovalDetail | null;
  proposal?: Record<string, unknown> | null;
  trace: { step: string; detail: string }[];
};

type ApprovalDetail = {
  state: string;
  mode: string;
  reason: string;
  artifact: string | null;
  lifecycle: string[];
};

type EvidenceDetail = {
  id: string;
  kind: string;
  title: string;
  source: string;
  handle: string;
  snippet: string;
};

type RunBody = {
  case_id: string;
  prompt: string;
  live_llm: boolean;
  results: LaneResult[];
  agent_view: AgentView;
  transparency?: {
    run_type: string;
    persistent_data_mutated: boolean;
    hidden_backend_steps: string[];
    note: string;
  };
  token_savings: {
    input_tokens_saved: number;
    input_reduction_percent: number;
    synapsor_input_tokens: number;
    postgres_llm_input_tokens: number;
  };
};

type AgentView = Record<string, { title: string; summary: string; items: string[]; raw_text: string; char_count: number; word_count: number }>;

const api = {
  async cases(): Promise<CaseRow[]> {
    const res = await fetch("/api/cases");
    return res.json();
  },
  async run(caseId: string, liveLlm: boolean): Promise<RunBody> {
    const res = await fetch(`/api/cases/${caseId}/run?live_llm=${liveLlm ? "true" : "false"}`, { method: "POST" });
    if (!res.ok) throw new Error(`run failed with HTTP ${res.status}`);
    return res.json();
  },
  async capability(): Promise<{ sql: string }> {
    const res = await fetch("/api/synapsor/capability");
    return res.json();
  },
  async agentPreview(caseId: string): Promise<{ case_id: string; agent_view: AgentView }> {
    const res = await fetch(`/api/cases/${caseId}/agent-preview`);
    if (!res.ok) throw new Error(`agent preview failed with HTTP ${res.status}`);
    return res.json();
  },
  async reset(): Promise<{ status: string; message: string }> {
    const res = await fetch("/api/reset", { method: "POST" });
    return res.json();
  }
};

function fmtTokens(n: number) {
  return n.toLocaleString();
}

function fmtCents(n: number | null) {
  if (n === null) return "-";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function riskClass(risk: string) {
  return risk.toLowerCase();
}

function friendlyCaseTitle(item: CaseRow) {
  if (item.customer.includes("Acme")) return "Overbilled upgrade + missed credit";
  if (item.customer.includes("Beta")) return "Clean renewal invoice";
  if (item.customer.includes("Northstar")) return "Side-letter discount applied wrong";
  if (item.customer.includes("MedNova")) return "Usage overage needs approval";
  return "Upfront bill confused as revenue";
}

function plainProblem(item: CaseRow) {
  if (item.customer.includes("Acme")) return "The invoice charged too much for a new product and forgot an approved service credit.";
  if (item.customer.includes("Beta")) return "The invoice appears normal and should pass without an adjustment.";
  if (item.customer.includes("Northstar")) return "A special discount letter was applied to the wrong product line.";
  if (item.customer.includes("MedNova")) return "Extra usage was billed, but the contract may require written approval first.";
  return "The customer paid for a year upfront, but revenue should still be recognized month by month.";
}

function guideForCase(item: CaseRow) {
  if (item.customer.includes("Acme")) {
    return {
      question: "Should Acme pay this invoice as-is?",
      factA: "Invoice says: $20,000 due",
      factB: "Contract + credit say: $13,000",
      answer: "Propose a $7,000 credit",
      helper: "The AI must connect an upgrade clause and an approved service credit."
    };
  }
  if (item.customer.includes("Beta")) {
    return {
      question: "Is this clean renewal invoice okay?",
      factA: "Invoice matches the contract",
      factB: "Revenue schedule matches the month",
      answer: "No adjustment needed",
      helper: "This is the easy path that deterministic rules can handle."
    };
  }
  if (item.customer.includes("Northstar")) {
    return {
      question: "Was the discount applied to the right product?",
      factA: "Invoice used the discount on services",
      factB: "Side letter says Core subscription",
      answer: "Reclass the discount",
      helper: "The AI must understand side-letter language, not just totals."
    };
  }
  if (item.customer.includes("MedNova")) {
    return {
      question: "Can this usage overage be billed now?",
      factA: "Usage is 20% over the limit",
      factB: "Contract auto-bills only up to 10%",
      answer: "Hold billing for approval",
      helper: "The math is easy; the approval clause is the hard part."
    };
  }
  return {
    question: "Can a yearly payment become revenue today?",
    factA: "Customer paid $120,000 upfront",
    factB: "Service is delivered over 12 months",
    answer: "Recognize $10,000 this month",
    helper: "The AI must separate cash collection from revenue recognition."
  };
}

function connectionForCase(item: CaseRow) {
  if (item.customer.includes("Acme")) {
    return {
      visualProblem: "The customer was charged more than the trusted records allow.",
      invoiceLabel: "Customer was charged",
      invoiceValue: "$20,000",
      evidenceLabel: "Customer should pay",
      evidenceValue: "$13,000 after contract + approved credit",
      bridge: "$20,000 invoice - $13,000 allowed = $7,000 credit",
      short: "Compare bill to allowed amount",
      result: "Difference becomes the proposed credit"
    };
  }
  if (item.customer.includes("Beta")) {
    return {
      visualProblem: "The customer was charged the same amount the trusted records expect.",
      invoiceLabel: "Customer was charged",
      invoiceValue: "Matches renewal",
      evidenceLabel: "Trusted records expect",
      evidenceValue: "Same monthly amount",
      bridge: "Invoice matches contract = no correction",
      short: "Compare bill to contract",
      result: "Matching facts mean no adjustment"
    };
  }
  if (item.customer.includes("Northstar")) {
    return {
      visualProblem: "A discount was used in the wrong place.",
      invoiceLabel: "Invoice used discount on",
      invoiceValue: "Services",
      evidenceLabel: "Signed letter says use it on",
      evidenceValue: "Core subscription",
      bridge: "Discount was used on the wrong line = reclass it",
      short: "Compare invoice use to side letter",
      result: "Wrong placement becomes a reclass"
    };
  }
  if (item.customer.includes("MedNova")) {
    return {
      visualProblem: "The customer used more than the automatic billing limit.",
      invoiceLabel: "Usage over limit",
      invoiceValue: "20%",
      evidenceLabel: "Can auto-bill only up to",
      evidenceValue: "10% without written approval",
      bridge: "20% overage > 10% auto-bill limit = hold billing",
      short: "Compare usage to approval limit",
      result: "Too much usage needs written approval"
    };
  }
  return {
    visualProblem: "The customer paid for a year, but the company delivers the service month by month.",
    invoiceLabel: "Cash collected now",
    invoiceValue: "$120,000",
    evidenceLabel: "Revenue allowed this month",
    evidenceValue: "$10,000",
    bridge: "$120,000 paid upfront ÷ 12 months = $10,000 this month",
    short: "Compare cash to service period",
    result: "Payment is spread over time"
  };
}

function decisionLabel(decision: string) {
  const labels: Record<string, string> = {
    adjustment_required: "Fix the invoice",
    no_adjustment_required: "No fix needed",
    reclass_adjustment_required: "Reclass the discount",
    billing_hold_required: "Put billing on hold",
    no_billing_adjustment_but_revenue_schedule_required: "Fix revenue schedule",
    human_review_required: "Needs human review"
  };
  return labels[decision] ?? decision.split("_").join(" ");
}

function payloadWhy(key: string) {
  if (key === "synapsor") {
    return "Synapsor sends only the selected facts and evidence handles; database-owned context, safety, and replay stay out of the prompt.";
  }
  if (key === "postgres") {
    return "Postgres needs more text because the app has to paste raw rows, policies, rules, and workflow glue into the prompt.";
  }
  return "Rules-only does not call an LLM, so there is no model prompt.";
}

function laneOutcomeLabel(lane: LaneResult) {
  if (lane.lane === "synapsor_llm") {
    return lane.proposal_created ? "Created a governed proposal" : "Returned a governed answer";
  }
  if (lane.lane === "postgres_llm") {
    return lane.proposal_created ? "Created an app-managed proposal" : "Returned an app-managed answer";
  }
  return lane.decision === "no_adjustment_required" ? "Passed the simple case" : "Punted to human review";
}

function laneTakeaway(lane: LaneResult) {
  if (lane.lane === "synapsor_llm") {
    return "The AI reached the business answer with compact governed context, evidence handles, branch staging, and replay.";
  }
  if (lane.lane === "postgres_llm") {
    return "The AI can reason over the same issue, but the app has to assemble context, evidence, proposal state, and replay glue.";
  }
  return lane.decision === "no_adjustment_required"
    ? "Rules worked because this case was simple and known."
    : "Rules could not safely interpret the messy contract language.";
}

function approvalLabel(lane: LaneResult) {
  if (lane.approval?.state === "auto_approved") return "Auto-approved by Synapsor policy + audit";
  if (lane.lane === "synapsor_llm" && lane.proposal_created) return "Auto branch + governed proposal + replay";
  if (lane.lane === "postgres_llm") return lane.proposal_created ? "App-managed proposal flow" : "App-managed approval";
  if (lane.lane === "postgres_rules") return laneOutcomeLabel(lane);
  return lane.replay_available ? "Replayable governed answer" : laneOutcomeLabel(lane);
}

function appGlueSavings(run: RunBody) {
  const syn = run.results.find((lane) => lane.lane === "synapsor_llm");
  const pg = run.results.find((lane) => lane.lane === "postgres_llm");
  if (!syn || !pg) return { saved: 0, reduction: 0 };
  const saved = Math.max(0, pg.app_glue_lines - syn.app_glue_lines);
  const reduction = pg.app_glue_lines > 0 ? Math.round((saved / pg.app_glue_lines) * 100) : 0;
  return { saved, reduction };
}

function outputReason(lane: LaneResult, connection: ReturnType<typeof connectionForCase>) {
  if (lane.lane === "postgres_rules") {
    return lane.decision === "no_adjustment_required"
      ? "Why: the known rule matched the trusted records."
      : "Why: the rules found a problem but cannot safely explain messy contract language.";
  }
  if (lane.billing_adjustment_cents !== null && lane.billing_adjustment_cents !== 0) {
    return `Why: ${connection.bridge}.`;
  }
  return `Why: ${connection.result}.`;
}

function App() {
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [selected, setSelected] = useState("C2C-1001");
  const [run, setRun] = useState<RunBody | null>(null);
  const [sql, setSql] = useState("");
  const [loading, setLoading] = useState(true);
  const [runningLive, setRunningLive] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [guideStep, setGuideStep] = useState(0);
  const [agentPreview, setAgentPreview] = useState<AgentView | null>(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    Promise.all([api.cases(), api.capability()])
      .then(([caseRows, capability]) => {
        setCases(caseRows);
        setSql(capability.sql);
        setLoading(false);
      })
      .catch((error) => {
        setLoadError(error instanceof Error ? error.message : "failed to load demo");
        setLoading(false);
      });
  }, []);

  async function runLiveComparison() {
    const seq = ++requestSeq.current;
    setRunningLive(true);
    setLoadError("");
    try {
      const body = await api.run(selected, true);
      if (seq === requestSeq.current) {
        setRun(body);
        setGuideStep(4);
      }
    } catch (error) {
      if (seq === requestSeq.current) setLoadError(error instanceof Error ? error.message : "live run failed");
    } finally {
      if (seq === requestSeq.current) setRunningLive(false);
    }
  }

  async function resetSeedData() {
    setResetting(true);
    setLoadError("");
    try {
      await api.reset();
      setRun(null);
      setAgentPreview(null);
      setGuideStep(0);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "reset failed");
    } finally {
      setResetting(false);
    }
  }

  const currentCase = cases.find((item) => item.case_id === selected);
  const byLane = useMemo(() => {
    const result: Record<string, LaneResult> = {};
    run?.results.forEach((lane) => {
      result[lane.lane] = lane;
    });
    return result;
  }, [run]);

  async function showAgentPacketStep() {
    setGuideStep(3);
    setLoadError("");
    try {
      const preview = await api.agentPreview(selected);
      setAgentPreview(preview.agent_view);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "agent preview failed");
    }
  }

  return (
    <main className="app-shell">
      <aside className="queue">
        <div className="brand-lockup">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-name">SYNAPSOR</div>
            <div className="brand-subtitle">Contract-to-Cash Agent</div>
          </div>
        </div>
        <button className="run-button" onClick={() => setGuideStep(0)} disabled={!selected}>
          <Play size={16} /> Start guided review
        </button>
        <div className="run-help">
          The OpenAI Agents SDK run happens at the final walkthrough step.
        </div>
        <button className="reset-button" onClick={resetSeedData} disabled={resetting}>
          {resetting ? "Clearing..." : "Clear run view"}
        </button>
        <div className="run-help">
          Cases are immutable seed scenarios. This button clears the visible run; it does not hide a backend data rewrite.
        </div>
        <div className="queue-title">Pick a customer problem</div>
        <div className="case-list">
          {cases.map((item) => (
            <button
              key={item.case_id}
              className={`case-row ${item.case_id === selected ? "active" : ""}`}
              onClick={() => {
                setSelected(item.case_id);
                setRun(null);
                setAgentPreview(null);
                setGuideStep(0);
                setLoadError("");
              }}
            >
              <div className="case-row-top">
                <span>{item.customer}</span>
                <span className={`risk ${riskClass(item.risk)}`}>{item.risk}</span>
              </div>
              <strong>{friendlyCaseTitle(item)}</strong>
              <small>{plainProblem(item)}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="workspace guided-workspace">
        {currentCase && (
          <>
            <C2CPlainBrief currentCase={currentCase} />
            <GuidedReview
              currentCase={currentCase}
              run={run}
              agentPreview={agentPreview}
              guideStep={guideStep}
              setGuideStep={setGuideStep}
              showAgentPacketStep={showAgentPacketStep}
              runningLive={runningLive}
              runLiveComparison={runLiveComparison}
            />
          </>
        )}

        {loadError ? (
          <div className="error-box">
            <strong>Run did not load</strong>
            <span>{loadError}</span>
          </div>
        ) : loading ? (
          <div className="loading"><Activity className="spin" /> Loading demo shell</div>
        ) : run && guideStep >= 4 ? (
          <>
            <section className="quick-take">
              <div>
                <strong>Supporting proof</strong>
                <span>The answer is above. These sections show the token breakdown and technical trace without repeating the same lane cards.</span>
              </div>
            </section>

            <TokenPanel run={run} />

            <details className="technical-details">
              <summary>Open technical proof: evidence handles, branch proposal, SQL, and Agents SDK trace</summary>
              <section className="two-column">
                <SynapsorPanel lane={byLane.synapsor_llm} sql={sql} />
                <EvidencePanel lane={byLane.synapsor_llm} />
              </section>
              <TracePanel lanes={run.results} />
            </details>
          </>
        ) : (
          <section className="empty-state">
            <strong>No run has started yet.</strong>
            <span>Choose a customer problem, then press “Start guided review.” The OpenAI Agents SDK run happens only at the final step.</span>
          </section>
        )}
      </section>
    </main>
  );
}

function C2CPlainBrief({ currentCase }: { currentCase: CaseRow }) {
  return (
    <section className="c2c-plain-brief">
      <div>
        <span><EyeIcon /> 10-second story</span>
        <strong>Can the AI fix a messy billing problem without being handed the whole business world?</strong>
        <p>
          This demo compares three ways to review the same customer issue. The business answer matters,
          but the real Synapsor proof is who owns context, evidence, safe write proposals, settlement,
          and replay.
        </p>
      </div>
      <div className="brief-steps">
        <article>
          <b>1</b>
          <strong>Understand the bill</strong>
          <p>{plainProblem(currentCase)}</p>
        </article>
        <article>
          <b>2</b>
          <strong>Check trusted evidence</strong>
          <p>Contract clauses, credits, usage, and revenue policy decide the correct outcome.</p>
        </article>
        <article>
          <b>3</b>
          <strong>Compare three lanes</strong>
          <p>Synapsor + LLM, Postgres + LLM, and deterministic rules show different responsibility splits.</p>
        </article>
      </div>
    </section>
  );
}

function EyeIcon() {
  return <FileSearch size={16} />;
}

function GuidedReview({
  currentCase,
  run,
  agentPreview,
  guideStep,
  setGuideStep,
  showAgentPacketStep,
  runningLive,
  runLiveComparison
}: {
  currentCase: CaseRow;
  run: RunBody | null;
  agentPreview: AgentView | null;
  guideStep: number;
  setGuideStep: (step: number) => void;
  showAgentPacketStep: () => void;
  runningLive: boolean;
  runLiveComparison: () => void;
}) {
  const guide = guideForCase(currentCase);
  const connection = connectionForCase(currentCase);
  const [evidenceLane, setEvidenceLane] = useState<LaneResult | null>(null);
  const steps = [
    { label: "Problem", detail: "What went wrong?" },
    { label: "Invoice", detail: "What billing says" },
    { label: "Evidence", detail: "What changes the answer" },
    { label: "AI packet", detail: "What each lane sends" },
    { label: "Output", detail: "What each lane did" }
  ];
  const currentStep = steps[guideStep] ?? steps[0];
  return (
    <section className="guided-shell">
      <div className="stepper">
        {steps.map((step, index) => (
          <div className={`step-dot ${guideStep === index ? "active" : ""} ${guideStep > index ? "done" : ""}`} key={step.label}>
            <span>{index + 1}</span>
            <div>
              <strong>{step.label}</strong>
              <small>{step.detail}</small>
            </div>
          </div>
        ))}
      </div>

      {guideStep === 0 && (
        <div className="guided-card guided-stage start-card">
          <GuideDrawer title="What this step means">
            <div className="guide-narrative">
              <StepHeader step={1} title={currentStep.label} subtitle="Start with the business problem, not the database internals." />
              <span className={`risk ${riskClass(currentCase.risk)}`}>{currentCase.risk} risk</span>
              <h2>{friendlyCaseTitle(currentCase)}</h2>
              <p>{plainProblem(currentCase)}</p>
              <div className="plain-goal">
                <strong>What we are trying to find out</strong>
                <span>Did the company charge this customer the right amount, and can the AI safely propose a fix?</span>
              </div>
              <div className="simple-question">
                <small>The question</small>
                <strong>{guide.question}</strong>
              </div>
            </div>
          </GuideDrawer>
          <div className="story-visual money-scene" aria-hidden="true">
            <div className="visual-explainer">
              <strong>What is the problem?</strong>
              <span>{connection.visualProblem}</span>
            </div>
            <div className="amount-flow">
              <div className="floating-paper invoice-paper">
                <small>{connection.invoiceLabel}</small>
                <strong>{connection.invoiceValue}</strong>
              </div>
              <div className="connection-bridge">
                <small>{connection.short}</small>
                <strong>{connection.bridge}</strong>
              </div>
              <div className="floating-paper evidence-paper">
                <small>{connection.evidenceLabel}</small>
                <strong>{connection.evidenceValue}</strong>
              </div>
            </div>
            <div className="answer-bubble">{guide.answer}</div>
          </div>
          <div className="guided-actions stage-actions">
            <button className="primary-action" onClick={() => setGuideStep(1)}>Start with the invoice</button>
          </div>
        </div>
      )}

      {guideStep === 1 && (
        <div className="guided-card guided-stage">
          <GuideDrawer title="What this step means">
            <div className="guide-narrative">
              <StepHeader step={2} title={currentStep.label} subtitle="First, look at what the customer was asked to pay." />
              <h2>The invoice is only one side of the story.</h2>
              <p>Anyone can read the amount due. The hard part is proving whether that amount is allowed by the contract and company policy.</p>
              <div className="why-box">
                <strong>Why this step exists</strong>
                <span>We start with the invoice because it gives us the first number or claim. Next we compare it against trusted evidence.</span>
              </div>
            </div>
          </GuideDrawer>
          <div className="story-visual invoice-scene" aria-hidden="true">
            <div className="visual-explainer">
              <strong>First clue</strong>
              <span>The bill tells us what the customer is being asked to pay. It does not prove the amount is correct.</span>
            </div>
            <div className="invoice-sheet">
              <div className="sheet-line wide" />
              <div className="sheet-line" />
              <div className="sheet-line short" />
              <div className="total-row">
                <ReceiptText size={30} />
                <div>
                  <small>Amount shown</small>
                  <strong>{guide.factA}</strong>
                </div>
              </div>
            </div>
            <div className="warning-callout">This may be wrong</div>
            <div className="compare-strip">
              <span>Invoice</span>
              <ArrowRight size={16} />
              <span>Needs proof</span>
            </div>
          </div>
          <div className="large-fact invoice">
            <ReceiptText size={28} />
            <div>
              <small>What billing says</small>
              <strong>{guide.factA}</strong>
            </div>
          </div>
          <div className="guided-actions">
            <button className="secondary-action" onClick={() => setGuideStep(0)}>Back</button>
            <button className="primary-action" onClick={() => setGuideStep(2)}>Check the contract evidence</button>
          </div>
        </div>
      )}

      {guideStep === 2 && (
        <div className="guided-card guided-stage">
          <GuideDrawer title="What this step means">
            <div className="guide-narrative">
              <StepHeader step={3} title={currentStep.label} subtitle="Now check the trusted evidence that decides the answer." />
              <h2>The contract can change the result.</h2>
              <p>For messy business cases, the AI needs more than totals. It needs the exact contract words, approved credits, policies, and safe database context.</p>
              <div className="why-box">
                <strong>What the AI has to connect</strong>
                <span>{guide.helper}</span>
              </div>
            </div>
          </GuideDrawer>
          <div className="story-visual evidence-scene" aria-hidden="true">
            <div className="visual-explainer">
              <strong>Why the answer changes</strong>
              <span>Trusted records explain what should happen, then Synapsor turns that into a safe proposed action.</span>
            </div>
            <div className="evidence-sources">
              <div className="evidence-card contract-card"><FileText size={24} /> Contract</div>
              <div className="evidence-card credit-card"><BadgeCheck size={24} /> Credit</div>
              <div className="evidence-card policy-card"><ShieldCheck size={24} /> Policy</div>
            </div>
            <div className="evidence-equation">
              <small>Connection</small>
              <strong>{connection.bridge}</strong>
              <span>{connection.result}</span>
            </div>
            <div className="evidence-result">{guide.answer}</div>
          </div>
          <div className="large-fact contract">
            <FileText size={28} />
            <div>
              <small>What governed evidence says</small>
              <strong>{guide.factB}</strong>
            </div>
          </div>
          <div className="large-fact answer">
            <Scale size={28} />
            <div>
              <small>Correct outcome</small>
              <strong>{guide.answer}</strong>
            </div>
          </div>
          <div className="guided-actions">
            <button className="secondary-action" onClick={() => setGuideStep(1)}>Back</button>
            <button className="primary-action" onClick={showAgentPacketStep}>Show what each lane gives the AI</button>
          </div>
        </div>
      )}

      {guideStep === 3 && (
        <div className={`guided-card guided-stage packet-stage ${runningLive ? "running-card" : ""}`}>
          <GuideDrawer title="What this step means">
            <div className="guide-narrative">
              <StepHeader step={4} title={currentStep.label} subtitle="Before the AI answers, compare what each system gives it." />
              <h2>Cleaner context means a safer AI answer.</h2>
              <p>Synapsor gives the model a smaller, governed packet. Postgres can still work, but the app has to paste more raw material into the prompt. Rules do not use AI at all.</p>
            </div>
          </GuideDrawer>
          <div className="story-visual packet-scene" aria-hidden="true">
            <div className="visual-explainer">
              <strong>What does the AI actually receive?</strong>
              <span>Same business question, three very different context packages.</span>
            </div>
            <div className="packet-comparison">
              <div className="packet-card syn-packet-card">
                <div className="packet-head"><Bot size={25} /><strong>Synapsor</strong></div>
                <span className="packet-size">Compact packet</span>
                <ul>
                  <li>Selected facts</li>
                  <li>Evidence handles</li>
                  <li>Safe write path</li>
                </ul>
              </div>
              <div className="packet-arrow">versus</div>
              <div className="packet-card pg-packet-card">
                <div className="packet-head"><Database size={25} /><strong>Postgres app</strong></div>
                <span className="packet-size">Large prompt</span>
                <ul>
                  <li>Raw rows</li>
                  <li>Policy chunks</li>
                  <li>App workflow glue</li>
                </ul>
              </div>
              <div className="packet-card rules-packet-card">
                <div className="packet-head"><Boxes size={25} /><strong>Rules only</strong></div>
                <span className="packet-size">No AI packet</span>
                <ul>
                  <li>Known checks</li>
                  <li>No language judgment</li>
                  <li>Human fallback</li>
                </ul>
              </div>
            </div>
            <div className="packet-takeaway">
              <KeyRound size={20} />
              <strong>Synapsor reduces what the AI must read, while keeping evidence and writes governed by the database.</strong>
            </div>
          </div>
          <GuideDrawer title="View what each lane sends to the AI" className="lane-context-drawer">
            <div className="context-preview">
              <div className="context-pill syn">
                <strong>Synapsor + LLM</strong>
                <span>Compact governed packet: case, top evidence, handles, safety rules.</span>
              </div>
              <div className="context-pill pg">
                <strong>Postgres + LLM</strong>
                <span>Larger app-assembled packet: raw rows, chunks, rules, workflow glue.</span>
              </div>
              <div className="context-pill rules">
                <strong>Rules only</strong>
                <span>No AI packet. It runs deterministic checks and punts if language is messy.</span>
              </div>
            </div>
            {agentPreview ? (
              <AgentViewPanel agentView={agentPreview} compact />
            ) : (
              <div className="loading inline"><Activity className="spin" /> Loading exact agent packets</div>
            )}
          </GuideDrawer>
          <div className="guided-actions">
            <button className="secondary-action" onClick={() => setGuideStep(2)} disabled={runningLive}>Back</button>
            <div className="run-disclosure">
              <ShieldCheck size={16} />
              <span>
                This click creates a comparison report for the three lanes. It does not secretly change seed data;
                proposal and branch artifacts are shown explicitly in the result and evidence modal.
              </span>
            </div>
            <button className="primary-action" onClick={runLiveComparison} disabled={runningLive}>
              {runningLive ? <Activity className="spin" size={18} /> : <Play size={18} />}
              {runningLive ? "Running OpenAI Agents SDK comparison..." : "Run Agents SDK comparison"}
            </button>
          </div>
          {runningLive && (
            <div className="run-progress" aria-label="Live run progress">
              <div className="run-progress-step active">Synapsor prepares governed context</div>
              <div className="run-progress-step active delay-one">Postgres assembles raw context</div>
              <div className="run-progress-step active delay-two">Rules check known paths</div>
            </div>
          )}
        </div>
      )}

      {guideStep === 4 && run && (
        <div className="guided-card guided-stage result-card">
          <GuideDrawer title="What this step means">
            <div className="guide-narrative">
              <StepHeader step={5} title={currentStep.label} subtitle="Now compare the answer and the operating model." />
              <h2>Same problem. Different execution safety.</h2>
              <p>The important result is not only the business answer. It is how much context the AI needed, whether the write is staged safely, and whether the run can be replayed.</p>
            </div>
          </GuideDrawer>
          <div className="story-visual result-scene" aria-hidden="true">
            <div className="visual-explainer">
              <strong>What happened after the run?</strong>
              <span>All three lanes reviewed the same problem. The proof is shown directly below.</span>
            </div>
            <div className="verification-title">
              <strong>How to verify the agents did real work</strong>
              <span>Check the evidence they used, the reason they gave, and the artifact they produced.</span>
            </div>
            <div className="verification-chain">
              <div>
                <FileSearch size={18} />
                <strong>1. Evidence checked</strong>
                <span>{connection.invoiceValue} compared with {connection.evidenceValue}</span>
              </div>
              <div>
                <Scale size={18} />
                <strong>2. Reasoning shown</strong>
                <span>{connection.bridge}</span>
              </div>
              <div>
                <ShieldCheck size={18} />
                <strong>3. Work artifact</strong>
                <span>Proposal, evidence count, and replay/audit status</span>
              </div>
            </div>
            <div className="output-board">
              {run.results.map((lane, index) => (
                <div className={`output-lane ${lane.lane}`} key={lane.lane} style={{ animationDelay: `${index * 120}ms` }}>
                  <div className="output-lane-head">
                    {lane.lane === "synapsor_llm" ? <Bot size={24} /> : lane.lane === "postgres_llm" ? <Database size={24} /> : <Boxes size={24} />}
                    <div>
                      <small>{lane.title}</small>
                      <span>Output</span>
                      <strong>{decisionLabel(lane.decision)}</strong>
                    </div>
                  </div>
                  <p className="output-reason"><b>Agent said</b>{lane.reason}</p>
                  <div className="output-money">
                    <span>Invoice</span>
                    <strong>{fmtCents(lane.billing_adjustment_cents)}</strong>
                  </div>
                  <div className="output-money revenue">
                    <span>Revenue</span>
                    <strong>{fmtCents(lane.revenue_adjustment_cents)}</strong>
                  </div>
                  <div className="output-proof">
                    <span>{fmtTokens(lane.input_tokens)} input tokens</span>
                    <span>{fmtTokens(lane.app_glue_lines)} app glue LOC</span>
                    <button type="button" className="evidence-button" onClick={() => setEvidenceLane(lane)}>
                      {lane.evidence_items} evidence items
                    </button>
                  </div>
                  <div className="output-status">
                    <b>Proof</b>
                    {lane.lane === "synapsor_llm" && <><ShieldCheck size={16} /> {approvalLabel(lane)}</>}
                    {lane.lane === "postgres_llm" && <><GitBranch size={16} /> App-managed proposal flow</>}
                    {lane.lane === "postgres_rules" && <><History size={16} /> {laneOutcomeLabel(lane)}</>}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <ResultSummaryPanel run={run} />
          <div className="result-grid">
            <Fact label="Tokens saved" value={fmtTokens(run.token_savings.input_tokens_saved)} />
            <Fact label="Input reduction" value={`${run.token_savings.input_reduction_percent}%`} />
            <Fact label="App glue saved" value={`${fmtTokens(appGlueSavings(run).saved)} LOC`} />
            <Fact label="Mode" value={run.transparency?.run_type === "comparison_report" ? "Comparison report" : "OpenAI Agents SDK"} />
            <Fact label="Hidden mutations" value={run.transparency?.persistent_data_mutated ? "Yes" : "None"} />
          </div>
          {run.transparency?.note && (
            <div className="run-transparency-note">
              <ShieldCheck size={17} />
              <span>{run.transparency.note}</span>
            </div>
          )}
          <div className="mini-result-row">
            {run.results.map((lane) => (
              <div className={`mini-result ${lane.lane}`} key={lane.lane}>
                <small>{lane.title}</small>
                <strong>{decisionLabel(lane.decision)}</strong>
                <span>{laneOutcomeLabel(lane)}</span>
              </div>
            ))}
          </div>
          <div className="guided-actions">
            <button className="secondary-action" onClick={() => setGuideStep(3)}>Back to context comparison</button>
          </div>
          {evidenceLane && <EvidenceModal lane={evidenceLane} onClose={() => setEvidenceLane(null)} />}
        </div>
      )}
    </section>
  );
}

function GuideDrawer({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`guide-drawer ${open ? "open" : ""} ${className}`}>
      <button
        type="button"
        className="guide-drawer-summary"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{title}</span>
        <strong>{open ? "Close" : "Open"}</strong>
      </button>
      <div className="drawer-body" aria-hidden={!open}>
        <div className="drawer-body-inner">{children}</div>
      </div>
    </div>
  );
}

function EvidenceModal({ lane, onClose }: { lane: LaneResult; onClose: () => void }) {
  const proposal = lane.proposal as { lifecycle?: string[]; branch?: string; proposal_handle?: string } | null;
  const lifecycle = proposal?.lifecycle ?? [];
  const approvalLifecycle = lane.approval?.lifecycle ?? [];
  const hasEvidence = lane.evidence_details.length > 0;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  return createPortal(
    <div className="evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-modal-title" onClick={onClose}>
      <div className="evidence-modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="evidence-modal-head">
          <div>
            <small>{lane.title}</small>
            <h3 id="evidence-modal-title">Evidence and agent work</h3>
            <span>{decisionLabel(lane.decision)} · {lane.evidence_items} evidence item{lane.evidence_items === 1 ? "" : "s"}</span>
          </div>
          <button type="button" onClick={onClose} aria-label="Close evidence modal">
            <X size={18} />
            Close
          </button>
        </div>

        <section className="agent-said-box">
          <strong>What the lane said</strong>
          <p>{lane.reason}</p>
        </section>

        <section className="agent-said-box transparency-box">
          <strong>{lane.lane === "synapsor_llm" ? "What changed in the demo" : "What this lane owns"}</strong>
          <p>
            {lane.lane === "synapsor_llm"
              ? "The demo returns Synapsor branch, proposal, settlement, evidence, and replay artifacts explicitly. It does not hide a separate backend mutation after the run."
              : lane.lane === "postgres_llm"
                ? "Postgres can reach the same business answer, but the app owns evidence assembly, proposal workflow, audit, and replay reconstruction."
                : "The rules lane performs deterministic checks only and does not call an LLM or create proposal artifacts."}
          </p>
        </section>

        {lane.lane === "synapsor_llm" && lifecycle.length > 0 && (
          <section className="branch-graph">
            <div className="branch-graph-head">
              <strong>How Synapsor staged the production update</strong>
              <span>Branch and write lifecycle are database-owned, not app glue.</span>
            </div>
            <div className="branch-flow">
              {lifecycle.map((step, index) => (
                <div className="branch-node" key={step}>
                  <span>{index + 1}</span>
                  <strong>{step}</strong>
                </div>
              ))}
            </div>
            <div className="branch-artifacts">
              <span>Branch: <b>{proposal?.branch}</b></span>
              <span>Proposal: <b>{proposal?.proposal_handle}</b></span>
            </div>
          </section>
        )}

        {lane.lane === "synapsor_llm" && lifecycle.length === 0 && approvalLifecycle.length > 0 && (
          <section className="branch-graph auto-approval-graph">
            <div className="branch-graph-head">
              <strong>How Synapsor auto-approved the low-risk case</strong>
              <span>No production write was needed. Synapsor applied DB-owned approval rules and recorded the decision.</span>
            </div>
            <div className="branch-flow auto-approval-flow">
              {approvalLifecycle.map((step, index) => (
                <div className="branch-node" key={step}>
                  <span>{index + 1}</span>
                  <strong>{step}</strong>
                </div>
              ))}
            </div>
            <div className="branch-artifacts">
              <span>Approval: <b>{lane.approval?.state}</b></span>
              <span>Mode: <b>{lane.approval?.mode}</b></span>
              {lane.approval?.artifact && <span>Audit: <b>{lane.approval.artifact}</b></span>}
            </div>
          </section>
        )}

        <section className="evidence-list-section">
          <div className="branch-graph-head">
            <strong>{lane.lane === "synapsor_llm" ? "Evidence handles selected by Synapsor" : "Evidence used by this lane"}</strong>
            <span>{lane.lane === "synapsor_llm" ? "The LLM receives compact snippets and handles; full evidence stays governed by the DB." : "Postgres evidence is assembled by the app before the LLM sees it."}</span>
          </div>
          {hasEvidence ? (
            <div className="evidence-list">
              {lane.evidence_details.map((item) => (
                <article className="evidence-item" key={item.handle}>
                  <div>
                    <small>{item.kind} · {item.source}</small>
                    <strong>{item.title}</strong>
                  </div>
                  <code>{item.handle}</code>
                  <p>{item.snippet}</p>
                </article>
              ))}
            </div>
          ) : (
            <div className="no-evidence">
              <strong>No LLM evidence packet</strong>
              <span>This rules lane runs deterministic checks and punts when the case needs language judgment.</span>
            </div>
          )}
        </section>
      </div>
    </div>,
    document.body
  );
}

function StepHeader({ step, title, subtitle }: { step: number; title: string; subtitle: string }) {
  return (
    <div className="step-header">
      <span>Step {step}</span>
      <div>
        <strong>{title}</strong>
        <small>{subtitle}</small>
      </div>
    </div>
  );
}

function TurboGuide({ currentCase }: { currentCase: CaseRow }) {
  const guide = guideForCase(currentCase);
  return (
    <div className="turbo-guide" aria-label="Guided business problem explanation">
      <div className="guide-kicker">
        <span className={`risk ${riskClass(currentCase.risk)}`}>{currentCase.risk} risk</span>
        <span>{friendlyCaseTitle(currentCase)}</span>
      </div>
      <h2>{guide.question}</h2>
      <div className="step-explainer">
        <span><b>Problem</b> identify what looks wrong</span>
        <span><b>Invoice</b> read the billed amount</span>
        <span><b>Evidence</b> check contract and policy</span>
        <span><b>AI packet</b> compare what each lane sends</span>
        <span><b>Output</b> see each lane’s answer</span>
      </div>
      <p>{plainProblem(currentCase)}</p>

      <div className="guide-flow">
        <div className="guide-card invoice">
          <ReceiptText size={24} />
          <strong>{guide.factA}</strong>
          <small>billing system</small>
        </div>
        <div className="guide-arrow"><ArrowRight size={20} /></div>
        <div className="guide-card contract">
          <FileText size={24} />
          <strong>{guide.factB}</strong>
          <small>contract evidence</small>
        </div>
        <div className="guide-arrow"><ArrowRight size={20} /></div>
        <div className="guide-card answer">
          <Scale size={24} />
          <strong>{guide.answer}</strong>
          <small>safe proposal</small>
        </div>
      </div>

      <div className="guide-bottom">
        <ShieldCheck size={18} />
        <div>
          <strong>Why this needs an agent</strong>
          <span>{guide.helper}</span>
        </div>
      </div>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function ResultSummaryPanel({ run }: { run: RunBody }) {
  const syn = run.results.find((lane) => lane.lane === "synapsor_llm");
  const pg = run.results.find((lane) => lane.lane === "postgres_llm");
  const rules = run.results.find((lane) => lane.lane === "postgres_rules");
  const lanes = [syn, pg, rules].filter(Boolean) as LaneResult[];
  return (
    <section className="result-summary">
      <div className="result-summary-head">
        <strong>Three-lane output</strong>
        <span>Same case, three execution models.</span>
      </div>
      <div className="result-summary-grid">
        {lanes.map((lane) => (
          <article className={`result-output ${lane.lane}`} key={lane.lane}>
            <div className="result-output-title">
              <small>{lane.title}</small>
              {lane.replay_available && <span>Replayable</span>}
            </div>
            <h3>{decisionLabel(lane.decision)}</h3>
            <p>{lane.reason}</p>
            <div className="result-output-facts">
              <Fact label="Invoice change" value={fmtCents(lane.billing_adjustment_cents)} />
              <Fact label="Revenue change" value={fmtCents(lane.revenue_adjustment_cents)} />
              <Fact label="Output" value={laneOutcomeLabel(lane)} />
            </div>
            <div className="takeaway">{laneTakeaway(lane)}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

function AgentViewPanel({ agentView, compact = false }: { agentView: AgentView; compact?: boolean }) {
  const [fullscreenPayload, setFullscreenPayload] = useState<null | { label: string; view: AgentView[string] }>(null);
  const cards = [
    ["synapsor", "Synapsor + LLM"],
    ["postgres", "Postgres + LLM"],
    ["rules", "Rules only"]
  ] as const;

  useEffect(() => {
    if (!fullscreenPayload) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreenPayload(null);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [fullscreenPayload]);

  const fullscreenModal = fullscreenPayload ? createPortal(
    <div className="payload-modal" role="dialog" aria-modal="true" aria-labelledby="payload-modal-title" onClick={() => setFullscreenPayload(null)}>
      <div className="payload-modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="payload-modal-head">
          <div>
            <small>Exact text sent to the agent</small>
            <h3 id="payload-modal-title">{fullscreenPayload.label}</h3>
            <span>
              {fmtTokens(fullscreenPayload.view.char_count)} chars · {fmtTokens(fullscreenPayload.view.word_count)} words
            </span>
          </div>
          <button type="button" onClick={() => setFullscreenPayload(null)} aria-label="Close full screen payload">
            <X size={18} />
            Close
          </button>
        </div>
        <pre>{fullscreenPayload.view.raw_text}</pre>
      </div>
    </div>,
    document.body
  ) : null;

  return (
    <section className={`agent-view ${compact ? "compact" : ""}`}>
      <div className="agent-view-head">
        <div>
          <strong>What the AI sees when you run it</strong>
          <span>Same business problem. Very different context handed to the decision maker.</span>
        </div>
      </div>
      <div className="agent-view-grid">
        {cards.map(([key, label]) => {
          const view = agentView?.[key] ?? {
            title: "Context unavailable",
            summary: "This run did not return an agent-view payload.",
            items: [],
            raw_text: "",
            char_count: 0,
            word_count: 0
          };
          return (
            <div className={`agent-packet ${key}`} key={key}>
              <small>{label}</small>
              <h3>{view.title}</h3>
              <p>{view.summary}</p>
              <div className="payload-size">
                <span>{fmtTokens(view.char_count)} chars</span>
                <span>{fmtTokens(view.word_count)} words</span>
                <span className="why-chip" tabIndex={0}>
                  why?
                  <em>{payloadWhy(key)}</em>
                </span>
              </div>
              <button
                className="fullscreen-button"
                type="button"
                onClick={() => setFullscreenPayload({ label, view })}
                disabled={!view.raw_text}
              >
                <Maximize2 size={15} />
                View full screen
              </button>
              <ul>
                {view.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <details className="raw-agent-text">
                <summary>Show exact text sent to the agent</summary>
                <pre>{view.raw_text}</pre>
              </details>
            </div>
          );
        })}
      </div>
      {fullscreenModal}
    </section>
  );
}

function LaneCard({ lane, baselineTokens }: { lane: LaneResult; baselineTokens: number }) {
  const isSynapsor = lane.lane === "synapsor_llm";
  const plainLabel =
    lane.lane === "synapsor_llm"
      ? "Best path: AI plus database safety"
      : lane.lane === "postgres_llm"
        ? "Works, but the app must glue everything"
        : "Cheap, but punts on messy language";
  const tokenDelta = baselineTokens - lane.input_tokens;
  const Icon = lane.lane === "postgres_rules" ? Boxes : lane.lane === "postgres_llm" ? Database : Bot;
  return (
    <article className={`lane-card ${isSynapsor ? "synapsor" : ""}`}>
      <div className="lane-head">
        <div className="lane-title">
          <Icon size={20} />
          <div>
            <h3>{lane.title}</h3>
            <small>{plainLabel}</small>
          </div>
        </div>
        {isSynapsor && <span className="native-badge"><BadgeCheck size={14} /> Native</span>}
      </div>
      <div className="decision">{decisionLabel(lane.decision)}</div>
      <p>{lane.reason}</p>
      <div className="adjustments">
        <Fact label="Invoice change" value={fmtCents(lane.billing_adjustment_cents)} />
        <Fact label="Revenue change" value={fmtCents(lane.revenue_adjustment_cents)} />
      </div>
      <div className="simple-score">
        <div>
          <small>Input tokens</small>
          <strong>{fmtTokens(lane.input_tokens)}</strong>
        </div>
        <div>
          <small>Evidence</small>
          <strong>{lane.evidence_items || "none"}</strong>
        </div>
        <div>
          <small>App glue LOC</small>
          <strong>{fmtTokens(lane.app_glue_lines)}</strong>
        </div>
        <div>
          <small>Safety</small>
          <strong>{lane.replay_available ? "Replayable" : lane.proposal_created ? "App-owned" : "Limited"}</strong>
        </div>
      </div>
      <div className="capability-row">
        <Status on={lane.proposal_created} label="proposal" />
        <Status on={lane.branch_created} label={isSynapsor ? "auto branch" : "branch"} />
        <Status on={lane.replay_available} label="replay" />
      </div>
      {isSynapsor && (
        <div className="savings-pill">Saves {fmtTokens(Math.max(tokenDelta, 0))} input tokens vs Postgres + LLM</div>
      )}
      <div className="lane-foot"><Clock3 size={14} /> {lane.elapsed_ms} ms · {lane.tool_calls} tool calls · {lane.db_round_trips} DB trips</div>
    </article>
  );
}

function Status({ on, label }: { on: boolean; label: string }) {
  return <span className={on ? "status-on" : "status-off"}>{on ? <CheckCircle2 size={13} /> : <span />} {label}</span>;
}

function TokenPanel({ run }: { run: RunBody }) {
  const syn = run.results.find((lane) => lane.lane === "synapsor_llm");
  const pg = run.results.find((lane) => lane.lane === "postgres_llm");
  if (!syn || !pg) {
    return (
      <section className="panel token-panel">
        <div className="panel-title"><Banknote size={18} /> Token comparison unavailable</div>
      </section>
    );
  }
  const max = Math.max(syn.input_tokens, pg.input_tokens);
  const glue = appGlueSavings(run);
  return (
    <section className="panel token-panel">
      <div className="panel-title"><Banknote size={18} /> Why Synapsor uses fewer tokens</div>
      <p className="panel-copy">Postgres makes the app paste more raw business context into the prompt. Synapsor sends the AI a smaller, governed packet with evidence handles.</p>
      <Breakdown title="Synapsor + LLM" data={syn.payload_breakdown} total={syn.input_tokens} max={max} highlight />
      <Breakdown title="Postgres + LLM" data={pg.payload_breakdown} total={pg.input_tokens} max={max} />
      <div className="savings-total">
        <strong>{fmtTokens(run.token_savings.input_tokens_saved)}</strong>
        <span>input tokens saved on this run</span>
      </div>
      <div className="loc-comparison">
        <div>
          <small>Synapsor app glue</small>
          <strong>{fmtTokens(syn.app_glue_lines)} LOC</strong>
        </div>
        <div>
          <small>Postgres + LLM app glue</small>
          <strong>{fmtTokens(pg.app_glue_lines)} LOC</strong>
        </div>
        <div className="loc-saved">
          <small>App glue reduction</small>
          <strong>{fmtTokens(glue.saved)} LOC saved ({glue.reduction}%)</strong>
        </div>
      </div>
    </section>
  );
}

function Breakdown({ title, data, total, max, highlight = false }: { title: string; data: Record<string, number>; total: number; max: number; highlight?: boolean }) {
  return (
    <div className="breakdown">
      <div className="breakdown-head">
        <strong>{title}</strong>
        <span>{fmtTokens(total)} tokens</span>
      </div>
      <div className="stack" style={{ width: `${Math.max(8, (total / max) * 100)}%` }}>
        {Object.entries(data).map(([key, value]) => (
          <span key={key} title={`${key}: ${value}`} style={{ width: `${(value / total) * 100}%` }} className={highlight ? "seg syn" : "seg"} />
        ))}
      </div>
      <div className="legend">
        {Object.entries(data).map(([key, value]) => (
          <span key={key}>{key}: {fmtTokens(value)}</span>
        ))}
      </div>
    </div>
  );
}

function SynapsorPanel({ lane, sql }: { lane: LaneResult; sql: string }) {
  const proposal = lane.proposal as {
    proposal_handle?: string;
    branch?: string;
    branch_policy?: string;
    created_by?: string;
    lifecycle?: string[];
    allowed_columns?: string[];
  } | null;
  return (
    <section className="panel syn-panel">
      <div className="panel-title"><LockKeyhole size={18} /> Synapsor Control Plane</div>
      <div className="control-grid">
        <Fact label="Write proposal" value={proposal?.proposal_handle ?? "none"} />
        <Fact label="Branch" value={proposal?.branch ?? "none"} />
        <Fact label="Branch policy" value={proposal?.branch_policy === "auto_create_on_proposal" ? "auto-create on proposal" : "none"} />
        <Fact label="Hybrid syntax" value="SEARCH USING HYBRID" />
        <Fact label="Response shape" value="RETURNS JSON + aliases" />
        <Fact label="Evidence mode" value="handles_only" />
        <Fact label="Security" value="tenant policy + redaction" />
      </div>
      {proposal?.lifecycle && (
        <div className="branch-lifecycle">
          <strong>DB-owned branch/write lifecycle</strong>
          <div>
            {proposal.lifecycle.map((step) => (
              <span key={step}>{step}</span>
            ))}
          </div>
        </div>
      )}
      <div className="code-window">
        <pre>{sql}</pre>
      </div>
    </section>
  );
}

function EvidencePanel({ lane }: { lane: LaneResult }) {
  return (
    <section className="panel">
      <div className="panel-title"><FileSearch size={18} /> Governed Evidence Handles</div>
      <div className="handles">
        {lane.evidence_handles.map((handle) => (
          <div className="handle" key={handle}>
            <ShieldCheck size={15} />
            <span>{handle}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TracePanel({ lanes }: { lanes: LaneResult[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><History size={18} /> Agent Time Travel & Lane Trace</div>
      <div className="trace-columns">
        {lanes.map((lane) => (
          <div className="trace" key={lane.lane}>
            <strong>{lane.title}</strong>
            {lane.trace.map((step, index) => (
              <div className="trace-row" key={`${lane.lane}-${step.step}`}>
                <span>{index + 1}</span>
                <div>
                  <b>{step.step}</b>
                  <small>{step.detail}</small>
                </div>
                {index < lane.trace.length - 1 && <ArrowRight size={13} />}
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

export default App;
