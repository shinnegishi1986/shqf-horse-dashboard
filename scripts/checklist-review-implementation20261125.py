#!/usr/bin/env python3
# scripts/checklist-review-implementation20261125.py
#
# Stop Streamlit before running:
# python scripts/checklist-review-implementation20261125.py app.py
#
# Requires the Checklist Review structure from the uploaded app.
# Creates a verified timestamped source backup and validates AST changes.
# Does not import/execute app.py, modify the database, or change filter logic.
#
# Count charts: new checkbox identity, unchecked initially, user may enable it.
# Prize table: numeric values plus display-only NumberColumn yen formatting.
# Native table sorting affects the displayed page; use Show all for all rows.
# Trend: all matching rows before pagination; daily total/per-checklist modes.
# 28-day trends use observed days only; per-checklist trend is record-weighted.
# Missing observations are not zero-filled. Future dates are excluded (JST).
# Touch selection uses the plot area, not tiny dots; vertical dragging scrolls.
# Browser/device validation is still required after deployment.

RUNTIME = r'''
# CHECKLIST_REVIEW_IMPLEMENTATION_20261125_V1

def _crp_number(value):
    import math
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("¥", "").replace("￥", "")
        if value.upper().startswith("JPY"):
            value = value[3:].strip()
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _crp_review_table(data, **kwargs):
    import pandas as pd
    frame = data.copy()
    config = dict(kwargs.pop("column_config", {}) or {})
    for column in frame.columns:
        if str(column).startswith("Prize"):
            frame[column] = pd.Series([_crp_number(v) for v in frame[column]], index=frame.index, dtype="float64")
            config[column] = st.column_config.NumberColumn(
                str(column), format="yen",
                help="Numeric JPY. Header sorting applies to this displayed page. Choose Show all to sort all filtered results.",
            )
    return st.dataframe(frame, column_config=config, **kwargs)


def _crp_pack(records, today):
    import math
    from collections import defaultdict, deque
    from datetime import datetime, timedelta
    daily = defaultdict(list)
    stats = {"records": len(records), "valid": 0, "missing": 0, "invalid": 0, "bad_date": 0, "future": 0}
    for entry in records:
        day = parse_race_date(entry.get("date_of_race"))
        if isinstance(day, datetime):
            day = day.date()
        if day is None:
            stats["bad_date"] += 1
            continue
        if day > today:
            stats["future"] += 1
            continue
        raw = entry.get("prize")
        if raw is None or isinstance(raw, str) and not raw.strip():
            stats["missing"] += 1
            continue
        prize = _crp_number(raw)
        if prize is None or prize < 0:
            stats["invalid"] += 1
            continue
        daily[day].append(prize)
        stats["valid"] += 1
    points = []
    window = deque()
    for day in sorted(daily):
        total = math.fsum(daily[day])
        count = len(daily[day])
        window.append((day, total, count))
        first = day-timedelta(days=27)
        while window and window[0][0] < first:
            window.popleft()
        window_total = math.fsum(row[1] for row in window)
        window_count = sum(row[2] for row in window)
        values = [total, total/count, window_total/window_count, window_total/len(window)]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Prize values exceed the supported chart range.")
        points.append({
            "date": day.isoformat(), "total": total, "count": count, "mean": total/count,
            "rolling_mean": window_total/window_count, "rolling_total": window_total/len(window),
            "window_count": window_count, "window_days": len(window),
        })
    stats["total"] = math.fsum(point["total"] for point in points)
    if not math.isfinite(stats["total"]):
        raise ValueError("Prize values exceed the supported chart range.")
    stats["latest"] = points[-1]["date"] if points else None
    stats["age"] = (today-parse_race_date(stats["latest"])).days if points else None
    stats["recent_count"] = sum(point["count"] for point in points if parse_race_date(point["date"]) >= today-timedelta(days=27))
    return {"points": points, "stats": stats}


def _crp_render_trend(owner_id, first_records, second_records=None, second_enabled=False):
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import streamlit.components.v1 as components
    if not first_records and not (second_enabled and second_records):
        return
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    try:
        first = _crp_pack(first_records, today)
        first.update(name="First filter", color="#82b0ff")
        series = [first]
        if second_enabled:
            second = _crp_pack(second_records if second_records is not None else [], today)
            second.update(name="Second filter", color="#61d8bd")
            series.append(second)
    except (ValueError, OverflowError) as error:
        st.error(str(error))
        return
    if not any(item["points"] for item in series):
        st.info("Prize trend: no dated, nonnegative prize values are available for the current conditions through today. Zero prizes are included; missing prizes are not treated as zero.")
        return
    payload = json.dumps({"series": series, "today": today.isoformat()}, ensure_ascii=True, allow_nan=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    components.html(_CRP_HTML.replace("__CRP_DATA__", payload, 1), height=820, scrolling=True)


_CRP_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<style>
:root{color-scheme:dark;--bg:#0c1322;--panel:#121e32;--line:#2b3a52;--text:#edf3ff;--muted:#a1b2cb}*{box-sizing:border-box}[hidden]{display:none!important}
html,body{margin:0;background:var(--bg);color:var(--text);font:13px/1.5 Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums;-webkit-text-size-adjust:100%}body{padding:18px}
header{display:flex;justify-content:space-between;align-items:start;gap:12px}.eyebrow{font-size:10px;letter-spacing:.14em;color:#9abaff;font-weight:650}.title{font-size:22px;font-weight:650;letter-spacing:-.025em;margin:3px 0}.muted{color:var(--muted);font-size:11px}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:16px 0}.card{border:1px solid var(--line);border-radius:12px;padding:12px;background:linear-gradient(135deg,#172640,#111c2f);min-height:88px}.value{font-size:21px;font-weight:650;letter-spacing:-.025em;margin:6px 0;overflow-wrap:anywhere}.small{font-size:11px;color:var(--muted)}
button{font:inherit;min-height:44px;padding:8px 12px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;cursor:pointer;touch-action:manipulation}button:focus-visible{outline:2px solid #a9c4ff;outline-offset:2px}.controls{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.modes{display:flex;gap:4px}.mode[aria-pressed=true]{background:#284e82;border-color:#769ede}.mode{font-size:12px}.legend{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 5px}.legend span{font-size:11px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.hint{font-size:11px;color:var(--muted);margin:5px 0 10px}.plot{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:4px}svg{display:block;width:100%;height:350px;touch-action:pan-y pinch-zoom}#details{margin-top:12px;border:1px solid var(--line);border-radius:12px;padding:12px;background:var(--panel)}.detail-title{font-size:13px;font-weight:650;margin-bottom:8px}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.scope{padding:0 6px}.scope-name{font-weight:600;margin-bottom:5px}.detail-row{display:flex;justify-content:space-between;gap:12px;font-size:11px;margin:3px 0}.detail-row span:first-child{color:var(--muted)}.detail-row span:last-child{text-align:right;overflow-wrap:anywhere}.method{border-top:1px solid var(--line);margin-top:12px;padding-top:12px;font-size:11px;color:var(--muted)}.method p{margin:6px 0}.footer{font-size:10px;color:var(--muted);margin-top:10px}#about{font-size:11px}#quality{margin-top:8px}
@media(max-width:520px){body{padding:12px}.title{font-size:19px}.cards{gap:6px}.card{padding:8px}.value{font-size:16px}.detail-grid{grid-template-columns:1fr;gap:10px}svg{height:320px}.modes button{padding:8px;font-size:11px}}
</style></head><body>
<header><div><div class="eyebrow">CONDITION MONITOR</div><div class="title">Prize over time</div><div class="muted">All matching records before pagination · race dates oldest to newest</div></div><button id="about" type="button" aria-expanded="false">About</button></header>
<div class="cards"><div class="card"><div class="small" id="focusLabel"></div><div class="value" id="prize"></div><div class="small">Recorded prize · selected scope</div></div><div class="card"><div class="small">Valid-prize checklists</div><div class="value" id="count"></div><div class="small" id="recent"></div></div><div class="card"><div class="small">Latest valid match</div><div class="value" id="latest"></div><div class="small" id="age"></div></div></div>
<div class="controls"><div class="modes" aria-label="Prize metric"><button type="button" class="mode" id="totalMode" aria-pressed="true">Daily total</button><button type="button" class="mode" id="meanMode" aria-pressed="false">Per checklist</button></div><span id="metricLabel" class="muted"></span></div>
<div id="legend" class="legend"></div><div class="hint">Solid: observed race-day value · Dashed: trailing 28-day trend · Tap or hover for values; arrow keys browse dates.</div>
<div class="plot"><svg id="chart" role="img" tabindex="0" aria-label="Matching checklist prizes by race date, oldest on the left and latest on the right"></svg></div>
<div id="details" role="status" aria-live="polite"></div>
<div id="method" class="method" hidden><p>Daily total adds valid saved prizes on each race date. Per checklist divides that total by the number of valid-prize checklists on that date, reducing the effect of changing record counts.</p><p>The dashed trend uses the 28 calendar days ending on each observed date, including that date. In Daily total view it is the average of recorded race-day totals in that window. In Per checklist view it is the record-weighted mean prize in that window. It uses past and current observations only.</p><p>Zero prizes are valid. Missing, invalid, negative, non-finite and future-dated values are excluded. Days without valid observations are not invented as zero. Dotted connectors span dates more than one day apart and are not observations.</p><p>All already-filtered finishing places are included, with no additional top-three restriction. Second-filter results are a subset, not an extra amount to add to the first filter. This is a historical descriptive view, not a forecast or betting ROI.</p><div id="quality"></div></div>
<div class="footer">Latest-match age and recent counts use today's date in Japan. Review sample size and recency alongside prize levels.</div>
<script>
"use strict";
const data=__CRP_DATA__,svg=document.getElementById('chart'),details=document.getElementById('details'),ns='http://www.w3.org/2000/svg',byId=id=>document.getElementById(id),DAY=86400000;
const money=v=>'JPY '+new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(v),num=v=>new Intl.NumberFormat().format(v),time=date=>Date.parse(date+'T00:00:00Z');
const dates=Array.from(new Set(data.series.flatMap(s=>s.points.map(p=>p.date)))).sort();
const times=dates.map(time);data.series.forEach(s=>s.lookup=new Map(s.points.map(p=>[p.date,p])));
const focus=data.series[data.series.length-1],stats=focus.stats;
byId('focusLabel').textContent=focus.name;byId('prize').textContent=money(stats.total);byId('count').textContent=num(stats.valid);byId('recent').textContent=num(stats.recent_count)+' in the last 28 days';byId('latest').textContent=stats.latest||'No valid match';byId('age').textContent=stats.age===null?'No dated prize data':num(stats.age)+' day(s) ago';
data.series.forEach(s=>{const item=document.createElement('span'),dot=document.createElement('i');dot.className='dot';dot.style.background=s.color;item.append(dot,document.createTextNode(s.name));byId('legend').appendChild(item);const p=document.createElement('p');p.textContent=s.name+': '+num(s.stats.valid)+' valid / '+num(s.stats.records)+' matching; excluded '+num(s.stats.missing)+' missing prize, '+num(s.stats.invalid)+' invalid prize, '+num(s.stats.bad_date)+' invalid date, '+num(s.stats.future)+' future-dated.';byId('quality').appendChild(p)});
let mode='total',active=dates.length-1,pinned=false,geometry=null,cross=null,dots=[],down=null,resizeTimer=null;
function el(tag,attrs,text,parent=svg){const node=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,String(v)));if(text!==undefined)node.textContent=text;parent.appendChild(node);return node}
function text(parent,tag,value,cls){const node=document.createElement(tag);if(cls)node.className=cls;node.textContent=value;parent.appendChild(node);return node}
function row(parent,key,value){const r=document.createElement('div');r.className='detail-row';text(r,'span',key);text(r,'span',value);parent.appendChild(r)}
function valuesAt(date){return data.series.map(s=>({series:s,point:s.lookup.get(date)}))}
function show(index){active=Math.max(0,Math.min(dates.length-1,index));if(!geometry)return;const date=dates[active],x=geometry.x(times[active]);cross.setAttribute('x1',x);cross.setAttribute('x2',x);dots.forEach(dot=>dot.remove());dots=[];valuesAt(date).forEach(({series,point})=>{if(point)dots.push(el('circle',{cx:x,cy:geometry.y(point[mode]),r:5,fill:series.color,stroke:'#edf3ff','stroke-width':2,'pointer-events':'none'}))});details.replaceChildren();text(details,'div',date+' · '+(mode==='total'?'Daily prize totals':'Mean prize per valid checklist'),'detail-title');const grid=document.createElement('div');grid.className='detail-grid';valuesAt(date).forEach(({series,point})=>{const panel=document.createElement('div');panel.className='scope';const title=text(panel,'div',series.name,'scope-name');title.style.color=series.color;if(!point){text(panel,'div','No valid observation on this date.','muted')}else{row(panel,'Daily total',money(point.total));row(panel,'Valid checklists',num(point.count));row(panel,'Mean / checklist',money(point.mean));row(panel,'28-day trend',money(point[mode==='total'?'rolling_total':'rolling_mean']));row(panel,'Trend sample',num(point.window_count)+' checklists / '+num(point.window_days)+' observed days')}grid.appendChild(panel)});details.appendChild(grid)}
function draw(){svg.replaceChildren();dots=[];const width=Math.max(280,svg.clientWidth||720),height=svg.clientHeight||350,left=64,right=15,top=26,bottom=43,w=width-left-right,h=height-top-bottom;let min=times[0],max=times[times.length-1];if(min===max){min-=DAY;max+=DAY}let largest=1;data.series.forEach(s=>s.points.forEach(p=>{largest=Math.max(largest,p[mode],p[mode==='total'?'rolling_total':'rolling_mean'])}));largest*=1.12;const x=t=>left+(t-min)/(max-min)*w,y=v=>top+h-v/largest*h;geometry={x,y,left,right:width-right,width,min,max};svg.setAttribute('viewBox','0 0 '+width+' '+height);
for(let i=0;i<=4;i++){const value=largest*i/4,yy=y(value);el('line',{x1:left,x2:width-right,y1:yy,y2:yy,stroke:'#2a3a52','stroke-width':1});el('text',{x:left-8,y:yy+4,'text-anchor':'end',fill:'#a5b5cd','font-size':10},new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1}).format(value))}el('text',{x:left,y:15,fill:'#a5b5cd','font-size':10},'JPY');
let ticks=dates.length===1?[times[0]]:[0,1,2,3,4].map(i=>min+(max-min)*i/4),labels=new Set();ticks.forEach(t=>{const label=new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',year:'2-digit',timeZone:'UTC'}).format(new Date(t));if(labels.has(label))return;labels.add(label);el('text',{x:x(t),y:height-14,'text-anchor':t===min?'start':t===max?'end':'middle',fill:'#a5b5cd','font-size':10},label)});
data.series.forEach(s=>{const trend=s.points.map((p,i)=>(i?'L':'M')+x(time(p.date))+','+y(p[mode==='total'?'rolling_total':'rolling_mean'])).join(' ');el('path',{d:trend,fill:'none',stroke:s.color,'stroke-width':2,'stroke-dasharray':'7 5',opacity:.55});for(let i=1;i<s.points.length;i++){const a=s.points[i-1],b=s.points[i];el('line',{x1:x(time(a.date)),y1:y(a[mode]),x2:x(time(b.date)),y2:y(b[mode]),stroke:s.color,'stroke-width':2.2,'stroke-dasharray':time(b.date)-time(a.date)>DAY?'2 5':'none',opacity:.95})}if(s.points.length===1){const p=s.points[0];el('circle',{cx:x(time(p.date)),cy:y(p[mode]),r:4,fill:s.color})}});
cross=el('line',{x1:left,x2:left,y1:top,y2:top+h,stroke:'#d6e3ff','stroke-dasharray':'3 4','stroke-width':1,'pointer-events':'none'});el('rect',{x:left,y:top,width:w,height:h,fill:'transparent','pointer-events':'all'});byId('metricLabel').textContent=mode==='total'?'JPY per observed race day':'JPY per valid checklist';show(active)}
function nearest(clientX){const rect=svg.getBoundingClientRect(),position=(clientX-rect.left)*geometry.width/rect.width,t=geometry.min+(Math.max(geometry.left,Math.min(geometry.right,position))-geometry.left)/(geometry.right-geometry.left)*(geometry.max-geometry.min);let lo=0,hi=times.length-1;while(lo<hi){const mid=Math.floor((lo+hi)/2);if(times[mid]<t)lo=mid+1;else hi=mid}return lo>0&&Math.abs(times[lo-1]-t)<Math.abs(times[lo]-t)?lo-1:lo}
svg.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'&&!pinned)show(nearest(e.clientX))});svg.addEventListener('pointerdown',e=>{down={x:e.clientX,y:e.clientY}});svg.addEventListener('pointerup',e=>{if(down&&Math.abs(e.clientX-down.x)<12&&Math.abs(e.clientY-down.y)<12){pinned=true;show(nearest(e.clientX))}down=null});svg.addEventListener('pointercancel',()=>down=null);svg.addEventListener('pointerleave',()=>{if(!pinned)show(dates.length-1)});svg.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();pinned=true;show(active+(e.key==='ArrowLeft'?-1:1))}if(e.key==='Escape'){pinned=false;show(dates.length-1)}});
function setMode(next){mode=next;byId('totalMode').setAttribute('aria-pressed',String(mode==='total'));byId('meanMode').setAttribute('aria-pressed',String(mode==='mean'));draw()}byId('totalMode').addEventListener('click',()=>setMode('total'));byId('meanMode').addEventListener('click',()=>setMode('mean'));byId('about').addEventListener('click',()=>{const panel=byId('method');panel.hidden=!panel.hidden;byId('about').setAttribute('aria-expanded',String(!panel.hidden))});window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,100)});draw();
</script></body></html>"""
'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

MARKER = "# CHECKLIST_REVIEW_IMPLEMENTATION_20261125_V1"


def function(tree, name):
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(found) != 1:
        raise ValueError(f"Expected one {name}; found {len(found)}.")
    return found[0]


def start_line(node):
    return min([node.lineno]+[d.lineno for d in node.decorator_list])-1


def is_st_call(node, method):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "st" and node.func.attr == method


def patch_source(source):
    tree = ast.parse(source)
    if MARKER in source:
        for name in ("_crp_number", "_crp_review_table", "_crp_render_trend"):
            function(tree, name)
        return source, False
    if any(isinstance(n, ast.FunctionDef) and n.name.startswith("_crp_") for n in tree.body):
        raise ValueError("Conflicting review implementation helpers already exist.")
    if any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_CRP_HTML" for t in n.targets) for n in tree.body):
        raise ValueError("Conflicting prize-chart HTML already exists.")
    summary = function(tree, "build_summary_dataframe")
    arrow = function(tree, "_review_arrow_safe_summary")
    counts = function(tree, "render_review_stacked_count_charts")
    review = function(tree, "render_checklist_review_page")
    main = function(tree, "main")
    function(tree, "parse_race_date")
    prize_fields = [(n,i,k.value) for n in ast.walk(summary) if isinstance(n, ast.Dict)
                    for i,k in enumerate(n.keys) if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value.startswith("Prize")]
    if len(prize_fields) != 1:
        raise ValueError("Cannot uniquely identify the displayed checklist Prize field.")
    dictionary, index, prize_column = prize_fields[0]
    if not any(isinstance(n, ast.Name) and n.id == "entry" for n in ast.walk(dictionary.values[index])):
        raise ValueError("Unexpected Prize source expression.")
    dictionary.values[index] = ast.parse("_crp_number(entry.get('prize'))", mode="eval").body
    numeric_sets = [n.value for n in ast.walk(arrow) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "numeric_columns" for t in n.targets) and isinstance(n.value, ast.Set)]
    if len(numeric_sets) != 1:
        raise ValueError("Cannot identify the review table's numeric-column conversion.")
    numeric_sets[0].elts.append(ast.Constant(value=prize_column))
    toggles = [n for n in counts.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "show_charts" for t in n.targets) and is_st_call(n.value,"checkbox")]
    if len(toggles) != 1:
        raise ValueError("Cannot identify the combined count-chart checkbox.")
    toggle = toggles[0].value
    default = [k for k in toggle.keywords if k.arg == "value"]
    keys = [k for k in toggle.keywords if k.arg == "key"]
    if len(default) != 1 or len(keys) != 1:
        raise ValueError("Unexpected count-chart checkbox configuration.")
    default[0].value = ast.Constant(value=False)
    keys[0].value = ast.parse("f'review_stacked_count_charts_visible_20261125_{owner_id}'", mode="eval").body
    headings = [n for n in counts.body if isinstance(n, ast.Expr) and is_st_call(n.value,"subheader")]
    guards = [n for n in counts.body if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp)
              and isinstance(n.test.op, ast.Not) and isinstance(n.test.operand, ast.Name)
              and n.test.operand.id == "show_charts" and any(isinstance(item, ast.Return) for item in n.body)]
    if len(headings) != 1 or len(guards) != 1:
        raise ValueError("Cannot safely reposition the hidden count-chart heading.")
    counts.body.remove(headings[0])
    counts.body.insert(counts.body.index(guards[0])+1, headings[0])
    tables = [n for n in ast.walk(review) if is_st_call(n,"dataframe") and len(n.args) == 1
              and isinstance(n.args[0], ast.Name) and n.args[0].id == "summary_df"]
    if len(tables) != 1:
        raise ValueError("Cannot identify the Checklist Review results table.")
    tables[0].func = ast.Name(id="_crp_review_table", ctx=ast.Load())
    anchors = [n for n in review.body if isinstance(n, ast.Expr) and is_st_call(n.value,"subheader")
               and n.value.args and isinstance(n.value.args[0], ast.Constant) and n.value.args[0].value == "Filtered Checklists"]
    if len(anchors) != 1:
        raise ValueError("Cannot find the insertion point before Filtered Checklists.")
    trend = ast.parse("_crp_render_trend(owner_id, first_filtered_checklists, second_filtered_checklists, second_filter_enabled)").body[0]
    review.body.insert(review.body.index(anchors[0]), trend)
    helpers = ast.parse(RUNTIME).body
    position = tree.body.index(main)
    tree.body[position:position] = helpers
    edits = []
    for node in (summary, arrow, counts, review):
        ast.fix_missing_locations(node)
        edits.append((start_line(node), node.end_lineno, ast.unparse(node)+"\n\n"))
    edits.append((start_line(main), start_line(main), RUNTIME.strip()+"\n\n"))
    edits.sort()
    if any(right[0] < left[1] for left,right in zip(edits,edits[1:])):
        raise ValueError("Overlapping source edits.")
    lines = source.splitlines(keepends=True)
    for begin,end,text in reversed(edits):
        lines[begin:end] = [text]
    updated = "".join(lines)
    compile(updated, "<checklist-review-20261125>", "exec")
    if ast.dump(ast.parse(updated), include_attributes=False) != ast.dump(tree, include_attributes=False):
        raise ValueError("Unexpected changes outside the intended Checklist Review update.")
    return updated, True


def main():
    parser = argparse.ArgumentParser(description="Update Checklist Review count-chart defaults, numeric prize sorting and touch-friendly prize trends.")
    parser.add_argument("app_file", nargs="?", default="app.py")
    app = Path(parser.parse_args().app_file).resolve()
    if not app.is_file():
        raise SystemExit(f"Application file not found: {app}")
    original = app.read_bytes()
    try:
        updated, changed = patch_source(original.decode("utf-8-sig"))
    except Exception as error:
        raise SystemExit(f"Validation failed. Application was not changed.\n{error}") from error
    if not changed:
        print("The Checklist Review 20261125 update is already installed.")
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = app.with_name(f"{app.name}.before-review-20261125-{stamp}.bak")
    temporary = None
    try:
        if app.read_bytes() != original:
            raise RuntimeError("Application source changed during validation. Retry.")
        shutil.copy2(app, backup)
        if backup.read_bytes() != original:
            raise RuntimeError("Source backup verification failed.")
        encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline="\n", dir=app.parent,
                                         prefix=f".{app.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated)
        shutil.copymode(app, temporary)
        if app.read_bytes() != original:
            raise RuntimeError("Application source changed before replacement. Retry.")
        temporary.replace(app)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(f"Updated application: {app}")
    print(f"Source backup: {backup}")
    print("Combined venue/jockey/trainer/stallion count charts now start unchecked.")
    print("Prize remains numeric; yen formatting is display-only.")
    print("Table header sorting applies to the displayed page; Show all enables sorting all filtered results.")
    print("Added full-filter-history prize trends before pagination, including second-filter comparison when enabled.")
    print("No database records, filter logic, checklist update logic, menu permissions or pagination were changed.")
    print("Restart Streamlit and reopen Checklist Review.")


if __name__ == "__main__":
    main()
