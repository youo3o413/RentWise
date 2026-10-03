import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Building2,
  Calculator,
  Check,
  ChevronDown,
  ChevronUp,
  CircleDollarSign,
  Clock3,
  ExternalLink,
  Home,
  LoaderCircle,
  Lock,
  MapPin,
  MapPinned,
  Route,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Unlock,
} from "lucide-react";
import {
  getHealth,
  mediaUrl,
  getMapContext,
  getRecommendation,
  parseRequirements,
  resolveDestination,
  sendRecommendationFeedback,
} from "./api";
import MapView from "./MapView";
import { isPetPreference, setPetPreference } from "./petPreferences";

const NTU_DESTINATION = {
  resolved_label: "台北市 · 大安區 · 國立臺灣大學（公館校區）",
  resolved_address: "台北市大安區羅斯福路四段 1 號",
  region_name: "台北市",
  latitude: 25.0174,
  longitude: 121.5397,
  source: "demo_landmark",
};
const initialForm = {
  budget: 15000,
  destination: "政治大學",
  max_commute_minutes: 25,
  needs_window: true,
  noise_preference: "quiet",
  needs_elevator: false,
  needs_convenience_store: true,
  max_floor_without_elevator: 3,
  preferences: ["採光良好", "可開伙"],
  property_source: "mock",
  weights: {
    location: 30,
    cost: 30,
    property: 40,
  },
  commute_mode: "transit_walk",
  needs_parking: false,
  needs_rental_subsidy: false,
};

const agentMeta = {
  "Requirement Agent": { icon: Bot, label: "LangGraph 前置需求解析" },
  "Source Planning Agent": { icon: Route, label: "房源搜尋範圍規劃" },
  "Data Loader": { icon: Building2, label: "載入房源資料" },
  "Location Agent": { icon: MapPin, label: "步行與大眾運輸通勤分析" },
  "Cost Agent": { icon: CircleDollarSign, label: "每月租屋成本估算" },
  "Property Agent": { icon: Home, label: "房況與設備檢查" },
  "Suitability Agent": { icon: ShieldCheck, label: "個人適配度評估" },
  "Decision Explanation Agent": { icon: Bot, label: "依既定排名產生決策說明" },
};

function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      className={`toggle ${checked ? "active" : ""}`}
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
    >
      <span className="toggle-dot" />
      {label}
    </button>
  );
}

const weightLabels = {
  location: "通勤與生活圈",
  cost: "每月成本",
  property: "房屋條件",
};

const requirementFieldLabels = {
  budget: "預算",
  destination: "目的地",
  max_commute_minutes: "通勤上限",
  needs_window: "對外窗",
  noise_preference: "安靜程度",
  needs_elevator: "電梯",
  needs_convenience_store: "附近超商",
  max_floor_without_elevator: "樓層上限",
  preferences: "其他偏好",
  weights: "適配權重",
  commute_mode: "通勤方式",
  needs_parking: "停車需求",
  needs_rental_subsidy: "租金補貼",
};

const weightNames = Object.keys(weightLabels);

function distributeIntegerTotal(entries, total) {
  if (!entries.length) return {};
  const sourceTotal = entries.reduce((sum, [, value]) => sum + Number(value), 0);
  const exact = entries.map(([name, value]) => [
    name,
    sourceTotal ? Number(value) / sourceTotal * total : total / entries.length,
  ]);
  const result = Object.fromEntries(exact.map(([name, value]) => [name, Math.floor(value)]));
  let remainder = total - Object.values(result).reduce((sum, value) => sum + value, 0);
  exact
    .sort((a, b) => (b[1] - Math.floor(b[1])) - (a[1] - Math.floor(a[1])))
    .forEach(([name]) => {
      if (remainder > 0) {
        result[name] += 1;
        remainder -= 1;
      }
    });
  return result;
}

function normalizeWeights(weights) {
  return distributeIntegerTotal(Object.entries(weights), 100);
}

function rebalanceWeights(weights, changedName, requestedValue, locks) {
  if (locks[changedName]) return weights;
  const lockedOthers = weightNames.filter((name) => name !== changedName && locks[name]);
  const lockedTotal = lockedOthers.reduce((sum, name) => sum + Number(weights[name]), 0);
  const unlockedOthers = weightNames.filter((name) => name !== changedName && !locks[name]);
  const changedValue = Math.max(0, Math.min(100 - lockedTotal, Math.round(requestedValue)));
  const remaining = 100 - lockedTotal - changedValue;
  return {
    ...weights,
    ...distributeIntegerTotal(
      unlockedOthers.map((name) => [name, weights[name]]),
      remaining,
    ),
    [changedName]: unlockedOthers.length ? changedValue : 100 - lockedTotal,
  };
}

function WeightControl({ name, value, locked, max, onChange, onToggleLock }) {
  return (
    <div className={`weight-control ${locked ? "locked" : ""}`}>
      <span>
        <strong>{weightLabels[name]}</strong>
        <span>
          <b>{value}%</b>
          <button
            type="button"
            className="weight-lock"
            onClick={() => onToggleLock(name)}
            aria-label={`${locked ? "解除鎖定" : "鎖定"}${weightLabels[name]}權重`}
            title={locked ? "解除鎖定" : "鎖定此權重"}
          >
            {locked ? <Lock size={12} /> : <Unlock size={12} />}
          </button>
        </span>
      </span>
      <input
        type="range"
        min="0"
        max={max}
        step="1"
        value={value}
        disabled={locked}
        onChange={(event) => onChange(name, Number(event.target.value))}
      />
    </div>
  );
}

function AgentPipeline({ trace, loading }) {
  const defaultAgents = Object.keys(agentMeta);
  const completed = new Map((trace || []).map((item) => [item.agent, item]));

  return (
    <section className="panel pipeline-panel">
      <div className="section-title">
        <div>
          <span className="eyebrow">LANGGRAPH WORKFLOW</span>
          <h2>Agent 協作流程</h2>
        </div>
        {loading && <LoaderCircle className="spin" size={22} />}
      </div>
      <div className="pipeline">
        {defaultAgents.map((name, index) => {
          const meta = agentMeta[name];
          const Icon = meta.icon;
          const done = completed.has(name);
          return (
            <div className="pipeline-row" key={name}>
              <div className={`agent-icon ${done ? "done" : loading ? "pending" : ""}`}>
                {done ? <Check size={18} /> : <Icon size={18} />}
              </div>
              <div className="agent-copy">
                <strong>{name}</strong>
                <span>{completed.get(name)?.message || meta.label}</span>
              </div>
              <span className={`status-pill ${done ? "done" : ""}`}>
                {done ? "完成" : loading && index === completed.size ? "執行中" : "待命"}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ScoreRing({ score, status = "qualified" }) {
  const rounded = Math.round(score);
  const visibleStatus = status === "qualified" ? "qualified" : "needs_verification";
  const label = visibleStatus === "qualified"
    ? "合格"
    : "待確認";
  return (
    <div
      className={`score-ring ${visibleStatus}`}
      style={{ "--score": `${rounded * 3.6}deg` }}
    >
      <div>
        <strong>{rounded}</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}

function hasMetric(value) {
  return value !== undefined && value !== null && value !== "unknown";
}

function AssessmentCalculation({ assessment, assessments }) {
  const metrics = assessment.metrics || {};
  const score = Number(assessment.score).toFixed(1);
  let calculation = "";
  let explanation = "";

  if (assessment.agent === "Location Agent") {
    if (!hasMetric(metrics.commute_score)) {
      calculation = "通勤時間尚未取得，因此目前無法計算 Location 分數";
    } else {
      const commuteRatio = Number(metrics.commute_ratio) * 100;
      const components = [
        `通勤 ${Number(metrics.commute_score).toFixed(1)} × ${Math.round(Number(metrics.commute_component_weight) * 100)}%`,
      ];
      if (Number(metrics.store_component_weight) > 0 && hasMetric(metrics.store_score)) {
        components.push(
          `超商 ${Number(metrics.store_score).toFixed(1)} × ${Math.round(Number(metrics.store_component_weight) * 100)}%`,
        );
      }
      if (Number(metrics.parking_component_weight) > 0 && hasMetric(metrics.parking_score)) {
        components.push(
          `停車 ${Number(metrics.parking_score).toFixed(1)} × ${Math.round(Number(metrics.parking_component_weight) * 100)}%`,
        );
      }
      calculation = `${components.join(" ＋ ")} ＝ ${score} 分`;
      explanation = `通勤 ${metrics.commute_minutes} ÷ 上限 ${metrics.commute_limit} 分鐘＝${commuteRatio.toFixed(0)}%，先換算為 ${Number(metrics.commute_score).toFixed(1)} 分`;
    }
  } else if (assessment.agent === "Cost Agent") {
    const ratio = Number(metrics.cost_ratio);
    const band = ratio <= 0.7
      ? "使用預算 70% 以下"
      : ratio <= 1
        ? "落在預算 70–100% 區間"
        : ratio <= 1.2
          ? "超出預算 0–20% 區間"
          : "超出預算 20% 以上";
    calculation = `NT$ ${Number(metrics.estimated_monthly_cost).toLocaleString()} ÷ NT$ ${Number(metrics.budget).toLocaleString()} ＝ ${(ratio * 100).toFixed(1)}% → ${score} 分`;
    explanation = band;
  } else if (assessment.agent === "Property Agent") {
    const met = Number(metrics.met_count);
    const unmet = Number(metrics.unmet_count);
    const known = met + unmet;
    calculation = known
      ? `${met} 項符合 ÷ ${known} 項已知條件 ＝ ${score} 分`
      : "沒有已知條件，因此不產生 Property 分數";
    explanation = `${metrics.unknown_count} 項待確認；資料完整度 ${metrics.data_completeness}% 另外顯示，不混入分數`;
  } else if (assessment.agent === "Suitability Agent") {
    const labels = {
      location: "Location",
      cost: "Cost",
      property: "Property",
    };
    const rawScores = {
      location: assessments.location?.score,
      cost: assessments.cost?.score,
      property: assessments.property?.score,
    };
    const parts = Object.keys(labels)
      .filter((key) => metrics[`${key}_available`] && Number(metrics[`${key}_weight`]) > 0)
      .map((key) => (
        `${labels[key]} ${Number(rawScores[key]).toFixed(1)} × ${(Number(metrics[`${key}_weight`]) * 100).toFixed(1)}%`
      ));
    calculation = `${parts.join(" ＋ ")} ＝ ${score} 分`;
    const issues = [metrics.disqualifying_conflicts, metrics.pending_conditions]
      .filter(Boolean)
      .join("、");
    const baseExplanation = metrics.qualification_status === "needs_verification"
        ? `仍有條件或風險待確認：${issues}`
        : `必要條件皆有證據符合；證據涵蓋原權重 ${metrics.evidence_coverage_percent}%`;
    explanation = baseExplanation;
  } else {
    return null;
  }

  return (
    <p className="assessment-calculation">
      <Calculator size={14} />
      <span>
        <strong>本房源計算</strong>
        <b>{calculation}</b>
        {explanation && <small>{explanation}</small>}
      </span>
    </p>
  );
}

function ScoreBreakdown({ item }) {
  const suitability = item.assessments.suitability;
  const metrics = suitability.metrics;
  const locationMetrics = item.assessments.location.metrics;
  const costMetrics = item.assessments.cost.metrics;
  const propertyMetrics = item.assessments.property.metrics;
  const rows = [
    {
      key: "location",
      label: "通勤與生活圈",
      score: item.assessments.location.score,
      available: metrics.location_available,
    },
    {
      key: "cost",
      label: "每月成本",
      score: item.assessments.cost.score,
      available: metrics.cost_available,
    },
    {
      key: "property",
      label: "房屋條件",
      score: item.assessments.property.score,
      available: metrics.property_available,
    },
  ];
  const qualificationStatus = metrics.qualification_status === "qualified"
    ? "qualified"
    : "needs_verification";
  const qualified = qualificationStatus === "qualified";
  return (
    <details className="score-breakdown">
      <summary>適配分怎麼算？</summary>
      <div>
        <p className="formula-version">
          {metrics.formula_version} · 相同輸入會得到相同結果
        </p>
        {rows.map(({ key, label, score, available }) => {
          const originalWeight = Number(metrics[`original_${key}_weight`] || 0);
          const effectiveWeight = Number(metrics[`${key}_weight`] || 0);
          const contribution = Number(metrics[`${key}_contribution`] || 0);
          return (
          <span key={key} className={available ? "" : "unavailable"}>
            <strong>{label}</strong>
            <i>
              {available ? (
                <>
                  {Math.round(score)} × {Math.round(effectiveWeight * 100)}%
                  {Math.round(originalWeight * 100) !== Math.round(effectiveWeight * 100)
                    ? `（原 ${Math.round(originalWeight * 100)}%）`
                    : ""}
                </>
              ) : `未取得，原 ${Math.round(originalWeight * 100)}% 已重新分配`}
            </i>
            <b>{available ? contribution.toFixed(1) : "—"}</b>
          </span>
        )})}
        {!qualified && (
          <span className={`qualification-fail ${qualificationStatus}`}>
            <strong>必要條件資格</strong>
            <i>
              {qualificationStatus === "needs_verification"
                ? [metrics.disqualifying_conflicts, metrics.pending_conditions]
                    .filter(Boolean)
                    .join("、")
                : ""}
            </i>
            <b>待確認</b>
          </span>
        )}
        <span className="score-total">
          <strong>
            {qualified
              ? "最終適配分"
              : "參考分數（待確認）"}
          </strong><i />
          <b>{Number(item.total_score).toFixed(1)}</b>
        </span>
        <div className="score-evidence">
          <span>
            通勤：{locationMetrics.commute_minutes === "unknown"
              ? "未取得"
              : `${locationMetrics.commute_minutes} ÷ ${locationMetrics.commute_limit} 分鐘`
            }
            {locationMetrics.commute_ratio !== "unknown"
              ? ` = ${Math.round(Number(locationMetrics.commute_ratio) * 100)}%`
              : ""}
          </span>
          <span>
            Location 內部權重：通勤 {Math.round(Number(locationMetrics.commute_component_weight) * 100)}%
            {Number(locationMetrics.store_component_weight) > 0
              ? ` · 超商 ${Math.round(Number(locationMetrics.store_component_weight) * 100)}%（${Math.round(Number(locationMetrics.store_score))} 分）`
              : ""}
            {Number(locationMetrics.parking_component_weight) > 0
              ? ` · 停車 ${Math.round(Number(locationMetrics.parking_component_weight) * 100)}%（${Math.round(Number(locationMetrics.parking_score))} 分）`
              : ""}
          </span>
          <span>
            成本：NT$ {Number(costMetrics.estimated_monthly_cost).toLocaleString()}
            {" ÷ "}NT$ {Number(costMetrics.budget).toLocaleString()}
            {" = "}{Math.round(Number(costMetrics.cost_ratio) * 100)}%
          </span>
          <span>
            房屋：已知條件符合率 {propertyMetrics.known_match_rate}%
            {" · "}資料完整度 {propertyMetrics.data_completeness}%
          </span>
          <span>
            有效證據覆蓋原權重 {metrics.evidence_coverage_percent}%；未知資料不給中性分。
          </span>
        </div>
      </div>
    </details>
  );
}

const conditionSymbols = {
  met: "✓",
  unmet: "×",
  unknown: "?",
};

function PropertyConditionStrip({ assessment }) {
  const checks = (assessment?.checks || []).filter(
    (check) => check.status !== "not_required",
  );
  if (!checks.length) return null;
  return (
    <div className="condition-strip" aria-label="房屋條件核對">
      <strong>房屋條件</strong>
      {checks.map((check) => (
        <span
          className={`condition-chip ${check.status}`}
          key={check.label}
          title={check.evidence}
        >
          <i>{conditionSymbols[check.status]}</i>{check.label}
        </span>
      ))}
      <small>資料完整 {assessment.metrics.data_completeness}%</small>
    </div>
  );
}

function ResultCard({ item }) {
  const [open, setOpen] = useState(item.rank === 1);
  const [activeImage, setActiveImage] = useState(0);
  const p = item.property;
  const images = [...new Set([p.image_url, ...(p.image_urls || [])].filter(Boolean))].slice(0, 6).map(mediaUrl);
  const sourceLinks = (p.source_links?.length
    ? p.source_links
    : [{ name: p.source_name || "租屋平台", url: p.source_url }]
  ).filter((link) => link.url?.trim());
  const propertyAssessment = item.assessments.property;
  const qualificationStatus =
    item.assessments.suitability.metrics.qualification_status === "qualified"
      ? "qualified"
      : "needs_verification";
  const qualified = qualificationStatus === "qualified";
  return (
    <article className={`result-card ${item.rank === 1 && qualified ? "winner" : ""} ${qualificationStatus}`}>
      <div className="rank-badge">#{item.rank}</div>
      <div className="property-gallery">
        {images.length ? (
          <img loading="lazy" decoding="async" className="property-main-image" src={images[activeImage] || images[0]} alt={`${p.title} 房源照片 ${activeImage + 1}`} />
        ) : (
          <div className="property-image-placeholder">
            <Building2 size={52} strokeWidth={1.25} aria-hidden="true" />
            <strong>房源照片</strong>
            <span>尚未提供照片</span>
            {p.listing_area_ping && <small>{p.listing_area_ping} 坪 · NT$ {p.rent.toLocaleString()}／月</small>}
          </div>
        )}
        {images.length > 1 && (
          <div className="property-thumbnails" aria-label="房源照片">
            {images.map((image, index) => (
              <button
                type="button"
                className={index === activeImage ? "active" : ""}
                onClick={() => setActiveImage(index)}
                aria-label={`查看第 ${index + 1} 張房源照片`}
                aria-pressed={index === activeImage}
                key={image}
              >
                <img src={image} alt="" />
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="result-main">
        <div className="result-heading">
          <div>
            <div className="title-line">
              <h3>{p.title}</h3>
              {item.rank === 1 && qualified && <span className="best-tag"><Sparkles size={14} />首選</span>}
            </div>
            <p><MapPin size={15} />{p.address}</p>
          </div>
          <ScoreRing
            score={item.total_score}
            status={qualificationStatus}
          />
        </div>

        <div className="metrics-grid">
          <div>
            <span>預估月支出</span>
            <strong>NT$ {item.estimated_monthly_cost.toLocaleString()}</strong>
            {p.cost_estimated_by_ai && (
              <small>
                AI 依所在地與房型補估未揭露水電 · 可信度
                {p.cost_estimate_confidence === "high"
                  ? "高"
                  : p.cost_estimate_confidence === "medium" ? "中" : "低"}
              </small>
            )}
          </div>
          <div>
            <span>通勤時間</span>
            <strong>{p.commute_minutes ? `約 ${p.commute_minutes} 分鐘` : "地址無法定位"}</strong>
            {p.commute_method && (
              <small>
                {p.commute_method}
                {p.commute_transfers != null ? ` · 轉乘 ${p.commute_transfers} 次` : ""}
                {p.route_distance_km != null ? ` · ${p.route_distance_km} km` : ""}
              </small>
            )}
            {(p.transit_commute_minutes || p.driving_commute_minutes) && (
              <small>
                {p.transit_commute_minutes
                  ? `大眾運輸 ${p.transit_commute_minutes} 分`
                  : "大眾運輸未取得"}
                {" · "}
                {p.driving_commute_minutes
                  ? `駕車 ${p.driving_commute_minutes} 分`
                  : "駕車未取得"}
              </small>
            )}
          </div>
          <div>
            <span>窗戶</span><strong>{p.window_type}</strong>
            {p.vision_analyzed_by_ai && (
              <small>
                AI 圖片判讀 · 空間
                {{
                  spacious: "寬敞",
                  adequate: "適中",
                  compact: "緊湊",
                  unknown: "無法確認",
                }[p.space_impression]}
                {p.listing_area_ping ? ` · 刊登 ${p.listing_area_ping} 坪` : ""}
              </small>
            )}
          </div>
          <div>
            <span>樓層／電梯</span>
            <strong>
              {p.floor ? `${p.floor}F` : "未揭露"}／
              {p.has_elevator === true ? "有電梯" : p.has_elevator === false ? "無電梯" : "未揭露"}
            </strong>
          </div>
        </div>

        <PropertyConditionStrip assessment={propertyAssessment} />

        <p className="recommendation">{item.recommendation}</p>

        {sourceLinks.length > 0 && (
          <div className="property-source-links">
            {sourceLinks.map((link) => (
              <a
                className="property-source-link"
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                key={`${link.name}-${link.url}`}
              >
                查看 {link.name} 原始刊登 <ExternalLink size={15} />
              </a>
            ))}
          </div>
        )}

        <div className="pros-cons">
          <div>
            <h4><Check size={16} />主要優勢</h4>
            <ul>{item.strengths.slice(0, 3).map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
          <div>
            <h4><TriangleAlert size={16} />需要取捨</h4>
            <ul>{item.tradeoffs.slice(0, 3).map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        </div>
        <button className="detail-button" onClick={() => setOpen(!open)}>
          查看各 Agent 分析 {open ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
        </button>

        {open && (
          <div className="assessment-list">
            {Object.values(item.assessments).map((assessment) => (
              <div className="assessment" key={assessment.agent}>
                <div>
                  <strong>
                    {assessment.agent}
                    {assessment.metrics.ai_used && " · OpenAI"}
                  </strong>
                  <span>{assessment.summary}</span>
                  <AssessmentCalculation
                    assessment={assessment}
                    assessments={item.assessments}
                  />
                  {assessment.agent === "Suitability Agent" && (
                    <ScoreBreakdown item={item} />
                  )}
                  {!!assessment.checks?.length && (
                    <div className="condition-evidence">
                      {assessment.checks
                        .filter((check) => check.status !== "not_required")
                        .map((check) => (
                          <span className={check.status} key={check.label}>
                            <i>{conditionSymbols[check.status]}</i>
                            <span>
                              <strong>{check.label}</strong>
                              <small>{check.evidence}</small>
                            </span>
                          </span>
                        ))}
                    </div>
                  )}
                </div>
                {assessment.agent === "Property Agent" ? (
                <b className="condition-count">
                    {assessment.metrics.met_count} 項符合
                    {" · "}資料 {assessment.metrics.data_completeness}%
                </b>
                ) : assessment.agent === "Suitability Agent"
                  && assessment.metrics.qualification_status !== "qualified" ? (
                  <b className="assessment-unknown">待確認</b>
                ) : assessment.metrics.score_available === false ? (
                  <b className="assessment-unknown">待確認</b>
                ) : (
                  <b>{Math.round(assessment.score)}</b>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [preferenceText, setPreferenceText] = useState(initialForm.preferences.join("、"));
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState("ranking");
  const [mapContext, setMapContext] = useState(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState("");
  const [requirementText, setRequirementText] = useState("");
  const [requirementLoading, setRequirementLoading] = useState(false);
  const [requirementResult, setRequirementResult] = useState(null);
  const [requirementError, setRequirementError] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [destinationResolution, setDestinationResolution] = useState(null);
  const [destinationResolving, setDestinationResolving] = useState(false);
  const [destinationError, setDestinationError] = useState("");
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [weightLocks, setWeightLocks] = useState(
    Object.fromEntries(weightNames.map((name) => [name, false])),
  );

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    const query = form.destination.trim();
    if (!query) {
      setDestinationResolution(null);
      setDestinationError("");
      setDestinationResolving(false);
      return undefined;
    }
    if (["台灣大學", "國立台灣大學", "台大"].includes(query.replaceAll("臺", "台"))) {
      setDestinationResolution(NTU_DESTINATION);
      setDestinationError("");
      setDestinationResolving(false);
      return undefined;
    }
    const controller = new AbortController();
    setDestinationResolving(true);
    setDestinationError("");
    setDestinationResolution(null);
    const timer = window.setTimeout(async () => {
      try {
        const resolved = await resolveDestination(query, controller.signal);
        setDestinationResolution(resolved);
      } catch (err) {
        if (err.name !== "AbortError") {
          setDestinationError(err.message || "無法辨識這個目的地");
        }
      } finally {
        if (!controller.signal.aborted) setDestinationResolving(false);
      }
    }, 650);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [form.destination]);

  const modeLabel = useMemo(() => {
    if (data?.mode === "ai") return "OpenAI";
    if (!data && health?.openai_enabled) return "OpenAI ready";
    return "Rules";
  }, [data, health]);
  const normalizedWeights = useMemo(() => {
    const total = Object.values(form.weights).reduce(
      (sum, value) => sum + Number(value),
      0,
    );
    return Object.fromEntries(
      Object.entries(form.weights).map(([name, value]) => [
        name,
        total ? Math.round(Number(value) / total * 100) : 0,
      ]),
    );
  }, [form.weights]);
  const topPriority = useMemo(
    () => Object.entries(normalizedWeights).sort((a, b) => b[1] - a[1])[0],
    [normalizedWeights],
  );
  const inheritedFields = useMemo(() => {
    if (!requirementResult) return [];
    const updated = new Set(requirementResult.updated_fields || []);
    return ["destination", "budget", "max_commute_minutes"]
      .filter((name) => !updated.has(name))
      .map((name) => requirementFieldLabels[name]);
  }, [requirementResult]);
  const displayPreferences = useMemo(
    () => preferenceText
      .split(/[、,，]/)
      .map((value) => value.trim())
      .filter(Boolean),
    [preferenceText],
  );

  function update(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function updateWeight(name, value) {
    setForm((current) => {
      const weights = rebalanceWeights(current.weights, name, value, weightLocks);
      return { ...current, weights };
    });
  }

  function toggleWeightLock(name) {
    setWeightLocks((current) => ({ ...current, [name]: !current[name] }));
  }

  function togglePetPreference(checked) {
    setPreferenceText((current) => {
      const preferences = current.split(/[、,，]/).map((value) => value.trim()).filter(Boolean);
      return setPetPreference(preferences, checked).join("、");
    });
    // Keep an applied AI parse marked as applied, so submit respects this edit
    // instead of re-parsing the original text and restoring the pet requirement.
  }

  async function applyNaturalLanguageRequirements() {
    setRequirementLoading(true);
    setRequirementError("");
    setRequirementResult(null);
    try {
      const current = {
        ...form,
        property_source: "mock",
        budget: Number(form.budget),
        max_commute_minutes: Number(form.max_commute_minutes),
        max_floor_without_elevator: Number(form.max_floor_without_elevator),
        preferences: preferenceText
          .split(/[、,，]/)
          .map((value) => value.trim())
          .filter(Boolean),
      };
      const result = await parseRequirements(requirementText, current);
      setForm({
        ...result.requirements,
        property_source: "mock",
        weights: normalizeWeights(result.requirements.weights),
      });
      setPreferenceText(result.requirements.preferences.join("、"));
      setRequirementResult(result);
      setAdvancedOpen(false);
    } catch (err) {
      setRequirementError(err.message || "Requirement Agent 無法解析需求。");
    } finally {
      setRequirementLoading(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setData(null);
    setPage("ranking");
    setMapContext(null);
    setMapError("");
    setFeedbackMessage("");
    try {
      const payload = {
        ...form,
        property_source: "mock",
        requirement_text: requirementText.trim(),
        requirements_parsed: Boolean(requirementResult),
        destination_resolved_address:
          destinationResolution?.resolved_address || "",
        destination_latitude: destinationResolution?.latitude ?? null,
        destination_longitude: destinationResolution?.longitude ?? null,
        budget: Number(form.budget),
        max_commute_minutes: Number(form.max_commute_minutes),
        max_floor_without_elevator: Number(form.max_floor_without_elevator),
        preferences: preferenceText.split(/[、,，]/).map((x) => x.trim()).filter(Boolean),
      };
      const result = await getRecommendation(payload);
      setData(result);
      window.setTimeout(() => {
        document.getElementById("ranked-results")?.scrollIntoView({ behavior: "smooth" });
      }, 0);
    } catch (err) {
      setError(err.message || "分析失敗：請確認 FastAPI 已在 8000 port 啟動。");
    } finally {
      setLoading(false);
    }
  }

  async function submitRecommendationFeedback(accepted) {
    if (!data?.thread_id) return;
    setFeedbackLoading(true);
    setFeedbackMessage("");
    try {
      const feedback = {
        accepted,
        weights: accepted ? null : normalizeWeights(form.weights),
      };
      const result = await sendRecommendationFeedback(data.thread_id, feedback);
      setData(result);
      setMapContext(null);
      setFeedbackMessage(
        accepted
          ? "已確認這份推薦，LangGraph 流程完成。"
          : "已更新 State 與權重，並在保留分析結果的情況下重新排序。",
      );
      if (!accepted) {
        window.setTimeout(() => {
          document.getElementById("ranked-results")?.scrollIntoView({
            behavior: "smooth",
          });
        }, 0);
      }
    } catch (err) {
      setFeedbackMessage(err.message || "目前無法送出推薦回饋。");
    } finally {
      setFeedbackLoading(false);
    }
  }

  async function openMap() {
    setPage("map");
    if (mapContext || !data?.results.length) return;
    setMapLoading(true);
    setMapError("");
    try {
      const context = await getMapContext({
        destination: form.destination,
        destination_address:
          destinationResolution?.resolved_address || "",
        region_name: destinationResolution?.region_name || "",
        destination_latitude: destinationResolution?.latitude ?? null,
        destination_longitude: destinationResolution?.longitude ?? null,
        properties: data.results.slice(0, 6).map((item) => ({
          id: item.property.id,
          title: item.property.title,
          address: item.property.address,
          score: item.total_score,
          source_url: item.property.source_url || "",
          latitude: item.property.latitude,
          longitude: item.property.longitude,
          nearby_convenience_stores: item.property.nearby_convenience_stores || [],
          convenience_store_lookup_completed:
            item.property.convenience_store_lookup_completed || false,
          nearby_parking_facilities: item.property.nearby_parking_facilities || [],
          parking_lookup_completed: item.property.parking_lookup_completed || false,
        })),
      });
      setMapContext(context);
    } catch (err) {
      setMapError(err.message || "地圖服務暫時無法使用。");
    } finally {
      setMapLoading(false);
    }
  }

  return (
    <main>
      <header className="hero">
        <nav>
          <div className="brand"><div><Home size={21} /></div><strong>RentWise</strong></div>
          <div className="nav-actions">
            <span className="mode-badge"><span />{modeLabel}</span>
          </div>
        </nav>
        <div className="hero-copy">
          <span className="eyebrow">MULTI-AGENT RENTAL DECISION PLATFORM</span>
          <h1>
            <span className="hero-title-line">不僅幫你找房，</span>
            <span className="hero-title-line">
              且幫你做出<span>更好的租屋<span className="hero-no-break">決策。</span></span>
            </span>
          </h1>
          <p>多個 AI Agent 分別分析地點、成本、房況與生活偏好，再共同完成跨房源比較。</p>
        </div>
      </header>

      <div className="app-shell">
        {page === "map" && data ? (
          <MapView
            context={mapContext}
            loading={mapLoading}
            error={mapError}
            destinationName={form.destination}
            onBack={() => setPage("ranking")}
          />
        ) : (
          <>
        <form className="panel form-panel" onSubmit={submit}>
          <div className="section-title">
            <div>
              <span className="eyebrow">YOUR REQUIREMENTS</span>
              <h2>設定租屋需求</h2>
            </div>
            <Route size={24} />
          </div>

          <div className="requirement-agent">
            <div className="requirement-agent-heading">
              <div className="requirement-agent-icon"><Bot size={18} /></div>
              <div>
                <strong>Requirement Agent</strong>
                <span>用一句話描述需求，AI 會填入條件與建議權重</span>
              </div>
              <b>OpenAI</b>
            </div>
            <div className="requirement-agent-input">
              <textarea
                value={requirementText}
                onChange={(event) => {
                  setRequirementText(event.target.value);
                  setRequirementResult(null);
                }}
                placeholder="例如：我在政大上課，預算一萬五，25 分鐘內到，要能養貓、可開伙、有對外窗，希望安靜。"
                rows="3"
              />
              <button
                type="button"
                onClick={applyNaturalLanguageRequirements}
                disabled={
                  requirementLoading
                  || requirementText.trim().length < 3
                  || !health?.openai_enabled
                }
              >
                {requirementLoading
                  ? <><LoaderCircle className="spin" size={17} />解析中</>
                  : <><Sparkles size={17} />套用需求</>}
              </button>
            </div>
            {!health?.openai_enabled && health && (
              <small className="requirement-hint">
                後端尚未設定 OPENAI_API_KEY，仍可直接使用下方表單。
              </small>
            )}
            {requirementResult && (
              <div className="requirement-success">
                <Check size={16} />
                <span>
                  <strong>{requirementResult.interpretation}</strong>
                  {!!requirementResult.assumptions.length && (
                    <small>
                      待確認：{requirementResult.assumptions.join("、")}
                    </small>
                  )}
                </span>
              </div>
            )}
            {requirementError && (
              <small className="requirement-error">{requirementError}</small>
            )}
          </div>

          <div className={`requirements-overview ${requirementResult ? "ai-applied" : ""}`}>
            <div className="overview-heading">
              <div>
                <strong>
                  {requirementResult ? "AI 已整理需求" : "目前分析條件"}
                </strong>
                <span>確認摘要後可直接開始分析</span>
              </div>
              {requirementResult && <b><Check size={13} />已套用</b>}
            </div>
            <div className="overview-grid">
              <div>
                <span>目的地</span>
                <strong>
                  {destinationResolution?.resolved_label || form.destination}
                </strong>
              </div>
              <div><span>總預算</span><strong>NT$ {Number(form.budget).toLocaleString()}</strong></div>
              <div><span>通勤上限</span><strong>{form.max_commute_minutes} 分鐘</strong></div>
              <div>
                <span>最重視</span>
                <strong>{weightLabels[topPriority?.[0]]} {topPriority?.[1]}%</strong>
              </div>
            </div>
            <div className="overview-conditions">
              <span>
                {form.commute_mode === "drive"
                  ? "主要以汽車通勤"
                  : "主要以大眾運輸／步行通勤"}
              </span>
              {form.needs_window && <span>需要對外窗</span>}
              {form.needs_elevator && <span>需要電梯</span>}
              {form.needs_parking && <span>需要停車</span>}
              {form.needs_rental_subsidy && <span>需要可申請租補</span>}
              {form.needs_convenience_store && <span>附近要有超商</span>}
              {form.noise_preference === "quiet" && <span>希望安靜</span>}
              {displayPreferences.map((preference) => (
                <span key={preference}>{preference}</span>
              ))}
            </div>
            {!!inheritedFields.length && (
              <p className="inherited-note">
                <TriangleAlert size={14} />
                文字中未提到 {inheritedFields.join("、")}，目前沿用原設定。
              </p>
            )}
          </div>

          <button
            type="button"
            className="advanced-toggle"
            onClick={() => setAdvancedOpen((open) => !open)}
            aria-expanded={advancedOpen}
          >
            <span>
              <strong>調整詳細條件</strong>
              <small>預算、寵物、設備、樓層與適配權重</small>
            </span>
            {advancedOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>

          {advancedOpen && (
          <div className="advanced-settings">
          <div className="form-grid">
            <Field label="每月總預算" hint="包含管理費與預估水電">
              <div className="input-prefix"><span>NT$</span><input type="number" value={form.budget} onChange={(e) => update("budget", e.target.value)} /></div>
            </Field>
            <Field label="通勤目的地" hint="預設為政大；房源位於台大周邊，到其他目的地的通勤會重新計算">
              <input value={form.destination} onChange={(e) => update("destination", e.target.value)} />
              {destinationResolving && (
                <span className="destination-resolution loading">
                  <LoaderCircle className="spin" size={13} />
                  正在確認具體位置…
                </span>
              )}
              {!destinationResolving && destinationResolution && (
                <span className="destination-resolution resolved">
                  <MapPin size={13} />
                  已辨識：{destinationResolution.resolved_label}
                  <small>
                    {destinationResolution.source === "openstreetmap"
                      ? "OpenStreetMap 實際座標"
                      : destinationResolution.source === "demo_landmark"
                        ? "台大校區參考座標"
                        : "行政區規則"}
                  </small>
                </span>
              )}
              {!destinationResolving && destinationError && (
                <span className="destination-resolution unresolved">
                  <TriangleAlert size={13} />
                  {destinationError}
                </span>
              )}
            </Field>
            <Field
              label="最長大眾運輸／步行時間"
              hint="依預估通勤時間比較房源"
            >
              <div className="input-suffix"><input type="number" value={form.max_commute_minutes} onChange={(e) => update("max_commute_minutes", e.target.value)} /><span>分鐘</span></div>
            </Field>
            <Field label="安靜程度">
              <select value={form.noise_preference} onChange={(e) => update("noise_preference", e.target.value)}>
                <option value="quiet">希望安靜</option>
                <option value="balanced">可接受一般環境聲</option>
                <option value="no_preference">沒有偏好</option>
              </select>
            </Field>
            <Field
              label="主要通勤方式"
              hint="比較大眾運輸／步行或駕車所需時間"
            >
              <select
                value={form.commute_mode}
                onChange={(e) => update("commute_mode", e.target.value)}
              >
                <option value="transit_walk">大眾運輸／步行</option>
                <option value="drive">汽車駕駛</option>
              </select>
            </Field>
          </div>

          <div className="toggle-grid">
            <Toggle checked={displayPreferences.some(isPetPreference)} onChange={togglePetPreference} label="需要可養寵物" />
            <Toggle checked={form.needs_window} onChange={(v) => update("needs_window", v)} label="需要對外窗" />
            <Toggle checked={form.needs_elevator} onChange={(v) => update("needs_elevator", v)} label="一定要有電梯" />
            <Toggle checked={form.needs_convenience_store} onChange={(v) => update("needs_convenience_store", v)} label="附近需有便利商店" />
            <Toggle checked={form.needs_parking} onChange={(v) => update("needs_parking", v)} label="需要附近停車場" />
            <Toggle
              checked={form.needs_rental_subsidy}
              onChange={(v) => update("needs_rental_subsidy", v)}
              label="需要可申請租金補貼"
            />
          </div>

          <div className="weights-card">
            <div className="weights-heading">
              <div>
                <strong>你最在意什麼？</strong>
                <span>鎖住不想變動的項目；調整其他項目時，未鎖權重會自動補足 100%</span>
              </div>
              <b>自訂適配分</b>
            </div>
            <div className="weights-grid">
              {Object.keys(weightLabels).map((name) => (
                <WeightControl
                  key={name}
                  name={name}
                  value={form.weights[name]}
                  locked={weightLocks[name]}
                  max={100 - weightNames
                    .filter((other) => other !== name && weightLocks[other])
                    .reduce((sum, other) => sum + Number(form.weights[other]), 0)}
                  onChange={updateWeight}
                  onToggleLock={toggleWeightLock}
                />
              ))}
            </div>
          </div>

          <div className="form-grid">
            <Field label="無電梯可接受最高樓層">
              <div className="input-suffix"><input type="number" value={form.max_floor_without_elevator} onChange={(e) => update("max_floor_without_elevator", e.target.value)} /><span>樓</span></div>
            </Field>
            <Field label="其他偏好" hint="使用頓號或逗號分隔；可填可養貓、可開伙、隔音良好等">
              <input value={preferenceText} onChange={(e) => setPreferenceText(e.target.value)} placeholder="採光良好、可開伙、可養寵物" />
            </Field>
          </div>
          </div>
          )}

          <button className="submit-button" disabled={loading}>
            {loading ? <><LoaderCircle className="spin" size={20} />Agents 分析中...</> : <><Sparkles size={20} />啟動 Multi-Agent 分析</>}
          </button>
          <div className="listing-source">
            <div>
              <strong>依需求挑選前 10 筆房源</strong>
              <span>調整寵物、開伙、預算與設備需求，系統會分析所有候選房源，依符合程度推薦前 10 筆。</span>
            </div>
          </div>
          {error && <p className="error">{error}</p>}
        </form>

        <AgentPipeline trace={data?.trace} loading={loading} />

        {data?.results?.length > 0 && (
          <section className="results-section" id="ranked-results">
            <div className="decision-summary">
              <div className="summary-icon"><Bot size={26} /></div>
              <div className="decision-summary-content">
                <span className="eyebrow">DECISION EXPLANATION AGENT</span>
                <h2>最終決策摘要</h2>
                <p>{data.summary}</p>
                {data.awaiting_feedback && (
                  <div className="recommendation-feedback">
                    <strong>這份推薦符合你的偏好嗎？</strong>
                    <div className="feedback-controls">
                      <div className="feedback-weights">
                        {weightNames.map((name) => (
                          <WeightControl
                            key={name}
                            name={name}
                            value={form.weights[name]}
                            locked={weightLocks[name]}
                            max={100 - weightNames
                              .filter((other) => other !== name && weightLocks[other])
                              .reduce((sum, other) => sum + Number(form.weights[other]), 0)}
                            onChange={updateWeight}
                            onToggleLock={toggleWeightLock}
                          />
                        ))}
                      </div>
                      <div className="feedback-buttons">
                        <button
                          type="button"
                          onClick={() => submitRecommendationFeedback(false)}
                          disabled={feedbackLoading}
                        >
                          套用權重重新排序
                        </button>
                        <button
                          type="button"
                          className="feedback-accept"
                          onClick={() => submitRecommendationFeedback(true)}
                          disabled={feedbackLoading}
                        >
                          <Check size={15} /> 符合，完成
                        </button>
                      </div>
                    </div>
                    <small>
                      重新排序會從 Suitability Agent 繼續，不會重新搜尋或重跑圖片分析。
                    </small>
                  </div>
                )}
                {feedbackMessage && <div className="feedback-message">{feedbackMessage}</div>}
              </div>
            </div>
            <div className="results-heading">
              <div>
                <span className="eyebrow">RANKED RESULTS</span>
                <h2>
                  房源推薦排名
                </h2>
              </div>
              <div className="results-actions">
                <span>推薦前 {data.results.length} 筆房源</span>
                <button type="button" className="map-button" onClick={openMap}>
                  <MapPinned size={18} /> 查看地圖與超商
                </button>
              </div>
            </div>
            <div className="results-list">
              {data.results.map((item) => <ResultCard item={item} key={item.property.id} />)}
            </div>
          </section>
        )}

        {!data && !loading && (
          <section className="empty-state">
            <Clock3 size={30} />
            <h3>Agent 團隊正在待命</h3>
            <p>設定需求後啟動分析，系統會同步展示每個 Agent 的分工與最終排名。</p>
          </section>
        )}
          </>
        )}
      </div>
      <footer>RentWise · 智慧租屋決策</footer>
    </main>
  );
}
