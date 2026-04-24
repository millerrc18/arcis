"""MarketPulse analytics suite -- stateless functions on bar DataFrames."""

from .summary import daily_summary, biggest_movers, volume_analysis
from .volatility import realized_volatility, intraday_vol_profile, vol_surface, garman_klass_vol
from .correlation import pairwise_correlation, sector_correlation, rolling_correlation
from .patterns import intraday_patterns, day_of_week_effects, monthly_seasonality
from .sectors import sector_rotation, sector_heatmap, relative_strength
from .events import volume_spikes, price_gaps, anomaly_detection, event_impact
