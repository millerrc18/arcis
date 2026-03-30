/**
 * Roadmap page — Halcyon Lab development and scaling roadmap.
 * MAINTAINER NOTE: Update ROADMAP_DATA below when the roadmap changes. UI renders from this data.
 * Last updated: 2026-03-27
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Circle, Loader2, ChevronDown, ChevronRight, Lock, Info, Cpu, DollarSign, Calendar } from 'lucide-react'
import RevenueProjection from '../components/RevenueProjection'
import { api } from '../api'

const CAT = {
  strategy:   { label: 'Strategy',      color: '#2DD4BF' },
  ai:         { label: 'AI & training', color: '#7F77DD' },
  data:       { label: 'Data',          color: '#378ADD' },
  risk:       { label: 'Risk',          color: '#D85A30' },
  ops:        { label: 'Operations',    color: '#1D9E75' },
  validation: { label: 'Validation',    color: '#EF9F27' },
  legal:      { label: 'Legal & tax',   color: '#D4537E' },
  hardware:   { label: 'Hardware',      color: '#888780' },
}

const ROADMAP_DATA = {
  lastUpdated: '2026-03-27',
  phases: [
    { id: 'p1', name: 'Phase 1 — Bootcamp', status: 'active', capital: '$100K paper + $100 live', cost: '$64/mo', timeline: 'Apr–Jun 2026',
      desc: 'Prove the system has an edge. Accumulate 50+ closed trades. Build foundational infrastructure.',
      gate: { label: '50+ closed trades, positive expectancy across 6 metrics', metrics: [
        { key: 'trades_closed', label: 'Closed trades', target: 50, op: '>=', fmt: '' },
        { key: 'win_rate', label: 'Win rate', target: 0.45, op: '>=', fmt: 'pct' },
        { key: 'profit_factor', label: 'Profit factor', target: 1.3, op: '>=' },
        { key: 'expectancy_dollars', label: 'Expectancy', target: 0, op: '>', fmt: 'dollar' },
        { key: 'max_drawdown_pct', label: 'Max drawdown', target: 12, op: '<=', fmt: 'pctVal' },
        { key: 'sharpe_ratio', label: 'Per-trade Sharpe', target: 0.15, op: '>=' },
      ]},
      subphases: [
        { label: 'Weeks 1–2: Core system', items: [
          { l: '7-source data enrichment', s: 'done', c: 'data', d: 'Technicals, fundamentals, insider, macro, news, regime, sector — every trade packet sees 7 independent data sources.', r: 'Alternative Data Signals research' },
          { l: 'Bracket orders via Alpaca', s: 'done', c: 'strategy', d: 'Every position gets a stop-loss + take-profit bracket order (GTC). Protected even if system goes offline.', r: 'Risk Management: "protects against all outage scenarios"' },
          { l: 'Risk governor (8 hard limits)', s: 'done', c: 'risk', d: 'Position size, sector concentration, daily loss, drawdown, correlation, and more.', r: 'Risk Management: 8 institutional-grade risk controls' },
          { l: 'Self-blinding training pipeline', s: 'done', c: 'ai', d: 'Architectural temporal firewall — model never sees outcomes during training. Prevents look-ahead bias.', r: 'Prompt Engineering: "instruction-based approaches fail"' },
          { l: 'XML output format', s: 'done', c: 'ai', d: 'Structured <why_now>, <analysis>, <metadata> tags. Validated by Trading-R1 (Sharpe 2.72).', r: 'Optimal Training Formats: Trading-R1 (Tauric, Sep 2025)' },
          { l: 'Curriculum SFT (3-stage)', s: 'done', c: 'ai', d: 'Structure → Evidence → Decision with decreasing learning rates (3e-4 → 2e-4 → 1e-4).', r: 'Training Data Strategies' },
        ]},
        { label: 'Weeks 3–4: Quality & validation', items: [
          { l: 'Quality pipeline + LLM-as-judge', s: 'done', c: 'ai', d: 'Claude scores every example on 8-dimension rubric. Bottom 15% pruned. Golden ratio 62/38.', r: 'Gold-Standard Rubric' },
          { l: 'Leakage detector', s: 'done', c: 'validation', d: 'TF-IDF balanced accuracy. If >65%, the pipeline is leaking future information.', r: 'Training Data Strategies' },
          { l: 'Walk-forward backtesting', s: 'done', c: 'validation', d: 'Train on past, test on future. The only honest way to evaluate a trading model.', r: 'Walk-Forward Validation: Lopez de Prado AFML' },
          { l: 'Auditor agent (daily + weekly)', s: 'done', c: 'ops', d: 'Automated daily health check + weekly deep audit. Telegram alerts on yellow/red.', r: 'Risk Management: "50% of hedge fund failures are operational"' },
          { l: 'Process-first quality rubric', s: 'done', c: 'ai', d: 'Scores PROCESS not outcome. "Good process / bad outcome" deliberately upweighted.', r: 'Gold-Standard Rubric' },
          { l: 'Backfill cleanup (969 examples)', s: 'done', c: 'ai', d: '704 backfill + 194 blinded_win + 77 blinded_loss. All cleaned to XML. 100% parse rate.', r: 'Training data audit' },
        ]},
        { label: 'Weeks 5–8: Infrastructure', items: [
          { l: 'Cloud dashboard (halcyonlab.app)', s: 'done', c: 'ops', d: '13 pages, 52+ cloud API endpoints, Render deployment, PWA support.', r: 'Arcis brand identity (pending)' },
          { l: '24/7 overnight schedule (27 events)', s: 'done', c: 'ops', d: 'Pre-market brief 6AM, scans every 30min, EOD 4PM, 12 collectors, Saturday retrain.', r: 'Halcyon Framework: 75% GPU target' },
          { l: 'AI Council (5 agents)', s: 'done', c: 'ai', d: 'Bull, Bear, Quant, Macro, Risk agents via Claude Sonnet. Modified Delphi. ~$0.50/session.', r: 'AI Council research' },
          { l: 'Research collector (#13)', s: 'done', c: 'data', d: '7 sources: arXiv, SSRN, HuggingFace, Reddit, GitHub, AI blogs, SEC/FINRA. Weekly synthesis.', r: 'Research flywheel' },
          { l: 'Statistical validation (PSR, bootstrap)', s: 'done', c: 'validation', d: 'PSR, DSR, bootstrap Sharpe CIs, MinTRL, win rate test, expectancy test.', r: 'Walk-Forward: Lo 2002, Bailey & López de Prado 2014' },
          { l: '50-trade gate evaluator', s: 'done', c: 'validation', d: 'Automated PASS/FAIL: 4+ GREEN with 0 RED → proceed. Mixed → extend. RED → root cause.', r: 'Walk-Forward Validation' },
        ]},
        { label: 'Weeks 8–12: Risk & NLP', items: [
          { l: 'Thorp graduated drawdown', s: 'done', c: 'risk', d: 'Linear reduction 100%→0% from 0%→20% drawdown. Ed Thorp protocol.', r: 'Risk Management: Ed Thorp, Hedge Fund Market Wizards' },
          { l: 'SEC EDGAR NLP features', s: 'done', c: 'data', d: 'L-M dictionary sentiment + 17 cautionary phrases. CPU-only, milliseconds per filing.', r: 'SEC EDGAR research' },
          { l: 'Tech-fundamental divergence', s: 'done', c: 'strategy', d: 'Improving fundamentals + pullback = high conviction. Most novel feature for pullback strategy.', r: 'SEC EDGAR: "most novel feature"' },
          { l: 'LLM output validation', s: 'done', c: 'risk', d: 'Hard bounds: ticker in universe, price ±10%, stop below entry, allocation ≤5%.', r: 'Risk Management: "LLM hallucination ~4% rate"' },
          { l: 'SQLite WAL + backups', s: 'done', c: 'ops', d: 'WAL mode, busy_timeout 5000ms, daily backup. Prevents data loss.', r: 'Risk Management' },
          { l: 'Revenue projection model', s: 'done', c: 'ops', d: '3 scenarios + live mode. Locks to actual Sharpe at 20+ trades.', r: 'Research synthesis' },
          { l: 'Score + retrain halcyon-v1', s: 'in-progress', c: 'ai', d: 'Quality score 969 examples, prune bottom 15%, retrain with curriculum. First Saturday retrain.', r: 'Training data audit' },
        ]},
      ],
    },
    { id: 'p2', name: 'Phase 2 — Micro live + LLC', status: 'locked', capital: '$100 → $1,000 live', cost: '$125/mo', timeline: 'Jul–Sep 2026',
      desc: 'Validate edge with real money. Form legal entity. Random benchmark for statistical proof. Scale to 100+ trades.',
      gate: { label: '100+ trades, PSR >90%, paper-live concordance passes', metrics: [
        { key: 'win_rate', label: 'Win rate', target: 0.43, op: '>=', fmt: 'pct' },
        { key: 'profit_factor', label: 'Profit factor', target: 1.4, op: '>=' },
        { key: 'sharpe_ratio', label: 'Sharpe', target: 1.0, op: '>=' },
        { key: 'psr', label: 'PSR(0)', target: 0.90, op: '>=', fmt: 'pct' },
        { key: 'max_drawdown_pct', label: 'Max DD', target: 15, op: '<=', fmt: 'pctVal' },
        { key: 'calmar', label: 'Calmar', target: 1.0, op: '>=' },
      ]},
      subphases: [
        { label: 'Month 1: Legal + data', items: [
          { l: 'Form Wyoming LLC ($100 + $60/yr)', s: 'pending', c: 'legal', d: 'Liability protection, ring-fence trading. No state income tax, strong privacy.', r: 'LLC research: "Wyoming is optimal"' },
          { l: 'Section 475 MTM election (75-day deadline)', s: 'pending', c: 'legal', d: 'Mark-to-market accounting. Deduct losses against ordinary income. Irreversible deadline.', r: 'LLC research' },
          { l: 'Polygon.io Starter ($29/mo)', s: 'pending', c: 'data', d: 'Replace yfinance. Reliable EOD data for S&P 500. yfinance as fallback.', r: 'Data Infrastructure Audit' },
          { l: 'CPA for trader taxation ($500-2K)', s: 'pending', c: 'legal', d: 'Quarterly estimates, business expense deductions, Section 475 review.', r: 'LLC research' },
          { l: 'Random-entry benchmark (Account #2)', s: 'pending', c: 'validation', d: 'Random stock + same exits = strongest proof of model value-add.', r: 'Walk-Forward: "single most informative test"' },
        ]},
        { label: 'Month 2: Scaling + risk', items: [
          { l: 'Universe expansion (103 → ~325)', s: 'pending', c: 'strategy', d: 'Filtered S&P 500. More opportunities, faster accumulation.', r: 'Universe research' },
          { l: 'Research Analyst desk (Account #3)', s: 'pending', c: 'ai', d: 'Relaxed thresholds, 3-5x more training data, tagged "research_desk".', r: 'Multi-desk architecture' },
          { l: 'Parametric VaR (Ledoit-Wolf)', s: 'pending', c: 'risk', d: 'Daily portfolio risk. Shrinkage covariance for 50-asset estimation.', r: 'Risk Management: Ledoit & Wolf (2004)' },
          { l: 'Correlation-adjusted sizing', s: 'pending', c: 'risk', d: 'Sliding scale: <0.3=100%, 0.3-0.5=75%, 0.5-0.7=50%, >0.7=25%.', r: 'Risk Management' },
          { l: '7-scenario stress testing', s: 'pending', c: 'risk', d: 'GFC, China, Q4 2018, COVID, 2022 bear, yen unwind, Liberation Day. Nightly.', r: 'Risk Management' },
        ]},
        { label: 'Month 3: Validation + hardware', items: [
          { l: 'Paper-to-live concordance testing', s: 'pending', c: 'validation', d: 'KS test on P&L distributions. Must pass before scaling beyond $1K.', r: 'Walk-Forward Validation' },
          { l: 'Scale training data to 3,000+', s: 'pending', c: 'ai', d: 'PASS examples, DPO pairs, regime-diverse synthetic. Cap synthetic at ~2,500.', r: 'Perplexity: "3,000-3,500 by end of Phase 2"' },
          { l: 'Scale live $100 → $1,000', s: 'pending', c: 'strategy', d: '100+ live trades, PSR >90%, DD <15%, no paper-live divergence.', r: 'Scaling Plan' },
          { l: 'Dedicated Halcyon machine (~$1,500)', s: 'pending', c: 'hardware', d: 'RTX 3090, Ryzen 5, 32GB RAM, UPS. 24/7 uninterrupted. Unlocks 14B + GRPO.', r: 'GRPO research' },
          { l: 'Dead man\'s switch (Raspberry Pi)', s: 'pending', c: 'risk', d: 'Independent watchdog. Stale >4hr = stop trades. Stale >48hr = flatten.', r: 'Risk Management' },
        ]},
      ],
    },
    { id: 'p3', name: 'Phase 3 — Growth + breakout', status: 'locked', capital: '$1K → $5K live', cost: '$155/mo', timeline: 'Oct 2026 – Mar 2027',
      desc: 'Launch breakout strategy on paper. Scale capital. Hit 200+ trades for moderate edge detection.',
      gate: { label: 'Sharpe ≥1.0, PSR ≥95%, positive in 2+ regimes', metrics: [
        { key: 'sharpe_ratio', label: 'Sharpe', target: 1.0, op: '>=' },
        { key: 'psr', label: 'PSR(0)', target: 0.95, op: '>=', fmt: 'pct' },
        { key: 'profit_factor', label: 'Profit factor', target: 1.5, op: '>=' },
        { key: 'ir', label: 'IR vs SPY', target: 0.4, op: '>=' },
      ]},
      subphases: [
        { label: 'Months 1–3: Breakout R&D', items: [
          { l: 'Breakout indicators (BB squeeze, ADX, volume)', s: 'pending', c: 'strategy', d: 'BB squeeze + volume ≥1.5× + close above + ADX >25.', r: 'Breakout Spec' },
          { l: 'Breakout paper trading + labeling', s: 'pending', c: 'strategy', d: 'Triple-barrier labeling. 300-500 labeled setups needed.', r: 'Breakout research' },
          { l: 'Separate breakout LoRA adapter', s: 'pending', c: 'ai', d: 'Independent LoRA, hot-swap based on classifier. MeteoRA confirms separate > multi-task.', r: 'Training research' },
          { l: 'GRPO training experiments', s: 'pending', c: 'ai', d: 'Group Relative Policy Optimization. Needs RTX 3090 + 100+ closed trades.', r: 'GRPO research' },
        ]},
        { label: 'Months 3–6: Validation + scaling', items: [
          { l: 'Fama-French factor exposure', s: 'pending', c: 'risk', d: 'Detect hidden tilts: market, size, value, momentum, profitability.', r: 'Risk Management' },
          { l: 'Series 65 exam study (40-80 hrs)', s: 'pending', c: 'legal', d: '$187 fee. Required before taking outside capital.', r: 'Risk Management' },
          { l: 'Options data collection ($50/mo)', s: 'pending', c: 'data', d: 'Unusual Whales. Passive collection for Phase 4 options desk.', r: 'Options research' },
          { l: 'Scale live $1K → $5K', s: 'pending', c: 'strategy', d: '100-150 more trades. PSR >90%, Sharpe >0.2, DD <20%.', r: 'Walk-Forward Validation' },
        ]},
      ],
    },
    { id: 'p4', name: 'Phase 4 — Full autonomous', status: 'locked', capital: '$5K → $25K live', cost: '$220/mo', timeline: 'Apr–Sep 2027',
      desc: 'Dual-strategy live. Options desk research. 500-trade institutional validation.',
      gate: { label: 'DSR >0.95, PSR ≥99%, 500+ trades', metrics: [
        { key: 'sharpe_ratio', label: 'Sharpe', target: 1.0, op: '>=' },
        { key: 'psr', label: 'PSR(0)', target: 0.99, op: '>=', fmt: 'pct' },
        { key: 'dsr', label: 'Deflated Sharpe', target: 0.95, op: '>=' },
        { key: 'max_drawdown_pct', label: 'Max DD', target: 20, op: '<=', fmt: 'pctVal' },
      ]},
      subphases: [
        { label: 'Multi-strategy + options', items: [
          { l: 'Breakout strategy live', s: 'pending', c: 'strategy', d: 'Combined portfolio: pullback + breakout. Correlation monitoring between strategies.', r: 'Breakout research' },
          { l: 'Options desk research', s: 'pending', c: 'strategy', d: 'Credit spreads, Greeks, IV analysis. Backtest with Unusual Whales data.', r: 'Options research' },
          { l: 'Interactive Brokers migration', s: 'pending', c: 'ops', d: 'Better execution, TWAP/VWAP, broader products. Broker abstraction layer.', r: 'Risk Management' },
          { l: 'Process separation (Signal/Risk/Exec/Watch)', s: 'pending', c: 'risk', d: 'Four independent processes. Knight Capital lesson.', r: 'Risk Management' },
          { l: 'Pass Series 65', s: 'pending', c: 'legal', d: 'Regulatory gate for accepting outside capital.', r: 'Risk Management' },
          { l: 'Scale live $5K → $25K', s: 'pending', c: 'strategy', d: '500-trade DSR validation.', r: 'Walk-Forward Validation' },
        ]},
      ],
    },
    { id: 'p5', name: 'Phase 5 — Fund preparation', status: 'locked', capital: '$25K → $100K+', cost: '$500+/mo', timeline: 'Oct 2027+',
      desc: 'Institutional-grade track record. Fund formation. Seed capital conversations.',
      gate: { label: '2+ year track record, audit complete' },
      subphases: [
        { label: 'Fund formation', items: [
          { l: 'Third-party audit', s: 'pending', c: 'legal', d: 'BDO, Grant Thornton, or RSM. Independent NAV verification.', r: 'Fund Roadmap' },
          { l: 'PPM + LPA drafting', s: 'pending', c: 'legal', d: 'Private Placement Memorandum + Limited Partnership Agreement. $15K-$50K legal.', r: 'Fund Roadmap' },
          { l: 'GIPS 2020 compliance', s: 'pending', c: 'validation', d: 'Required for institutional presentation of track record.', r: 'Walk-Forward Validation' },
          { l: '3+ strategies live', s: 'pending', c: 'strategy', d: 'Pullback + breakout + options/momentum.', r: 'Business Plan' },
          { l: 'Seed capital conversations', s: 'pending', c: 'legal', d: '66% of allocators require 3-5 year track record.', r: 'Fund Roadmap' },
        ]},
      ],
    },
    { id: 'p6', name: 'Phase 6+ — Multi-desk', status: 'locked', capital: '$500K+ AUM', cost: '$5K+/mo', timeline: '2028+',
      desc: 'Full multi-desk trading operation. Scale toward $3M+ AUM. Capacity ceiling $500M-$1B+.',
      gate: { label: 'Fund economics viable at $2M+ AUM' },
      subphases: [
        { label: 'Multi-desk architecture', items: [
          { l: 'Equity Swing Desk', s: 'pending', c: 'strategy', d: 'Pullback + breakout. Foundation desk.', r: 'Multi-desk architecture' },
          { l: 'Options Volatility Desk', s: 'pending', c: 'strategy', d: 'Credit spreads, vol trading. Gated by equity profitability.', r: 'Options research' },
          { l: 'Equity Momentum Desk', s: 'pending', c: 'strategy', d: 'Trend-following with separate LoRA.', r: 'Multi-desk architecture' },
          { l: 'Performance machine (~$5K)', s: 'pending', c: 'hardware', d: 'RTX 4090 or 2x 3090, Ryzen 9, 64GB DDR5. Multi-model, parallel training.', r: 'Hardware roadmap' },
        ]},
      ],
    },
  ],
  hardware: [
    { phase: 'Phase 2', name: 'Dedicated Halcyon machine', cost: '$1,500-2,000', specs: 'RTX 3090 24GB, Ryzen 5, 32GB RAM, 1TB NVMe, UPS', unlocks: '14B model, GRPO, 24/7 uninterrupted' },
    { phase: 'Phase 4+', name: 'Performance machine', cost: '$4,000-6,000', specs: 'RTX 4090 or 2x 3090, Ryzen 9, 64GB DDR5, 2TB NVMe', unlocks: 'Multi-model, parallel training, multi-desk' },
  ],
  costs: [
    { phase: 'Phase 1', cost: '$64/mo', detail: 'Render $14, Claude ~$50' },
    { phase: 'Phase 2', cost: '$125/mo', detail: '+ Polygon $29, LLC $5' },
    { phase: 'Phase 3', cost: '$155/mo', detail: '+ Unusual Whales $50' },
    { phase: 'Phase 4', cost: '$220/mo', detail: '+ IB data $30' },
    { phase: 'Phase 5', cost: '$500+/mo', detail: '+ audit, admin, legal' },
    { phase: 'Fund', cost: '$5K-15K+', detail: 'Professional fund ops' },
  ],
}

// ═══════════════════════════════════════════════════════════════
// Components
// ═══════════════════════════════════════════════════════════════
function StatusIcon({ s }) {
  if (s === 'done') return <CheckCircle2 size={14} className="shrink-0" style={{ color: '#2DD4BF' }} />
  if (s === 'in-progress') return <Loader2 size={14} className="animate-spin shrink-0" style={{ color: '#FBBF24' }} />
  return <Circle size={14} className="shrink-0" style={{ color: 'var(--slate-500)' }} />
}

function CatBadge({ c }) {
  const cat = CAT[c]
  return cat ? <span style={{ background: cat.color + '18', color: cat.color, fontSize: 10, padding: '1px 6px', borderRadius: 4 }}>{cat.label}</span> : null
}

function Item({ item }) {
  const [open, setOpen] = useState(false)
  const done = item.s === 'done'
  return (
    <div style={{ borderBottom: '1px solid var(--slate-700)' }}>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 py-2 px-1 text-left text-sm" style={{ opacity: done ? 0.55 : 1 }}
        onMouseEnter={e => { if (!done) e.currentTarget.style.background = 'rgba(45,212,191,0.04)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
        <StatusIcon s={item.s} />
        <span className="flex-1" style={{ color: done ? 'var(--slate-400)' : 'var(--slate-100)', textDecoration: done ? 'line-through' : 'none' }}>{item.l}</span>
        <CatBadge c={item.c} />
        {item.d && <ChevronRight size={12} style={{ color: 'var(--slate-500)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />}
      </button>
      {open && item.d && (
        <div className="px-7 pb-3 text-xs" style={{ color: 'var(--slate-400)', lineHeight: 1.6 }}>
          <p>{item.d}</p>
          {item.r && <p style={{ color: '#2DD4BF', fontSize: 10, marginTop: 4 }}>Source: {item.r}</p>}
        </div>
      )}
    </div>
  )
}

function SubPhaseBlock({ sp }) {
  const done = sp.items.filter(i => i.s === 'done').length
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
        <Calendar size={12} style={{ color: '#FBBF24' }} />
        <span style={{ color: '#FBBF24', fontSize: 12, fontWeight: 500 }}>{sp.label}</span>
        <span style={{ color: 'var(--slate-500)', fontSize: 11 }}>({done}/{sp.items.length})</span>
      </div>
      <div style={{ borderTop: '1px solid var(--slate-700)' }}>
        {sp.items.map((it, i) => <Item key={i} item={it} />)}
      </div>
    </div>
  )
}

function GateMetric({ m, val }) {
  const has = val != null
  let pass = false
  if (has) { pass = m.op === '>=' ? val >= m.target : m.op === '>' ? val > m.target : m.op === '<=' ? val <= m.target : false }
  const dv = !has ? '--' : m.fmt === 'pct' ? `${(val*100).toFixed(1)}%` : m.fmt === 'dollar' ? `$${val.toFixed(2)}` : m.fmt === 'pctVal' ? `${val.toFixed(1)}%` : (typeof val === 'number' ? (Number.isInteger(val) ? `${val}` : val.toFixed(2)) : `${val}`)
  const op = m.op === '>=' ? '≥' : m.op === '>' ? '>' : '≤'
  const tv = m.fmt === 'pct' ? `${(m.target*100).toFixed(0)}%` : m.fmt === 'pctVal' ? `${m.target}%` : m.fmt === 'dollar' ? `$${m.target}` : m.target
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="w-2 h-2 rounded-full shrink-0" style={{ background: has ? (pass ? '#2DD4BF' : '#E24B4A') : 'var(--slate-500)' }} />
      <span style={{ width: 110, color: 'var(--slate-400)' }}>{m.label}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, color: has ? (pass ? '#2DD4BF' : '#E24B4A') : 'var(--slate-400)' }}>{dv}</span>
      <span style={{ color: 'var(--slate-500)' }}>{op} {tv}</span>
    </div>
  )
}

function PhaseCard({ phase, kpis }) {
  const [exp, setExp] = useState(phase.status === 'active')
  const locked = phase.status === 'locked'
  const items = (phase.subphases || []).flatMap(s => s.items)
  const done = items.filter(i => i.s === 'done').length
  const pct = items.length > 0 ? Math.round((done / items.length) * 100) : 0

  return (
    <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--slate-600)', borderLeftWidth: 4, borderLeftColor: locked ? 'var(--slate-600)' : '#2DD4BF' }}>
      <button onClick={() => setExp(!exp)} className="w-full flex items-center justify-between p-4 text-left"
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(30,41,59,0.5)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {locked && <Lock size={14} style={{ color: 'var(--slate-400)' }} />}
            <span className="font-medium" style={{ color: 'var(--slate-100)' }}>{phase.name}</span>
            <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'var(--slate-600)', color: 'var(--slate-300)' }}>{phase.capital}</span>
            <span className="text-xs" style={{ color: '#FBBF24' }}>{phase.cost}</span>
            <span className="text-xs" style={{ color: 'var(--slate-500)' }}>{phase.timeline}</span>
          </div>
          <p className="text-sm mt-1" style={{ color: 'var(--slate-300)' }}>{phase.desc}</p>
          {!locked && items.length > 0 && (
            <div className="flex items-center gap-3 mt-2 text-xs" style={{ color: 'var(--slate-400)' }}>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--slate-600)' }}>
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: '#2DD4BF' }} />
              </div>
              <span>{done}/{items.length} complete</span>
            </div>
          )}
        </div>
        {exp ? <ChevronDown size={18} className="shrink-0 ml-2" style={{ color: 'var(--slate-400)' }} /> : <ChevronRight size={18} className="shrink-0 ml-2" style={{ color: 'var(--slate-400)' }} />}
      </button>

      {exp && phase.subphases && (
        <div className="px-4 pb-4" style={{ borderTop: '1px solid var(--slate-600)' }}>
          <div className="mt-3">{phase.subphases.map((sp, i) => <SubPhaseBlock key={i} sp={sp} />)}</div>
        </div>
      )}

      {phase.gate && phase.gate.metrics && (
        <div className="px-4 py-3" style={{ background: 'rgba(15,23,42,0.5)', borderTop: '1px solid var(--slate-600)' }}>
          <div className="flex items-center gap-2 text-xs mb-2">
            <Lock size={12} style={{ color: '#FBBF24' }} />
            <span className="font-medium" style={{ color: 'var(--slate-300)' }}>Gate</span>
            <span style={{ color: 'var(--slate-500)' }}>— {phase.gate.label}</span>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 ml-5">
            {phase.gate.metrics.map((m, i) => <GateMetric key={i} m={m} val={kpis ? kpis[m.key] : null} />)}
          </div>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Page
// ═══════════════════════════════════════════════════════════════
export default function Roadmap() {
  const { data: ctoData } = useQuery({
    queryKey: ['cto-report-gate'],
    queryFn: () => api.getCtoReport(90),
    refetchInterval: 60000,
  })
  const ts = ctoData?.trade_summary || {}
  const fm = ctoData?.fund_metrics || {}
  const kpis = {
    trades_closed: ts.trades_closed || 0, win_rate: ts.win_rate || 0,
    sharpe_ratio: ts.sharpe_ratio || 0, expectancy_dollars: ts.expectancy_dollars || 0,
    profit_factor: ts.profit_factor || 0, max_drawdown_pct: ts.max_drawdown_pct || 0,
    psr: fm.psr || null, calmar: fm.calmar_ratio || null, dsr: fm.dsr || null, ir: fm.information_ratio || null,
  }
  const allItems = ROADMAP_DATA.phases.flatMap(p => (p.subphases || []).flatMap(s => s.items))
  const doneCount = allItems.filter(i => i.s === 'done').length

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Roadmap</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--slate-400)' }}>Every gate is performance-based, not time-based. Updated {ROADMAP_DATA.lastUpdated}.</p>
        <div className="mt-3 flex items-center gap-3">
          <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--slate-600)' }}>
            <div className="h-full rounded-full" style={{ width: `${Math.round((doneCount/allItems.length)*100)}%`, background: '#2DD4BF' }} />
          </div>
          <span className="text-sm" style={{ color: 'var(--slate-300)' }}>{doneCount}/{allItems.length} items ({Math.round((doneCount/allItems.length)*100)}%)</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        {Object.entries(CAT).map(([k, c]) => (
          <span key={k} className="text-xs flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: c.color }} />
            <span style={{ color: 'var(--slate-400)' }}>{c.label}</span>
          </span>
        ))}
      </div>

      <div className="space-y-3">
        {ROADMAP_DATA.phases.map(p => <PhaseCard key={p.id} phase={p} kpis={kpis} />)}
      </div>

      <div className="rounded-lg p-4" style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)' }}>
        <RevenueProjection />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg p-4" style={{ border: '1px solid var(--slate-600)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Cpu size={16} style={{ color: 'var(--slate-300)' }} />
            <h2 className="text-sm font-medium" style={{ color: 'var(--slate-100)' }}>Hardware roadmap</h2>
          </div>
          {ROADMAP_DATA.hardware.map((h, i) => (
            <div key={i} className="rounded-lg p-3 mb-2" style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-700)' }}>
              <div className="flex items-center justify-between mb-1">
                <span style={{ color: '#2DD4BF', fontSize: 11, fontWeight: 500 }}>{h.phase}</span>
                <span style={{ color: '#FBBF24', fontSize: 12, fontFamily: 'var(--font-mono)' }}>{h.cost}</span>
              </div>
              <div className="text-sm font-medium" style={{ color: 'var(--slate-100)' }}>{h.name}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--slate-400)' }}>{h.specs}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--slate-300)' }}>Unlocks: {h.unlocks}</div>
            </div>
          ))}
        </div>

        <div className="rounded-lg p-4" style={{ border: '1px solid var(--slate-600)' }}>
          <div className="flex items-center gap-2 mb-3">
            <DollarSign size={16} style={{ color: 'var(--slate-300)' }} />
            <h2 className="text-sm font-medium" style={{ color: 'var(--slate-100)' }}>Monthly cost trajectory</h2>
          </div>
          <div className="space-y-2">
            {ROADMAP_DATA.costs.map((c, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span style={{ width: 60, color: 'var(--slate-400)' }}>{c.phase}</span>
                <span style={{ width: 80, color: '#FBBF24', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{c.cost}</span>
                <span style={{ color: 'var(--slate-500)' }}>{c.detail}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <p className="text-xs text-center pb-4" style={{ color: 'var(--slate-500)' }}>
        The moat: combinatorial fusion of signals in structured LLM training data. Every trade teaches the model.
      </p>
    </div>
  )
}
