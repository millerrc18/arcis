/**
 * KnowRegion — the KNOW region shell + overview + drill-down stubs (P3-T4).
 * Design law #6: overview → drill-down (never a flat page menu).
 * Nested react-router routes under /console/know.
 */
import { Routes, Route } from 'react-router-dom'
import {
  KnowOverview,
  FundLadderView,
  TrackRecordStub,
  LedgersStub,
  SystemMapView,
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
        <Route path="ladder" element={<FundLadderView />} />
        <Route path="track-record" element={<TrackRecordStub />} />
        <Route path="ledgers" element={<LedgersStub />} />
        <Route path="system-map" element={<SystemMapView />} />
        <Route path="rigor" element={<RigorStub />} />
        <Route path="attribution" element={<AttributionStub />} />
        <Route path="research" element={<ResearchStub />} />
        <Route path="scorecards" element={<ScorecardsStub />} />
      </Routes>
    </div>
  )
}
