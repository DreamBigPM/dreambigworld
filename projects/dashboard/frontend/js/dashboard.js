/* ============================================================
   Dream Big Property Management — KPI Dashboard
   dashboard.js  — vanilla JS only, no frameworks
   ============================================================ */

/* --- Refresh Button --------------------------------------- */
(function () {
  const btn = document.getElementById('btn-refresh');
  const ts  = document.getElementById('last-updated');
  if (!btn || !ts) return;

  btn.addEventListener('click', function () {
    btn.classList.add('spinning');
    btn.disabled = true;

    setTimeout(function () {
      btn.classList.remove('spinning');
      btn.disabled = false;
      const now = new Date();
      ts.textContent = 'Last updated: just now';
      setTimeout(function () {
        ts.textContent = 'Last updated: 1 minute ago';
      }, 60000);
    }, 2000);
  });
})();

/* --- Alert Clear Buttons ---------------------------------- */
document.addEventListener('click', function (e) {
  const clearBtn = e.target.closest('.btn-clear');
  if (!clearBtn) return;

  const alertItem = clearBtn.closest('.alert-item');
  if (!alertItem) return;

  alertItem.classList.add('fade-out');
  setTimeout(function () {
    alertItem.remove();
    updateAlertCount();
  }, 350);
});

function updateAlertCount() {
  const remaining = document.querySelectorAll('.alert-item').length;
  const countEl = document.getElementById('alert-count');
  if (countEl) {
    countEl.textContent = remaining + ' active';
    if (remaining === 0) {
      const list = document.querySelector('.alerts-list');
      if (list) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:14px;">No active alerts. Nice work.</div>';
      }
    }
  }
}

/* --- Property Modal --------------------------------------- */
const PROPERTY_DATA = {
  'riverside-arms': {
    name: 'Riverside Arms',
    address: '4218 Magnolia Ave, Riverside, CA 92501',
    owner: 'Riverside Arms LLC',
    units: 18,
    occupied: 16,
    occupancy: '88.9%',
    openWOs: 12,
    overdueWOs: 10,
    lastInspection: 'Nov 15, 2025',
    daysSince: '223 days',
    revenue: '$15,400/mo',
    status: 'RED — 2 vacancies'
  },
  'corona-pines': {
    name: 'Corona Pines',
    address: '1075 Eagle Glen Pkwy, Corona, CA 92883',
    owner: 'Desert Capital Group',
    units: 24,
    occupied: 24,
    occupancy: '100%',
    openWOs: 8,
    overdueWOs: 6,
    lastInspection: 'Mar 3, 2026',
    daysSince: '115 days',
    revenue: '$28,800/mo',
    status: 'GREEN — fully occupied'
  },
  'moreno-commons': {
    name: 'Moreno Valley Commons',
    address: '23800 Sunnymead Blvd, Moreno Valley, CA 92553',
    owner: 'SoCal Rentals Trust',
    units: 32,
    occupied: 30,
    occupancy: '93.8%',
    openWOs: 19,
    overdueWOs: 17,
    lastInspection: 'Sep 10, 2025',
    daysSince: '289 days',
    revenue: '$38,400/mo',
    status: 'YELLOW — 2 vacancies'
  },
  'fontana-ridge': {
    name: 'Fontana Ridge',
    address: '9801 Sierra Ave, Fontana, CA 92335',
    owner: 'Inland Valley Holdings',
    units: 16,
    occupied: 15,
    occupancy: '93.8%',
    openWOs: 11,
    overdueWOs: 9,
    lastInspection: 'Oct 22, 2025',
    daysSince: '247 days',
    revenue: '$20,700/mo',
    status: 'YELLOW — 1 vacancy'
  }
};

function openPropertyModal(key) {
  const data = PROPERTY_DATA[key];
  if (!data) return;

  document.getElementById('modal-prop-name').textContent    = data.name;
  document.getElementById('modal-prop-address').textContent = data.address;
  document.getElementById('modal-prop-owner').textContent   = data.owner;
  document.getElementById('modal-prop-units').textContent   = data.occupied + ' / ' + data.units;
  document.getElementById('modal-prop-occ').textContent     = data.occupancy;
  document.getElementById('modal-prop-wos').textContent     = data.openWOs + ' open (' + data.overdueWOs + ' overdue)';
  document.getElementById('modal-prop-insp').textContent    = data.lastInspection + ' (' + data.daysSince + ')';
  document.getElementById('modal-prop-rev').textContent     = data.revenue;
  document.getElementById('modal-prop-status').textContent  = data.status;

  document.getElementById('property-modal').classList.add('open');
}

document.addEventListener('click', function (e) {
  const link = e.target.closest('.tbl-link');
  if (link && link.dataset.property) {
    e.preventDefault();
    openPropertyModal(link.dataset.property);
  }
});

document.addEventListener('click', function (e) {
  if (e.target.id === 'property-modal' || e.target.closest('.modal-close')) {
    document.getElementById('property-modal').classList.remove('open');
  }
});

/* --- Renewal "Start" Button / Toast ----------------------- */
document.addEventListener('click', function (e) {
  const btn = e.target.closest('.btn-start-renewal');
  if (!btn) return;

  const unit   = btn.dataset.unit   || 'the unit';
  const tenant = btn.dataset.tenant || 'tenant';
  showToast('Renewal workflow started for ' + tenant + ' — ' + unit);

  btn.textContent = 'Sent';
  btn.classList.add('disabled');
  btn.disabled = true;
});

function showToast(msg) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(function () { toast.classList.remove('show'); }, 3200);
}

/* --- Sparkline SVG helper --------------------------------- */
function drawSparkline(canvasId, values, color) {
  const el = document.getElementById(canvasId);
  if (!el) return;

  const w = 140, h = 28, pad = 2;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const pts = values.map(function (v, i) {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return x.toFixed(1) + ',' + y.toFixed(1);
  });

  el.innerHTML =
    '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
    '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + (color || '#1e3a5f') + '" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg>';
}

/* Draw all sparklines on load */
window.addEventListener('DOMContentLoaded', function () {
  // Rent collected (trending slightly down — bad)
  drawSparkline('spark-rent',   [98.1, 97.8, 97.2, 96.4, 95.8, 95.1, 94.2, 93.8, 93.4, 93.0], '#ef4444');
  // Occupancy (stable around 94%)
  drawSparkline('spark-occ',    [95.0, 94.8, 95.0, 94.5, 94.2, 94.1, 94.3, 94.1, 94.0, 94.1], '#f59e0b');
  // Days on market (climbing — very bad)
  drawSparkline('spark-dom',    [28, 34, 42, 55, 68, 82, 91, 104, 112, 120], '#ef4444');
  // Renewal rate (gradually improving)
  drawSparkline('spark-renewal',[84, 84, 85, 86, 86, 87, 87, 88, 88, 88], '#f59e0b');
  // Speed of repair (worsening)
  drawSparkline('spark-sor',    [4.1, 5.2, 6.8, 8.1, 9.4, 10.8, 11.9, 13.1, 14.0, 14.2], '#ef4444');
  // Maintenance satisfaction (stable green)
  drawSparkline('spark-maint',  [70, 71, 72, 71, 73, 72, 72, 71, 72, 72], '#22c55e');
  // Google rating (stable perfect)
  drawSparkline('spark-google', [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0], '#22c55e');
});
