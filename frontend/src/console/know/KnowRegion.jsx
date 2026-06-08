/**
 * KnowRegion — the KNOW region shell + overview + drill-down stubs (P3-T4).
 * Design law #6: overview → drill-down (never a flat page menu).
 * Nested react-router routes under /console/know.
 */
import { Routes, Route } from 'react-router-dom'
import {
  KnowOverview,
  FundLadderView,
  TrackRecordView,
  TradeLedgersView,
  SystemMapView,
} from './components'
import RigorStack from './RigorStack'
import AttributionView from './AttributionView'
import ResearchView from './ResearchView'
import ScorecardsView from './ScorecardsView'

export default function KnowRegion() {
  return (
    <div data-testid="know-region">
      <Routes>
        <Route index element={<KnowOverview />} />
        <Route path="ladder" element={<FundLadderView />} />
        <Route path="track-record" element={<TrackRecordView />} />
        <Route path="ledgers" element={<TradeLedgersView />} />
        <Route path="system-map" element={<SystemMapView />} />
        <Route path="rigor" element={<RigorStack />} />
        <Route path="attribution" element={<AttributionView />} />
        <Route path="research" element={<ResearchView />} />
        <Route path="scorecards" element={<ScorecardsView />} />
      </Routes>
    </div>
  )
}
