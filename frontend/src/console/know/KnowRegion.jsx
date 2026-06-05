/**
 * KnowRegion — the KNOW region shell + overview + drill-down stubs (P3-T4).
 * Design law #6: overview → drill-down (never a flat page menu).
 * Nested react-router routes under /console/know.
 */
import { Routes, Route } from 'react-router-dom'
import {
  KnowOverview,
  LadderStub,
  TrackRecordStub,
  LedgersStub,
  SystemMapStub,
  RigorStub,
  AttributionStub,
  ResearchStub,
  ScorecardsStub,
} from './components'

export default function KnowRegion() {
  return (
    <div data-testid="know-region">
      <Routes>
        <Route index element={<KnowOverview />} />
        <Route path="ladder" element={<LadderStub />} />
        <Route path="track-record" element={<TrackRecordStub />} />
        <Route path="ledgers" element={<LedgersStub />} />
        <Route path="system-map" element={<SystemMapStub />} />
        <Route path="rigor" element={<RigorStub />} />
        <Route path="attribution" element={<AttributionStub />} />
        <Route path="research" element={<ResearchStub />} />
        <Route path="scorecards" element={<ScorecardsStub />} />
      </Routes>
    </div>
  )
}
