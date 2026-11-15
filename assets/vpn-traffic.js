/* Real VPN tunnel traffic — shared by the dashboard block and /traffic.
 * Values from the API are bytes and bytes per second; formatting follows the
 * units chosen in Settings → VPN traffic. No dependency besides Chart.js. */
(function () {
  'use strict';

  const SI = 1000, IEC = 1024;

  function cfg() {
    const el = document.getElementById('trf-config');
    try { return el ? JSON.parse(el.textContent) : {}; } catch (_) { return {}; }
  }
  const CONF = cfg();
  const T = CONF.t || {};
  const LANG = CONF.lang || document.documentElement.lang || 'fr';
  let UNITS = CONF.units || { rate: 'mbps', volume: 'si' };

  function tr(key, params) {
    let s = T[key] || key;
    if (params) Object.keys(params).forEach(k => { s = s.replace('{' + k + '}', params[k]); });
    return s;
  }

  function num(v, digits) {
    return Number(v).toLocaleString(LANG, {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  }

  function volumeUnits() {
    const fr = LANG === 'fr';
    if (UNITS.volume === 'iec') return { base: IEC, names: fr ? ['o', 'Kio', 'Mio', 'Gio', 'Tio', 'Pio'] : ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'] };
    return { base: SI, names: fr ? ['o', 'ko', 'Mo', 'Go', 'To', 'Po'] : ['B', 'kB', 'MB', 'GB', 'TB', 'PB'] };
  }

  function fmtBytes(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) return '—';
    const u = volumeUnits();
    let v = Math.max(0, Number(bytes)), i = 0;
    while (v >= u.base && i < u.names.length - 1) { v /= u.base; i++; }
    const digits = i === 0 ? 0 : (v >= 100 ? 0 : (v >= 10 ? 1 : 2));
    return num(v, digits) + ' ' + u.names[i];
  }

  /* Scale used by charts: returns {factor, label} applied to bytes/s. */
  function rateScale(maxBps) {
    if (UNITS.rate === 'mbytes') {
      const u = volumeUnits();
      const m = u.base * u.base;
      return { factor: 1 / m, label: u.names[2] + '/s' };
    }
    if ((maxBps || 0) * 8 >= 1e9) return { factor: 8 / 1e9, label: 'Gbps' };
    return { factor: 8 / 1e6, label: 'Mbps' };
  }

  function fmtRate(bps) {
    if (bps === null || bps === undefined || isNaN(bps)) return { value: '—', unit: '' };
    if (UNITS.rate === 'mbytes') {
      const u = volumeUnits();
      const m = bps / (u.base * u.base);
      return { value: num(m, m >= 100 ? 0 : (m >= 10 ? 1 : 2)), unit: u.names[2] + '/s' };
    }
    const mbps = bps * 8 / 1e6;
    if (mbps >= 1000) return { value: num(mbps / 1000, 2), unit: 'Gbps' };
    return { value: num(mbps, mbps >= 100 ? 0 : (mbps >= 10 ? 1 : 2)), unit: 'Mbps' };
  }

  function fmtDate(ts, withTime) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return withTime
      ? d.toLocaleString(LANG, { dateStyle: 'medium', timeStyle: 'short' })
      : d.toLocaleDateString(LANG, { dateStyle: 'medium' });
  }

  function colors() {
    const dark = document.documentElement.getAttribute('data-bs-theme') !== 'light';
    return {
      dl: '#2dd4bf', dlFill: 'rgba(45,212,191,.16)',
      ul: '#fbbf24', ulFill: 'rgba(251,191,36,.10)',
      grid: dark ? 'rgba(48,54,61,.8)' : 'rgba(0,0,0,.07)',
      tick: dark ? '#8b949e' : '#666',
    };
  }

  const STATUS_CLASS = {
    connected: 'bg-success', unhealthy: 'bg-danger', unverified: 'bg-info text-dark',
    tunnel_down: 'bg-warning text-dark',
    container_down: 'bg-danger', unavailable: 'bg-secondary',
    disabled: 'bg-secondary', starting: 'bg-info text-dark',
  };

  const MEASURING = ['connected', 'unhealthy', 'unverified'];

  function reasonText(d) {
    if (d.status === 'connected') return '';
    if (d.status === 'disabled') return tr('trf_disabled_hint');
    if (d.status === 'starting') return tr('trf_waiting_samples');
    const key = 'trf_reason_' + (d.reason || 'generic');
    return T[key] ? T[key] : tr('trf_reason_generic');
  }

  function setText(root, sel, text) {
    root.querySelectorAll(sel).forEach(el => { el.textContent = text; });
  }

  /* Theme-aware charts: rebuild colours when the theme toggles. */
  const charts = new Set();
  new MutationObserver(() => {
    const c = colors();
    charts.forEach(ch => {
      ['x', 'y'].forEach(ax => {
        if (!ch.options.scales[ax]) return;
        ch.options.scales[ax].grid.color = c.grid;
        ch.options.scales[ax].ticks.color = c.tick;
      });
      ch.options.plugins.legend.labels.color = c.tick;
      ch.update('none');
    });
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-bs-theme'] });

  function baseOptions(yLabel) {
    const c = colors();
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: c.tick, boxWidth: 12, font: { size: 11 } } },
        tooltip: {},
      },
      scales: {
        x: { grid: { color: c.grid }, ticks: { color: c.tick, maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 10 } } },
        y: { beginAtZero: true, grid: { color: c.grid }, ticks: { color: c.tick, font: { size: 10 } },
             title: { display: !!yLabel, text: yLabel || '', color: c.tick, font: { size: 10 } } },
      },
    };
  }

  /* Line chart of rates. points: [{t (s), rx_rate, tx_rate}] (null = hole). */
  function rateChart(canvas, points, timeFmt) {
    if (!window.Chart || !canvas) return null;
    const max = Math.max(0, ...points.map(p => Math.max(p.rx_rate || 0, p.tx_rate || 0)));
    const sc = rateScale(max);
    const c = colors();
    const opts = baseOptions(sc.label);
    opts.scales.x.type = 'linear';
    if (points.length) {
      opts.scales.x.min = points[0].t * 1000;
      opts.scales.x.max = points[points.length - 1].t * 1000;
    }
    opts.scales.x.ticks.callback = v => timeFmt(v);
    opts.plugins.tooltip.callbacks = {
      title: items => items.length ? timeFmt(items[0].parsed.x, true) : '',
      label: item => {
        const f = fmtRate(item.raw.bps);
        return ' ' + item.dataset.label + ' : ' + f.value + ' ' + f.unit;
      },
    };
    const mk = (key) => points.map(p => ({ x: p.t * 1000, y: p[key] == null ? null : p[key] * sc.factor, bps: p[key] }));
    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        datasets: [
          { label: '↓ ' + tr('trf_download'), data: mk('rx_rate'), borderColor: c.dl, backgroundColor: c.dlFill,
            fill: true, tension: .25, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, spanGaps: false },
          { label: '↑ ' + tr('trf_upload'), data: mk('tx_rate'), borderColor: c.ul, backgroundColor: c.ulFill,
            fill: true, tension: .25, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, borderDash: [5, 3], spanGaps: false },
        ],
      },
      options: opts,
    });
    chart._trfScale = sc;
    charts.add(chart);
    return chart;
  }

  /* Bar chart of volumes. points: [{t, rx, tx}] with labels already computed. */
  function volumeChart(canvas, labels, points) {
    if (!window.Chart || !canvas) return null;
    const c = colors();
    const max = Math.max(0, ...points.map(p => Math.max(p.rx || 0, p.tx || 0)));
    const u = volumeUnits();
    let i = 0, div = 1;
    while (max / div >= u.base && i < u.names.length - 1) { div *= u.base; i++; }
    const opts = baseOptions(u.names[i]);
    opts.scales.x.ticks.maxTicksLimit = 12;
    opts.plugins.tooltip.callbacks = {
      label: item => ' ' + item.dataset.label + ' : ' + (item.raw === null ? '—' : fmtBytes(item.raw * div)),
    };
    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: '↓ ' + tr('trf_received'), data: points.map(p => p.rx == null ? null : p.rx / div), backgroundColor: c.dl, borderRadius: 2 },
          { label: '↑ ' + tr('trf_sent'), data: points.map(p => p.tx == null ? null : p.tx / div), backgroundColor: c.ul, borderRadius: 2 },
        ],
      },
      options: opts,
    });
    charts.add(chart);
    return chart;
  }

  function clockFmt(ms, long) {
    const d = new Date(ms);
    return d.toLocaleTimeString(LANG, long ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
  }

  /* ── Live block ─────────────────────────────────────────────────────── */
  function renderLive(root, d) {
    UNITS = d.units || UNITS;
    const badge = root.querySelector('[data-trf="status"]');
    if (badge) {
      badge.className = 'badge ' + (STATUS_CLASS[d.status] || 'bg-secondary');
      badge.textContent = tr('trf_status_' + d.status);
    }
    const reason = root.querySelector('[data-trf="reason"]');
    if (reason) {
      const txt = reasonText(d);
      reason.textContent = txt;
      reason.classList.toggle('d-none', !txt);
    }
    const down = fmtRate(d.rx_rate), up = fmtRate(d.tx_rate);
    setText(root, '[data-trf="rx-rate"]', down.value);
    setText(root, '[data-trf="rx-unit"]', down.unit);
    setText(root, '[data-trf="tx-rate"]', up.value);
    setText(root, '[data-trf="tx-unit"]', up.unit);
    const tot = d.totals || {};
    [['today', tot.today], ['month', tot.month], ['all', tot.all], ['hour', tot.last_hour]].forEach(([k, b]) => {
      if (!b) return;
      setText(root, `[data-trf="${k}-rx"]`, fmtBytes(b.rx));
      setText(root, `[data-trf="${k}-tx"]`, fmtBytes(b.tx));
      setText(root, `[data-trf="${k}-total"]`, fmtBytes(b.total));
    });
    setText(root, '[data-trf="since"]', d.since ? tr('trf_since', { date: fmtDate(d.since, true) }) : '');
    setText(root, '[data-trf="server"]', d.server || '—');
    setText(root, '[data-trf="provider"]', d.provider || '—');
    setText(root, '[data-trf="protocol"]', d.protocol ? (d.protocol === 'wireguard' ? 'WireGuard' : (d.protocol === 'openvpn' ? 'OpenVPN' : d.protocol)) : '—');
    setText(root, '[data-trf="iface"]', d.iface || '—');
    const note = root.querySelector('[data-trf="note"]');
    if (note) note.textContent = tr('trf_real_note', { iface: d.iface || 'tun0' });
    const bench = root.querySelector('[data-trf="bench"]');
    if (bench && tot.all) {
      const b = (tot.all.bench_rx || 0) + (tot.all.bench_tx || 0);
      bench.textContent = b > 0 ? '(' + tr('trf_bench_note', { v: fmtBytes(b) }) + ')' : '';
    }
    // Rates stay bright while counters are sampled, even if the VPN is unhealthy.
    root.classList.toggle('trf-dim', !MEASURING.includes(d.status));
  }

  function initLive(root) {
    if (!root) return;
    const canvas = root.querySelector('canvas[data-trf="chart"]');
    const empty = root.querySelector('[data-trf="chart-empty"]');
    const points = [];
    let lastTs = null, chart = null, timer = null, mode = 'live', minuteChart = null;
    const WINDOW = 5 * 60;   // 5 minutes of real-time samples on the dashboard

    function pushSamples(samples) {
      samples.forEach(([t, rx, tx]) => points.push({ t, rx_rate: rx, tx_rate: tx }));
      if (samples.length) lastTs = samples[samples.length - 1][0];
      const cutoff = (lastTs || 0) - WINDOW;
      while (points.length && points[0].t < cutoff) points.shift();
    }

    function drawLive() {
      if (!canvas || mode !== 'live') return;
      const hasData = points.some(p => p.rx_rate != null);
      if (empty) empty.classList.toggle('d-none', hasData);
      canvas.parentElement.classList.toggle('d-none', !hasData);
      if (!hasData) return;
      const max = Math.max(0, ...points.map(p => Math.max(p.rx_rate || 0, p.tx_rate || 0)));
      const sc = rateScale(max);
      if (!chart || chart._trfScale.label !== sc.label) {
        if (chart) { charts.delete(chart); chart.destroy(); }
        chart = rateChart(canvas, points, ms => clockFmt(ms, true));
        return;
      }
      const mk = key => points.map(p => ({ x: p.t * 1000, y: p[key] == null ? null : p[key] * sc.factor, bps: p[key] }));
      chart.data.datasets[0].data = mk('rx_rate');
      chart.data.datasets[1].data = mk('tx_rate');
      chart.options.scales.x.min = points[0].t * 1000;
      chart.options.scales.x.max = points[points.length - 1].t * 1000;
      chart.update('none');
    }

    let inflight = false, lastInterval = null, hourLoadedAt = 0;
    const HOUR_REFRESH_MS = 30000;   // minute buckets: no need to redraw faster

    function getJson(url) {
      // A redirect to the login page or a 5xx must be a failure, not "no data".
      return fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' })
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
    }

    function poll() {
      if (inflight) return;
      inflight = true;
      const url = CONF.liveUrl + (lastTs ? ('?since=' + lastTs) : '');
      getJson(url)
        .then(d => {
          lastInterval = d.interval;
          renderLive(root, d);
          pushSamples(d.samples || []);
          drawLive();
          if (mode === '1h' && Date.now() - hourLoadedAt >= HOUR_REFRESH_MS) loadHour();
        })
        .catch(() => markOffline())
        // Whatever happened, the next refresh is always scheduled.
        .finally(() => { inflight = false; schedule(lastInterval); });
    }

    function markOffline() {
      const badge = root.querySelector('[data-trf="status"]');
      if (badge) { badge.className = 'badge bg-secondary'; badge.textContent = tr('trf_status_unavailable'); }
      const reason = root.querySelector('[data-trf="reason"]');
      if (reason) { reason.textContent = tr('trf_reason_ui_offline'); reason.classList.remove('d-none'); }
      root.classList.add('trf-dim');
    }

    function schedule(interval) {
      clearTimeout(timer);
      // UI refresh every 3–5 s, never faster than the collection itself.
      const secs = Math.max(3, Math.min(5, interval || 5));
      timer = setTimeout(() => { if (!document.hidden) poll(); else schedule(interval); }, secs * 1000);
    }

    function loadHour() {
      hourLoadedAt = Date.now();
      getJson(CONF.historyUrl + '?range=1h').then(h => {
        if (mode !== '1h') return;
        if (chart) { charts.delete(chart); chart.destroy(); chart = null; }
        if (minuteChart) { charts.delete(minuteChart); minuteChart.destroy(); minuteChart = null; }
        const pts = (h.rate && h.rate.points) || [];
        const hasData = pts.some(p => p.rx_rate != null);
        if (empty) empty.classList.toggle('d-none', hasData);
        canvas.parentElement.classList.toggle('d-none', !hasData);
        if (hasData) minuteChart = rateChart(canvas, pts, clockFmt);
      }).catch(() => { hourLoadedAt = 0; });   // retried on the next poll
    }

    root.querySelectorAll('[data-trf-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        mode = btn.dataset.trfMode;
        root.querySelectorAll('[data-trf-mode]').forEach(b => b.classList.toggle('active', b === btn));
        if (mode === 'live') {
          if (minuteChart) { charts.delete(minuteChart); minuteChart.destroy(); minuteChart = null; }
          if (chart) { charts.delete(chart); chart.destroy(); chart = null; }
          drawLive();
          return;
        }
        loadHour();
      });
    });

    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    if (CONF.initial) { renderLive(root, CONF.initial); pushSamples(CONF.initial.samples || []); drawLive(); if (CONF.initial.samples && CONF.initial.samples.length) lastTs = CONF.initial.samples[CONF.initial.samples.length - 1][0]; }
    schedule(CONF.initial && CONF.initial.interval);
  }

  /* ── History page ───────────────────────────────────────────────────── */
  function labelFor(t, width, range) {
    if (typeof t === 'string') {
      if (t.length === 7) {
        const [y, m] = t.split('-').map(Number);
        return new Date(y, m - 1, 1).toLocaleDateString(LANG, { month: 'short', year: 'numeric' });
      }
      const [y, m, dd] = t.split('-').map(Number);
      return new Date(y, m - 1, dd).toLocaleDateString(LANG, range === '7d' ? { weekday: 'short', day: 'numeric' } : { day: 'numeric', month: 'short' });
    }
    const d = new Date(t * 1000);
    if (width >= 3600 && range !== '24h') return d.toLocaleString(LANG, { day: 'numeric', month: 'short', hour: '2-digit' });
    return d.toLocaleTimeString(LANG, { hour: '2-digit', minute: '2-digit' });
  }

  function initHistory(root) {
    if (!root) return;
    let rateCh = null, volCh = null, liveTimer = null;
    const rateCanvas = root.querySelector('canvas[data-trf="rate-chart"]');
    const volCanvas = root.querySelector('canvas[data-trf="volume-chart"]');
    const rateWrap = root.querySelector('[data-trf="rate-wrap"]');
    const volWrap = root.querySelector('[data-trf="volume-wrap"]');
    const empty = root.querySelector('[data-trf="history-empty"]');

    const VOLUME_TITLE = { 300: 'trf_chart_volume_5m', 3600: 'trf_chart_volume_hour', 86400: 'trf_chart_volume_day' };

    function destroy() {
      [rateCh, volCh].forEach(ch => { if (ch) { charts.delete(ch); ch.destroy(); } });
      rateCh = volCh = null;
    }

    let current = null;
    function load(range) {
      current = range;
      clearTimeout(liveTimer);
      root.querySelectorAll('[data-trf-range]').forEach(b => b.classList.toggle('active', b.dataset.trfRange === range));
      try { history.replaceState(null, '', '?range=' + range); } catch (_) {}
      fetch(CONF.historyUrl + '?range=' + range, { headers: { Accept: 'application/json' }, cache: 'no-store' })
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(h => {
          if (current !== range) return;   // a newer range was selected meanwhile
          UNITS = h.units || UNITS;
          destroy();
          const s = h.summary || {};
          setText(root, '[data-trf="sum-rx"]', fmtBytes(s.rx));
          setText(root, '[data-trf="sum-tx"]', fmtBytes(s.tx));
          setText(root, '[data-trf="sum-total"]', fmtBytes(s.total));
          const pr = fmtRate(s.peak_rx), pt = fmtRate(s.peak_tx);
          setText(root, '[data-trf="sum-peak-rx"]', pr.value + ' ' + pr.unit);
          setText(root, '[data-trf="sum-peak-tx"]', pt.value + ' ' + pt.unit);
          const benchBytes = (s.bench_rx || 0) + (s.bench_tx || 0);
          setText(root, '[data-trf="sum-bench"]', benchBytes > 0 ? tr('trf_bench_note', { v: fmtBytes(benchBytes) }) : '');
          setText(root, '[data-trf="since-note"]', h.since ? tr('trf_no_data_before', { date: fmtDate(h.since, true) }) : '');

          const ratePts = (h.rate && h.rate.points) || [];
          const volPts = (h.volume && h.volume.points) || [];
          const hasRate = ratePts.some(p => p.rx_rate != null);
          const hasVol = volPts.some(p => p.rx != null);
          if (rateWrap) rateWrap.classList.toggle('d-none', !hasRate);
          if (volWrap) volWrap.classList.toggle('d-none', !hasVol);
          if (empty) empty.classList.toggle('d-none', hasRate || hasVol);
          setText(root, '[data-trf="rate-title"]', tr(range === 'live' ? 'trf_chart_rate' : 'trf_chart_rate_avg'));

          if (hasRate) {
            const longRange = h.rate.width && h.rate.width >= 3600;
            rateCh = rateChart(rateCanvas, ratePts, (ms, long) => {
              const d = new Date(ms);
              if (longRange) return d.toLocaleString(LANG, long ? { dateStyle: 'medium', timeStyle: 'short' } : { day: 'numeric', month: 'short' });
              if (range === '24h') return d.toLocaleTimeString(LANG, { hour: '2-digit', minute: '2-digit' });
              return clockFmt(ms, long);
            });
          }
          if (hasVol) {
            const width = h.volume.width;
            const title = width ? (VOLUME_TITLE[width] || 'trf_chart_volume_day') : 'trf_chart_volume_month';
            setText(root, '[data-trf="volume-title"]', tr(title));
            volCh = volumeChart(volCanvas, volPts.map(p => labelFor(p.t, width, range)), volPts);
          }
        })
        .catch(() => { if (empty && !rateCh && !volCh) empty.classList.remove('d-none'); })
        .finally(() => {
          // Keep refreshing the live range even after a failed request.
          if (current === range && range === 'live') liveTimer = setTimeout(() => load('live'), 5000);
        });
    }

    root.querySelectorAll('[data-trf-range]').forEach(btn => btn.addEventListener('click', () => load(btn.dataset.trfRange)));
    load(CONF.range || '24h');
  }

  window.VpnTraffic = { initLive, initHistory, fmtBytes, fmtRate };
  document.addEventListener('DOMContentLoaded', () => {
    initLive(document.getElementById('trf-live'));
    initHistory(document.getElementById('trf-history'));
  });
})();
