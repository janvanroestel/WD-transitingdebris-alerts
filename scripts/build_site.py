"""
Generate docs/index.html with interactive Plotly light curves.
Data is embedded as JSON; plots are built client-side with Plotly.js
to support toggling between flux/mag and normalized/raw views.
"""

import os
import json
import datetime
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FP_DIR = os.path.join(BASE_DIR, "data", "forcedphot")
ALERTS_DIR = os.path.join(BASE_DIR, "data", "alerts")
OBJECT_GROUPS = [
    ("new", "van Roestel et al. 2026", os.path.join(BASE_DIR, "objects_new.csv")),
    ("known", "Other debris systems", os.path.join(BASE_DIR, "objects_known.csv")),
]
OUTPUT_DIR = os.path.join(BASE_DIR, "docs")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def slim_data(data):
    """Keep only mjd, mag, mag_unc, filter. Convert JD to MJD, round to 7 decimals."""
    if not data or not data.get("jd"):
        return data
    return {
        "mjd": [round(j - 2400000.5, 7) for j in data["jd"]],
        "mag": data["mag"],
        "mag_unc": data["mag_unc"],
        "filter": data["filter"],
    }


def main():
    all_data = []
    plot_idx = 0
    for group_id, group_label, csv_path in OBJECT_GROUPS:
        if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
            continue
        objects = pd.read_csv(csv_path, header=None, comment="%",
                              names=["name", "ztf_id", "ra_sex", "dec_sex", "mag"],
                              usecols=[0, 1, 2, 3, 4])
        objects = objects.dropna(subset=["name"])

        for _, obj in objects.iterrows():
            name = obj["name"]
            ztf_id = obj["ztf_id"]

            fp = load_json(os.path.join(FP_DIR, f"{name}.json"))
            alert_key = ztf_id if (ztf_id and ztf_id != "-") else name
            alerts = load_json(os.path.join(ALERTS_DIR, f"{alert_key}.json"))

            fp = slim_data(fp)
            alerts = slim_data(alerts)

            fp_last_jd = max(fp["mjd"]) if fp and fp.get("mjd") else None
            alert_last_jd = max(alerts["mjd"]) if alerts and alerts.get("mjd") else None

            all_data.append({
                "name": name,
                "ztf_id": ztf_id,
                "ra_sex": obj["ra_sex"],
                "dec_sex": obj["dec_sex"],
                "group": group_id,
                "fp": fp,
                "alerts": alerts,
                "fp_last_jd": fp_last_jd,
                "alert_last_jd": alert_last_jd,
            })
            plot_idx += 1

    # Collect which groups actually have data
    groups_with_data = []
    for group_id, group_label, _ in OBJECT_GROUPS:
        if any(d["group"] == group_id for d in all_data):
            groups_with_data.append((group_id, group_label))

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    now_mjd = (datetime.datetime.utcnow() - datetime.datetime(1858, 11, 17)).days \
              + (datetime.datetime.utcnow() - datetime.datetime.utcnow().replace(
                  hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 86400
    cutoff_mjd = now_mjd - 14  # two weeks

    # Build recent alerts summary
    recent_alerts = []
    for i, obj in enumerate(all_data):
        alerts = obj.get("alerts")
        if not alerts or not alerts.get("mjd"):
            continue
        recent_mjds = [m for m in alerts["mjd"] if m >= cutoff_mjd]
        if not recent_mjds:
            continue
        last_mjd = max(alerts["mjd"])
        days_ago = now_mjd - last_mjd
        if days_ago < 1:
            time_str = f"{days_ago * 24:.0f}h ago"
        else:
            time_str = f"{days_ago:.1f}d ago"
        recent_alerts.append((obj["name"], len(recent_mjds), time_str, days_ago,
                              i, obj["group"]))

    recent_alerts.sort(key=lambda x: x[3])  # most recent first

    if recent_alerts:
        rows = "".join(
            f'<tr><td><a href="#" class="alert-link" data-plot="{idx}" '
            f'data-group="{group}">{name}</a></td>'
            f"<td>{count}</td><td>{time}</td></tr>"
            for name, count, time, _, idx, group in recent_alerts
        )
        recent_html = f"""<div class="recent-alerts">
        <h3>Alerts in the last 2 weeks</h3>
        <table><tr><th>Object</th><th># alerts</th><th>Last alert</th></tr>{rows}</table>
        </div>"""
    else:
        recent_html = '<div class="recent-alerts"><h3>No alerts in the last 2 weeks</h3></div>'

    # Build plot container divs with group attribute
    plot_divs = []
    for i, obj in enumerate(all_data):
        plot_divs.append(
            f'<div class="plot-container" data-group="{obj["group"]}">'
            f'<div id="plot-{i}"></div></div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>White Dwarf Debris Monitor</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #fafafa;
            color: #333;
        }}
        h1 {{
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
        }}
        .subtitle {{
            color: #666;
            margin-top: -10px;
            margin-bottom: 30px;
        }}
        .controls {{
            display: flex;
            gap: 16px;
            align-items: center;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }}
        .toggle-group {{
            display: flex;
            border: 1px solid #ccc;
            border-radius: 6px;
            overflow: hidden;
        }}
        .toggle-btn {{
            padding: 6px 14px;
            border: none;
            background: white;
            cursor: pointer;
            font-size: 14px;
            color: #555;
            transition: background 0.15s, color 0.15s;
        }}
        .toggle-btn.active {{
            background: #333;
            color: white;
        }}
        .toggle-btn:not(:last-child) {{
            border-right: 1px solid #ccc;
        }}
        .tab-bar {{
            display: flex;
            gap: 0;
            margin-bottom: 24px;
            border-bottom: 2px solid #ddd;
        }}
        .tab-btn {{
            padding: 8px 20px;
            border: none;
            background: none;
            cursor: pointer;
            font-size: 15px;
            font-weight: 500;
            color: #888;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: color 0.15s, border-color 0.15s;
        }}
        .tab-btn.active {{
            color: #333;
            border-bottom-color: #333;
        }}
        .plot-container {{
            background: white;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 30px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .recent-alerts {{
            margin-bottom: 24px;
        }}
        .recent-alerts h3 {{
            margin: 0 0 8px 0;
            font-size: 15px;
        }}
        .recent-alerts table {{
            border-collapse: collapse;
            font-size: 14px;
        }}
        .recent-alerts th, .recent-alerts td {{
            padding: 4px 16px 4px 0;
            text-align: left;
        }}
        .recent-alerts th {{
            color: #888;
            font-weight: 500;
        }}
        .alert-link {{
            color: #333;
            text-decoration: underline;
        }}
        .footer {{
            text-align: center;
            color: #999;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }}
    </style>
</head>
<body>
    <h1>White Dwarf Debris Monitor</h1>
    <p class="subtitle">ZTF forced photometry and alert light curves for white dwarfs with transiting debris. ZTF Alerts last queried: {now}. </p>
    
    <p class="subtitle">Notes:<br> If you use this page, please cite van Roestel et al. 2026.<br>
    ZTF forced photometry is updated manually once every few months. The forced photometry does not correct for proper motion which can result in long term trends in the lightcurve.<br> 
    
    This page is inspired by https://zvanderbosch.github.io/debris_monitoring/
    </p>

    {recent_html}

    <div class="tab-bar" id="group-tabs">
        {"".join(f'<button class="tab-btn{" active" if i == 0 else ""}" data-group="{gid}">{glabel}</button>' for i, (gid, glabel) in enumerate(groups_with_data))}
    </div>

    <div class="controls">
        <div class="toggle-group" id="mode-toggle">
            <button class="toggle-btn active" data-mode="norm_flux">Normalised Flux</button>
            <button class="toggle-btn" data-mode="flux">Flux</button>
            <button class="toggle-btn" data-mode="norm_mag">Normalised Mag</button>
            <button class="toggle-btn" data-mode="mag">Magnitude</button>
        </div>
        <div class="toggle-group" id="snr-toggle">
            <button class="toggle-btn active" data-snr="true">Remove low SNR</button>
            <button class="toggle-btn" data-snr="false">Show all</button>
        </div>
    </div>

    {"".join(plot_divs)}

    <div class="footer">
        Data from the Zwicky Transient Facility (ZTF). Circles: forced photometry. Crosses: alerts.
    </div>

<script>
const DATA = {json.dumps(all_data)};

const FILTER_COLORS = {{"ZTF_g": "#2ca02c", "ZTF_r": "#d62728", "ZTF_i": "#ff7f0e"}};
const FILTER_LABELS = {{"ZTF_g": "g", "ZTF_r": "r", "ZTF_i": "i"}};
const FILTERS = ["ZTF_g", "ZTF_r", "ZTF_i"];

let currentMode = "norm_flux";
let filterSNR = true;
let currentGroup = "{groups_with_data[0][0] if groups_with_data else "new"}";

function median(arr) {{
    if (arr.length === 0) return 1;
    const sorted = arr.slice().sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}}

function mjdToDateStr(mjd) {{
    const ms = (mjd - 40587) * 86400000;
    return new Date(ms).toISOString().slice(0, 10);
}}

// Precompute flux, flux_unc, date arrays for each data source
const LN10x04 = 0.4 * Math.LN10;
function enrichSource(src) {{
    if (!src || !src.mjd || src.mjd.length === 0 || src._enriched) return;
    src.flux = src.mag.map(m => Math.pow(10, -0.4 * m));
    src.flux_unc = src.mag.map((m, i) => LN10x04 * src.flux[i] * src.mag_unc[i]);
    src.date = src.mjd.map(mjdToDateStr);
    src._enriched = true;
}}
DATA.forEach(d => {{ enrichSource(d.fp); enrichSource(d.alerts); }});

function getTraces(objData, mode) {{
    const traces = [];

    // Compute per-filter medians from forced photometry (used for normalization)
    const fpFluxMedians = {{}};
    const fpMagMedians = {{}};
    if (objData.fp && objData.fp.mjd) {{
        for (const filt of FILTERS) {{
            const fluxVals = [];
            const magVals = [];
            for (let i = 0; i < objData.fp.filter.length; i++) {{
                if (objData.fp.filter[i] === filt) {{
                    fluxVals.push(objData.fp.flux[i]);
                    magVals.push(objData.fp.mag[i]);
                }}
            }}
            fpFluxMedians[filt] = median(fluxVals);
            fpMagMedians[filt] = median(magVals);
        }}
    }}

    function addTraces(src, srcLabel, symbol, size) {{
        if (!src || !src.mjd || src.mjd.length === 0) return;
        for (const filt of FILTERS) {{
            let idx = [];
            for (let i = 0; i < src.filter.length; i++) {{
                if (src.filter[i] === filt) idx.push(i);
            }}
            if (idx.length === 0) continue;

            // Filter low SNR: remove points with unc > 0.2 * median(value) in current mode
            if (filterSNR) {{
                let vals, uncs;
                if (mode === "mag" || mode === "norm_mag") {{
                    vals = idx.map(i => src.mag[i]);
                    uncs = idx.map(i => src.mag_unc[i]);
                }} else {{
                    vals = idx.map(i => src.flux[i]);
                    uncs = idx.map(i => src.flux_unc[i]);
                }}
                const medVal = median(vals);
                const threshold = 0.2 * Math.abs(medVal);
                idx = idx.filter((_, j) => uncs[j] <= threshold);
                if (idx.length === 0) continue;
            }}

            const x = idx.map(i => src.mjd[i]);
            const dates = idx.map(i => src.date[i]);
            let y, err, hoverTpl;

            if (mode === "mag") {{
                y = idx.map(i => src.mag[i]);
                err = idx.map(i => src.mag_unc[i]);
                hoverTpl = "%{{customdata}}<br>mag=%{{y:.2f}} \u00b1 %{{error_y.array:.2f}}<extra></extra>";
            }} else if (mode === "norm_mag") {{
                const med = fpMagMedians[filt] || median(idx.map(i => src.mag[i]));
                y = idx.map(i => src.mag[i] - med);
                err = idx.map(i => src.mag_unc[i]);
                hoverTpl = "%{{customdata}}<br>\u0394mag=%{{y:.3f}} \u00b1 %{{error_y.array:.3f}}<extra></extra>";
            }} else if (mode === "flux") {{
                y = idx.map(i => src.flux[i]);
                err = idx.map(i => src.flux_unc[i]);
                hoverTpl = "%{{customdata}}<br>flux=%{{y:.4e}} \u00b1 %{{error_y.array:.2e}}<extra></extra>";
            }} else {{
                // norm_flux
                const med = fpFluxMedians[filt] || median(idx.map(i => src.flux[i]));
                y = idx.map(i => src.flux[i] / med);
                err = idx.map(i => src.flux_unc[i] / med);
                hoverTpl = "%{{customdata}}<br>norm flux=%{{y:.3f}} \u00b1 %{{error_y.array:.3f}}<extra></extra>";
            }}

            traces.push({{
                x: x,
                y: y,
                error_y: {{type: "data", array: err, visible: true, thickness: 1, width: 0}},
                mode: "markers",
                marker: {{size: size, color: FILTER_COLORS[filt], symbol: symbol}},
                name: srcLabel + " (" + FILTER_LABELS[filt] + ")",
                customdata: dates,
                hovertemplate: hoverTpl,
                type: "scatter",
            }});
        }}
    }}

    addTraces(objData.fp, "Forced phot", "circle", 3);
    addTraces(objData.alerts, "Alerts", "x", 7);

    return traces;
}}


function getLayout(objData, mode) {{
    let yTitle, reversed;
    if (mode === "mag") {{
        yTitle = "Magnitude";
        reversed = true;
    }} else if (mode === "norm_mag") {{
        yTitle = "\u0394 Magnitude";
        reversed = true;
    }} else if (mode === "flux") {{
        yTitle = "Flux";
        reversed = false;
    }} else {{
        yTitle = "Normalised Flux";
        reversed = false;
    }}

    // Current MJD: MJD epoch is 40587 for Unix epoch (1970-01-01)
    const nowMJD = (Date.now() / 86400000) + 40587;

    const shapes = [{{
        type: "line",
        x0: nowMJD, x1: nowMJD,
        y0: 0, y1: 1,
        yref: "paper",
        line: {{color: "#888", width: 1, dash: "dot"}},
    }}];
    const annotations = [{{
        x: nowMJD, y: 1, yref: "paper", yanchor: "bottom",
        text: "Today", showarrow: false,
        font: {{size: 10, color: "#888"}},
    }}];

    const simbadUrl = "https://simbad.u-strasbg.fr/simbad/sim-coo?Coord=" + encodeURIComponent(objData.ra_sex + " " + objData.dec_sex) + "&Radius=5&Radius.unit=arcsec";
    let titleText = "<a href='" + simbadUrl + "' target='_blank' style='color:inherit;text-decoration:underline'>" + objData.name + "</a>";
    const subtitles = [];
    if (objData.fp_last_jd) subtitles.push("Last FP: " + mjdToDateStr(objData.fp_last_jd));
    if (objData.alert_last_jd) subtitles.push("Last alert: " + mjdToDateStr(objData.alert_last_jd));
    if (subtitles.length) titleText += "  <span style='font-size:12px;color:#888'>" + subtitles.join(" | ") + "</span>";

    return {{
        title: {{text: titleText, font: {{size: 16}}}},
        xaxis: {{title: "MJD"}},
        yaxis: {{title: yTitle, autorange: reversed ? "reversed" : true}},
        shapes: shapes,
        annotations: annotations,
        template: "plotly_white",
        height: 400,
        margin: {{l: 60, r: 30, t: 50, b: 50}},
        legend: {{orientation: "h", yanchor: "bottom", y: 1.02, xanchor: "right", x: 1}},
    }};
}}

function updateVisibility() {{
    document.querySelectorAll(".plot-container").forEach(el => {{
        el.style.display = el.dataset.group === currentGroup ? "" : "none";
    }});
}}

function renderAll() {{
    updateVisibility();
    // Defer plot creation to ensure the browser has reflowed after visibility change
    requestAnimationFrame(function() {{
        for (let i = 0; i < DATA.length; i++) {{
            if (DATA[i].group !== currentGroup) continue;
            const el = document.getElementById("plot-" + i);
            // Purge any existing plot to avoid stale zero-size state
            Plotly.purge(el);
            const traces = getTraces(DATA[i], currentMode);
            const layout = getLayout(DATA[i], currentMode);
            Plotly.newPlot(el, traces, layout, {{responsive: true}});
        }}
    }});
}}

// Toggle buttons
document.getElementById("mode-toggle").addEventListener("click", function(e) {{
    const btn = e.target.closest(".toggle-btn");
    if (!btn) return;
    const mode = btn.dataset.mode;
    if (mode === currentMode) return;
    currentMode = mode;
    document.querySelectorAll("#mode-toggle .toggle-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    renderAll();
}});

document.getElementById("snr-toggle").addEventListener("click", function(e) {{
    const btn = e.target.closest(".toggle-btn");
    if (!btn) return;
    const val = btn.dataset.snr === "true";
    if (val === filterSNR) return;
    filterSNR = val;
    document.querySelectorAll("#snr-toggle .toggle-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    renderAll();
}});

document.getElementById("group-tabs").addEventListener("click", function(e) {{
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    const group = btn.dataset.group;
    if (group === currentGroup) return;
    currentGroup = group;
    document.querySelectorAll("#group-tabs .tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    renderAll();
}});

document.querySelectorAll(".alert-link").forEach(link => {{
    link.addEventListener("click", function(e) {{
        e.preventDefault();
        const group = this.dataset.group;
        const plotIdx = this.dataset.plot;
        if (group !== currentGroup) {{
            currentGroup = group;
            document.querySelectorAll("#group-tabs .tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelector('#group-tabs .tab-btn[data-group="' + group + '"]').classList.add("active");
            renderAll();
        }}
        // Scroll to plot after render
        requestAnimationFrame(function() {{
            document.getElementById("plot-" + plotIdx).scrollIntoView({{behavior: "smooth", block: "center"}});
        }});
    }});
}});

// Initial render
renderAll();
</script>
</body>
</html>"""

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    outpath = os.path.join(OUTPUT_DIR, "index.html")
    with open(outpath, "w") as f:
        f.write(html)
    print(f"Wrote {outpath}")


if __name__ == "__main__":
    main()
