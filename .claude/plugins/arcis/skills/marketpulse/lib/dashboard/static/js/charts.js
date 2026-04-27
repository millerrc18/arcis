/**
 * MarketPulse dashboard -- Plotly chart helper functions.
 *
 * Each function accepts a div ID, data, and an options object,
 * then calls Plotly.newPlot() with appropriate traces and layout.
 *
 * Theme colors are read from the current dark/light mode.
 */

// ---------------------------------------------------------------------------
// Theme-aware color helpers
// ---------------------------------------------------------------------------

function isDarkMode() {
    return document.documentElement.classList.contains('dark');
}

function getThemeColors() {
    const dark = isDarkMode();
    return {
        bg: 'transparent',
        paper: 'transparent',
        text: dark ? '#e2e8f0' : '#111827',
        grid: dark ? '#334155' : '#e5e7eb',
        accent: dark ? '#38bdf8' : '#2563eb',
        green: dark ? '#6ee7b7' : '#16a34a',
        red: dark ? '#fca5a5' : '#dc2626',
        blue: '#3b82f6',
        muted: dark ? '#94a3b8' : '#6b7280',
    };
}

function baseLayout(title, opts = {}) {
    const c = getThemeColors();
    return Object.assign({
        title: { text: title, font: { color: c.text, size: 14 } },
        paper_bgcolor: c.paper,
        plot_bgcolor: c.bg,
        font: { color: c.text, size: 11 },
        margin: { t: title ? 40 : 10, b: 40, l: 50, r: 20 },
        xaxis: {
            gridcolor: c.grid,
            linecolor: c.grid,
            zerolinecolor: c.grid,
        },
        yaxis: {
            gridcolor: c.grid,
            linecolor: c.grid,
            zerolinecolor: c.grid,
        },
        legend: { orientation: 'h', y: -0.15, font: { size: 10 } },
        hovermode: 'x unified',
    }, opts);
}

// ---------------------------------------------------------------------------
// Chart functions
// ---------------------------------------------------------------------------

/**
 * Mini bar chart for volume distribution on the overview page.
 *
 * @param {string} divId - Target div element ID
 * @param {string[]} labels - Ticker symbols
 * @param {number[]} values - Volume values
 */
function createMiniBar(divId, labels, values) {
    const c = getThemeColors();
    const traces = [{
        x: labels,
        y: values,
        type: 'bar',
        marker: { color: c.accent, opacity: 0.8 },
        hovertemplate: '%{x}: %{y:,.0f}<extra></extra>',
    }];

    const layout = baseLayout('', {
        margin: { t: 5, b: 30, l: 40, r: 10 },
        xaxis: { tickfont: { size: 9 }, gridcolor: c.grid },
        yaxis: { tickfont: { size: 9 }, gridcolor: c.grid },
        height: 100,
    });

    Plotly.newPlot(divId, traces, layout, { responsive: true, displayModeBar: false });
}

/**
 * Candlestick chart with volume subplot.
 *
 * @param {string} divId - Target div element ID
 * @param {Object} data - { dates, open, high, low, close, volume }
 * @param {Object} opts - { title }
 */
function createCandlestick(divId, data, opts = {}) {
    const c = getThemeColors();

    const candlestick = {
        x: data.dates,
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
        type: 'candlestick',
        increasing: { line: { color: c.green } },
        decreasing: { line: { color: c.red } },
        xaxis: 'x',
        yaxis: 'y',
        name: 'Price',
    };

    const volume = {
        x: data.dates,
        y: data.volume,
        type: 'bar',
        marker: { color: c.accent, opacity: 0.3 },
        xaxis: 'x',
        yaxis: 'y2',
        name: 'Volume',
        hovertemplate: 'Vol: %{y:,.0f}<extra></extra>',
    };

    const layout = baseLayout(opts.title || '', {
        height: 500,
        grid: { rows: 2, columns: 1, subplots: [['xy'], ['xy2']], roworder: 'top to bottom' },
        xaxis: { rangeslider: { visible: false }, gridcolor: c.grid },
        yaxis: { domain: [0.3, 1], title: 'Price', gridcolor: c.grid },
        yaxis2: { domain: [0, 0.25], title: 'Volume', gridcolor: c.grid },
    });

    Plotly.newPlot(divId, [candlestick, volume], layout, { responsive: true, displayModeBar: true });
}

/**
 * Heatmap chart (for sector heatmap, correlation matrix).
 *
 * @param {string} divId - Target div element ID
 * @param {Object} data - { x: [...], y: [...], z: [[...], ...] }
 * @param {Object} opts - { title, colorscale }
 */
function createHeatmap(divId, data, opts = {}) {
    const c = getThemeColors();

    const trace = {
        x: data.x,
        y: data.y,
        z: data.z,
        type: 'heatmap',
        colorscale: opts.colorscale || [[0, c.red], [0.5, '#1e293b'], [1, c.green]],
        hovertemplate: '%{y} / %{x}: %{z:.4f}<extra></extra>',
    };

    const layout = baseLayout(opts.title || '', {
        height: opts.height || 400,
        margin: { t: 40, b: 80, l: 100, r: 20 },
    });

    Plotly.newPlot(divId, [trace], layout, { responsive: true, displayModeBar: false });
}

/**
 * Line chart (for volatility, rolling correlation, relative strength).
 *
 * @param {string} divId - Target div element ID
 * @param {Object[]} series - [{ name, x, y, color? }, ...]
 * @param {Object} opts - { title, yAxisTitle }
 */
function createLineChart(divId, series, opts = {}) {
    const c = getThemeColors();

    const traces = series.map((s, i) => ({
        x: s.x,
        y: s.y,
        type: 'scatter',
        mode: 'lines',
        name: s.name,
        line: { color: s.color || [c.accent, c.green, c.red, '#f59e0b', '#8b5cf6'][i % 5], width: 2 },
    }));

    const layout = baseLayout(opts.title || '', {
        height: opts.height || 400,
        yaxis: { title: opts.yAxisTitle || '', gridcolor: c.grid },
    });

    Plotly.newPlot(divId, traces, layout, { responsive: true, displayModeBar: false });
}

/**
 * Grouped bar chart (for patterns -- intraday, day-of-week, monthly).
 *
 * @param {string} divId - Target div element ID
 * @param {string[]} categories - X-axis labels
 * @param {Object[]} series - [{ name, values, color? }, ...]
 * @param {Object} opts - { title, yAxisTitle }
 */
function createGroupedBar(divId, categories, series, opts = {}) {
    const c = getThemeColors();

    const traces = series.map((s, i) => ({
        x: categories,
        y: s.values,
        type: 'bar',
        name: s.name,
        marker: { color: s.color || [c.accent, c.green, '#f59e0b', c.red][i % 4] },
    }));

    const layout = baseLayout(opts.title || '', {
        height: opts.height || 400,
        barmode: 'group',
        yaxis: { title: opts.yAxisTitle || '', gridcolor: c.grid },
    });

    Plotly.newPlot(divId, traces, layout, { responsive: true, displayModeBar: false });
}
