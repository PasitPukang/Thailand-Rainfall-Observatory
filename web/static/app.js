const $ = (id) => document.getElementById(id);
const fmt = (value) => Number(value ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 1 });
const fmtDays = (value) => Number(value ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 2 });
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const months = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
let currentView = 'dashboard';

function setView(view) {
  currentView = view;
  document.querySelectorAll('.view').forEach((el) => el.classList.toggle('active', el.id === view));
  document.querySelectorAll('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
  $('view-title').textContent = ({ dashboard: 'ภาพรวมข้อมูล', analysis: 'วิเคราะห์ฝนหนักรายจังหวัด', forecast: 'แนวโน้มและประมาณการ', pipeline: 'การทำงานของ Pipeline', manual: 'คู่มือและแหล่งข้อมูล' })[view];
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function lineChart(rows) {
  if (!rows.length) return '<p class="muted">ไม่มีข้อมูล</p>';
  const w = 600, h = 215, left = 38, right = 10, top = 12, bottom = 34;
  const max = Math.max(1, ...rows.map((r) => Number(r.rainfall_mm)));
  const x = (i) => left + (i / Math.max(1, rows.length - 1)) * (w - left - right);
  const y = (v) => h - bottom - (v / max) * (h - top - bottom);
  const line = rows.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(Number(r.rainfall_mm)).toFixed(1)}`).join(' ');
  const area = `${line} L${x(rows.length - 1)},${h - bottom} L${x(0)},${h - bottom} Z`;
  const ticks = [0, .5, 1].map((part) => `<line class="gridline" x1="${left}" y1="${y(max * part)}" x2="${w - right}" y2="${y(max * part)}"/><text class="axis" x="${left - 7}" y="${y(max * part) + 4}" text-anchor="end">${fmt(max * part)}</text>`).join('');
  const labels = [0, Math.floor((rows.length - 1) / 2), rows.length - 1].map((i) => `<text class="axis" x="${x(i)}" y="${h - 8}" text-anchor="middle">${esc(rows[i].date.slice(5))}</text>`).join('');
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="กราฟฝนรายวัน"><defs><linearGradient id="rainGradient" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#41d5c3" stop-opacity=".35"/><stop offset="1" stop-color="#41d5c3" stop-opacity="0"/></linearGradient></defs>${ticks}<path class="area" d="${area}"/><path class="line" d="${line}"/>${labels}</svg>`;
}

function barChart(rows, key, label, partialKey, unit = 'มม.') {
  if (!rows.length) return '<p class="muted">ไม่มีข้อมูล</p>';
  const w = 560, h = 215, left = 36, right = 10, top = 12, bottom = 34;
  const inner = w - left - right;
  const max = Math.max(1, ...rows.map((r) => Number(r[key])));
  const slot = inner / rows.length, width = Math.min(34, slot * .62);
  const y = (v) => h - bottom - (v / max) * (h - top - bottom);
  const ticks = [0, .5, 1].map((part) => `<line class="gridline" x1="${left}" y1="${y(max * part)}" x2="${w - right}" y2="${y(max * part)}"/><text class="axis" x="${left - 6}" y="${y(max * part) + 4}" text-anchor="end">${fmt(max * part)}</text>`).join('');
  // Thin out x-axis labels when bars are too narrow for them (e.g. 27 years); the latest bar always keeps its label.
  const labelWidth = Math.max(...rows.map((r) => String(label(r)).length)) * 6.5 + 6;
  const step = Math.max(1, Math.ceil(labelWidth / slot));
  const bars = rows.map((r, i) => { const cx = left + slot * (i + .5), value = Number(r[key]), barHeight = h - bottom - y(value); const tick = (rows.length - 1 - i) % step === 0 ? `<text class="axis" x="${cx}" y="${h - 8}" text-anchor="middle">${esc(label(r))}</text>` : ''; return `<rect class="bar ${partialKey && !r[partialKey] ? 'partial' : ''}" x="${cx - width / 2}" y="${y(value)}" width="${width}" height="${Math.max(1, barHeight)}" rx="3"><title>${esc(label(r))}: ${fmt(value)} ${esc(unit)}</title></rect>${tick}`; }).join('');
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="กราฟแท่งปริมาณฝน">${ticks}${bars}</svg>`;
}

function renderForecast(data) {
  const cards = data.forecast.months.map((item) => {
    const rangeMax = Math.max(item.high_mm * 1.15, item.estimate_mm + 1);
    const low = Math.max(0, item.low_mm / rangeMax * 100), high = Math.min(100, item.high_mm / rangeMax * 100);
    const median = Math.min(100, item.estimate_mm / rangeMax * 100);
    return `<article class="forecast-card"><div class="month">${months[item.month - 1]} ${item.year + 543}</div><strong>${fmt(item.estimate_mm)} <span style="font-size:1rem;color:var(--muted)">มม.</span></strong><div class="measure">ค่ากลางฝนรวมรายเดือน</div><div class="range"><div class="band" style="left:${low}%;width:${Math.max(1, high - low)}%"></div><div class="marker" style="left:${median}%"></div></div><div class="range-label"><span>${fmt(item.low_mm)} มม.</span><span>${fmt(item.high_mm)} มม.</span></div><div class="error">ทดสอบย้อนหลัง ${item.history_years} ปี · MAE <b>${fmt(item.backtest_mae_mm)} มม.</b></div></article>`;
  }).join('');
  $('forecast-cards').innerHTML = cards || '<div class="panel">ข้อมูลย้อนหลังยังไม่พอสำหรับประมาณการ</div>';
}

function renderAnalysis(data) {
  const item = data.analysis;
  const period = item.same_period;
  const current = period.current;
  $('analysis-basis').textContent = item.basis === 'mean_per_province_point'
    ? 'ภาพรวม: ค่าเฉลี่ยต่อจุดตัวแทน 77 จังหวัด' : `จุดตัวแทนจังหวัด${data.selected_name}`;
  $('heavy-current-label').textContent = `วันฝนหนักปี ${period.current_year + 543} · ช่วงเดียวกัน`;
  $('heavy-current').textContent = current ? fmtDays(current.heavy_days) : '—';
  $('heavy-baseline').textContent = period.historical_median_heavy_days == null ? '—' : fmtDays(period.historical_median_heavy_days);
  $('heavy-change').textContent = period.heavy_change_pct == null ? 'เทียบไม่ได้' : `${period.heavy_change_pct > 0 ? '+' : ''}${fmt(period.heavy_change_pct)}%`;
  $('heavy-period').textContent = `1 ม.ค.–${period.through.slice(3)} ${months[Number(period.through.slice(0, 2)) - 1]} · ${period.days} วัน`;
  $('very-heavy-current').textContent = current ? fmtDays(current.very_heavy_days) : '—';
  $('comparison-range').textContent = `ช่วงเดียวกัน ${period.days} วัน`;
  $('heavy-annual-chart').innerHTML = barChart(item.annual, 'heavy_days', (r) => String(r.year + 543), 'complete', 'วัน');
  $('heavy-month-chart').innerHTML = barChart(item.seasonal_heavy, 'heavy_days_per_year', (r) => months[r.month - 1], null, 'วัน/ปี');
  $('temperature-chart').innerHTML = barChart(item.annual, 'average_temperature_c', (r) => String(r.year + 543), 'complete', '°C');
  $('humidity-chart').innerHTML = barChart(item.annual, 'average_humidity_pct', (r) => String(r.year + 543), 'complete', '%');
  $('wind-chart').innerHTML = barChart(item.annual, 'average_daily_max_wind_kmh', (r) => String(r.year + 543), 'complete', 'กม./ชม.');
  $('comparison-rows').innerHTML = period.years.map((r) => `<tr class="${r.year === period.current_year ? 'current-year' : ''}"><td>${r.year + 543}</td><td>${fmtDays(r.heavy_days)}</td><td>${fmtDays(r.very_heavy_days)}</td><td>${fmt(r.rainfall_mm)}</td><td>${fmt(r.average_temperature_c)}</td></tr>`).join('');
}

function renderRanking(items) {
  const max = Math.max(1, ...items.map((r) => r.heavy_days));
  $('ranking').innerHTML = items.map((r, i) => `<div class="rank-row"><span class="order">${String(i + 1).padStart(2, '0')}</span><span class="name" title="${esc(r.province_name)}">${esc(r.province_name)}</span><span class="rank-track"><span class="rank-fill" style="display:block;width:${Math.max(2, r.heavy_days / max * 100)}%"></span></span><span class="rank-value">${fmt(r.heavy_days)}</span></div>`).join('');
}

function renderFiles(items) {
  $('file-inventory').innerHTML = items.map((item) => `<div><div><strong>${esc(item.label)}</strong><br><code>${esc(item.path)}</code></div><span>${fmt(item.count)} ไฟล์ · ${fmt(item.size_mb)} MB</span></div>`).join('');
}

function renderRunHistory(runs) {
  $('run-history').innerHTML = runs.map((run) => `<tr><td>${esc(run.finished_at_th)}</td><td class="${run.status === 'SUCCESS' ? 'ok' : 'fail'}">${run.status === 'SUCCESS' ? 'สำเร็จ' : 'ล้มเหลว'}</td><td>${esc(run.target_date)}</td><td>${fmt(run.new_hourly_rows)}</td><td>${fmt(run.updated_hourly_rows)}</td><td>${fmt(run.new_daily_rows)}</td></tr>`).join('');
}

function renderToday(outlook, place) {
  $('today-date').textContent = `${outlook.date} · เวลาไทย`;
  $('today-place').textContent = outlook.basis === 'one_province_point'
    ? `จุดตัวแทนจังหวัด${place}` : 'เฉลี่ยโอกาสของจุดตัวแทน 77 จังหวัด';
  if (outlook.probability_pct == null) {
    $('today-answer').textContent = 'ข้อมูลไม่พอ';
    $('today-probability').textContent = '—';
    $('today-explanation').textContent = 'ไม่พบข้อมูลย้อนหลังสำหรับคำนวณ';
    $('today-meter-fill').style.width = '0%';
    return;
  }
  $('today-answer').textContent = outlook.likely_rain ? 'มีแนวโน้มฝนตก' : 'มีแนวโน้มฝนไม่ตก';
  $('today-answer').classList.toggle('rain-yes', outlook.likely_rain);
  $('today-probability').textContent = `${outlook.probability_pct}%`;
  $('today-meter-fill').style.width = `${outlook.probability_pct}%`;
  $('today-explanation').textContent = `${fmt(outlook.wet_samples)} จาก ${fmt(outlook.sample_count)} ตัวอย่างมีฝน · ข้อมูลจริงล่าสุด ${outlook.historical_data_through}`;
}

function render(data) {
  if ($('province').options.length === 1) {
    data.provinces.forEach((p) => {
      for (const id of ['province', 'analysis-province']) {
        const option = document.createElement('option'); option.value = p.province_id; option.textContent = p.province_name; $(id).append(option);
      }
    });
  }
  $('analysis-province').value = $('province').value;
  $('asof').textContent = `ข้อมูลถึง ${data.last_date} · ${data.selected_name}`;
  renderToday(data.today_rain, data.selected_name);
  $('stat-rain30').textContent = fmt(data.kpis.rain_last_30_mm);
  $('stat-ytd').textContent = fmt(data.kpis.rain_ytd_mm);
  $('stat-max').textContent = fmt(data.kpis.max_day_last_30_mm);
  $('stat-temp').textContent = fmt(data.kpis.avg_temp_last_30_c);
  $('recent-chart').innerHTML = lineChart(data.recent);
  $('annual-chart').innerHTML = barChart(data.annual, 'rainfall_mm', (r) => String(r.year + 543), 'complete');
  $('climate-chart').innerHTML = barChart(data.forecast.climatology, 'rainfall_mm', (r) => months[r.month - 1]);
  renderRanking(data.ranking);
  renderAnalysis(data);
  renderForecast(data);
  renderFiles(data.files);
  renderRunHistory(data.runs);
  $('row-hourly').textContent = `${fmt(data.counts.hourly_rows)} แถว`;
  $('row-daily').textContent = `${fmt(data.counts.daily_rows)} แถว`;
  $('row-provinces').textContent = `${fmt(data.counts.province_count)} จังหวัด`;
  if (data.latest_run) {
    $('run-status').textContent = data.latest_run.status === 'SUCCESS' ? 'ทำงานสำเร็จ' : 'งานล้มเหลว';
    $('run-status').style.color = data.latest_run.status === 'SUCCESS' ? 'var(--teal)' : 'var(--danger)';
    $('run-date').textContent = `รอบข้อมูลถึง ${data.latest_run.target_date}`;
    $('run-new-hourly').textContent = fmt(data.latest_run.new_hourly_rows);
    $('run-updated').textContent = fmt(data.latest_run.updated_hourly_rows);
    $('run-new-daily').textContent = fmt(data.latest_run.new_daily_rows);
  } else {
    $('run-status').textContent = 'ยังไม่มีประวัติรอบใหม่';
  }
}

async function load() {
  $('refresh').disabled = true;
  $('error').classList.add('hidden');
  try {
    const selected = $('province').value;
    const response = await fetch(`/api/dashboard${selected ? `?province_id=${encodeURIComponent(selected)}` : ''}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`ไม่สามารถอ่านข้อมูลได้ (${response.status})`);
    render(await response.json());
  } catch (error) {
    $('error').textContent = `${error.message} กรุณาตรวจว่า Docker Desktop และฐานข้อมูล PostgreSQL เปิดอยู่`;
    $('error').classList.remove('hidden');
    $('asof').textContent = 'เชื่อมต่อข้อมูลไม่ได้';
  } finally { $('refresh').disabled = false; }
}

document.querySelectorAll('.nav-item').forEach((item) => item.addEventListener('click', () => setView(item.dataset.view)));
$('province').addEventListener('change', load);
$('analysis-province').addEventListener('change', () => { $('province').value = $('analysis-province').value; load(); });
$('refresh').addEventListener('click', load);
load();
