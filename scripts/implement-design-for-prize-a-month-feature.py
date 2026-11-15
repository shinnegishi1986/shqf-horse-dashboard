# scripts/implement-design-for-prize-a-month-feature.py
#
# Requires:
#   scripts/fix-prize-a-month-feature.py
#
# Redesigns the jockey, horse-owner, and trainer comparison UI.
#
# Removes:
#   - Duplicate participant/venue detail selectors
#   - The "Exact prize details" expander
#   - Duplicate summary metrics outside the dashboard
#   - Verbose methodology captions outside tooltips
#
# Keeps:
#   - Existing year/month/period/participant filters
#   - 8/12/20/50/100-bar pagination
#   - All date-range calculations and prize aggregation
#   - Account isolation
#   - Breakdown tables and CSV exports
#
# Adds no new data inputs.
# Summary cards and About totals open read-only tooltips.
#
# Charts/tooltips use an explicit dark design.
# Global Streamlit theme configuration is not changed.
#
# Creates a timestamped source backup.
# Does not change database records or schema.
#
# Stop Streamlit before running:
#
# python scripts/implement-design-for-prize-a-month-feature.py app.py

RUNTIME = r'''
# PRIZE_ANALYTICS_DARK_DESIGN_V1

def _mct_chart(
    chart_rows,
    stats,
    label,
    kind,
    year,
    month,
    *,
    period="Month",
):
    import json
    from datetime import timedelta
    import streamlit.components.v1 as components

    first, end = _mp_dates(year, month, period)
    last = end - timedelta(days=1)
    entities = list(stats["entity_order"])

    if not entities:
        return

    payload = json.dumps(
        {
            "rows": chart_rows,
            "entities": entities,
            "venues": list(stats["venue_order"]),
            "label": label,
            "period": period,
            "dates": (
                f"{first.isoformat()} — {last.isoformat()}"
            ),
            "total": stats["total"],
            "valid": stats["valid"],
            "missing": stats["missing"],
            "invalid": stats["invalid"],
            "invalid_dates": stats["invalid_dates"],
        },
        ensure_ascii=True,
        allow_nan=False,
    )

    payload = (
        payload.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    html = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<style>
:root{
  color-scheme:dark;
  --bg:#0b1120;--panel:#111b2e;--raised:#17243b;
  --line:#27354d;--fg:#edf3ff;--muted:#9aacc7;
  --accent:#8ba9ff;
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{
  margin:0;background:var(--bg);color:var(--fg);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,
    BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-text-size-adjust:100%;
  font-variant-numeric:tabular-nums;
}
body{
  padding:18px 18px 28px;
  -webkit-overflow-scrolling:touch;
}
.header{
  display:flex;justify-content:space-between;
  gap:12px;align-items:flex-start;margin-bottom:18px;
}
.eyebrow{
  font-size:10px;letter-spacing:.16em;
  font-weight:700;color:var(--accent);margin-bottom:6px;
}
.title{
  font-size:22px;font-weight:650;letter-spacing:-.025em;
}
.subtitle{
  font-size:12px;color:var(--muted);
  margin-top:7px;line-height:1.5;
}
button,select{
  font:inherit;color:inherit;
  border:1px solid var(--line);
  background:var(--panel);border-radius:9px;
  min-height:44px;padding:8px 12px;
  touch-action:manipulation;font-size:14px;
}
select{font-size:16px}
button{cursor:pointer}
button:disabled{opacity:.35;cursor:default}
button:hover:not(:disabled){
  border-color:#55729e;background:var(--raised);
}
button:focus-visible,select:focus-visible{
  outline:2px solid #a6baff;outline-offset:3px;
}
.metrics{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:10px;margin-bottom:20px;
}
.metric{
  text-align:left;min-height:95px;padding:15px;
  background:linear-gradient(145deg,#14213a,#101a2d);
  border-radius:13px;
}
.metric-label{
  display:block;font-size:11px;font-weight:500;
  color:var(--muted);margin-bottom:11px;
}
.metric-value{
  display:block;font-size:clamp(17px,2.4vw,25px);
  font-weight:650;letter-spacing:-.03em;
  overflow-wrap:anywhere;
}
.metric:first-child{border-color:#3a547e}
.metric:first-child .metric-value{color:#bbccff}
.chart-panel{
  border:1px solid var(--line);border-radius:14px;
  padding:14px;background:var(--panel);
}
.chart-heading{
  display:flex;justify-content:space-between;
  align-items:center;gap:12px;
}
.section-title{font-size:14px;font-weight:650}
.micro{
  font-size:11px;line-height:1.5;color:var(--muted);
}
.quality{
  font-size:11px;color:#b8c7e3;
  background:transparent;border:none;
  min-height:36px;padding:4px 6px;
}
#legend{
  display:flex;flex-wrap:wrap;
  gap:8px 14px;margin:14px 0 8px;
}
.legend-item{
  display:inline-flex;align-items:center;gap:6px;
  color:#bdcbe0;font-size:11px;overflow-wrap:anywhere;
}
.swatch{
  display:inline-block;width:8px;height:8px;
  border-radius:3px;flex-shrink:0;
}
.toolbar{
  display:flex;flex-wrap:wrap;align-items:center;
  justify-content:space-between;gap:10px;
  margin:12px 0 6px;padding-top:12px;
  border-top:1px solid var(--line);
}
.navigation{
  display:flex;align-items:center;gap:8px;
}
.navigation button{min-width:44px;padding:8px}
.size-label{
  display:flex;gap:8px;align-items:center;
  color:var(--muted);font-size:11px;
}
.size-label select{min-width:70px}
.footer{
  margin-top:12px;border-top:1px solid var(--line);
  padding-top:12px;
}
#axis{display:block;width:100%;height:28px}
.bar-row{
  padding:9px 0 11px;border-top:1px solid #1c2a40;
}
.row-head{
  display:flex;align-items:center;
  justify-content:space-between;gap:10px;
}
.name{
  flex:1;display:flex;gap:10px;align-items:center;
  text-align:left;min-width:0;border:none;
  background:transparent;padding:0;min-height:44px;
}
.name:hover:not(:disabled){
  background:transparent;border-color:transparent;
}
.rank{
  font-size:11px;width:23px;
  color:#7087a9;flex-shrink:0;
}
.entity-name{
  font-size:13px;font-weight:550;overflow-wrap:anywhere;
}
.row-total{
  text-align:right;font-size:13px;font-weight:650;
  max-width:45%;overflow-wrap:anywhere;
}
.bar{
  display:block;width:100%;height:34px;touch-action:pan-y;
}
.segment{cursor:pointer}
.segment:focus{
  outline:none;stroke:#e9f1ff;stroke-width:2;
}
#tip{
  position:absolute;z-index:30;width:390px;
  max-width:calc(100% - 24px);max-height:65vh;
  overflow:auto;-webkit-overflow-scrolling:touch;
  background:#19263d;color:#edf3ff;
  border:1px solid #48638b;border-radius:13px;
  padding:15px;box-shadow:0 16px 50px #0009;
  font-size:12px;line-height:1.6;overflow-wrap:anywhere;
}
#tip strong{
  display:block;font-size:14px;margin:0 52px 4px 0;
}
.close{
  float:right;min-height:36px;
  padding:4px 8px;font-size:11px;
}
.tip-rule{
  border-top:1px solid #344864;margin:10px 0;
}
.tip-line{
  display:flex;justify-content:space-between;
  gap:15px;margin:3px 0;
}
.tip-line span:first-child{color:#aabbd6}
.tip-line span:last-child{
  text-align:right;font-weight:600;
}
.breakdown{
  width:100%;border-collapse:collapse;
  margin-top:9px;font-size:11px;
}
.breakdown th{
  text-align:left;color:#aabbd6;font-weight:500;
  padding:6px 4px;border-bottom:1px solid #344864;
}
.breakdown td{
  padding:6px 4px;border-bottom:1px solid #293b55;
}
.breakdown th:not(:first-child),
.breakdown td:not(:first-child){text-align:right}
.note{
  color:#aabbd6;font-size:11px;margin-top:10px;
}
@media(max-width:650px){
  body{padding:12px}
  .metrics{
    grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;
  }
  .metric{min-height:85px;padding:12px}
  .title{font-size:19px}
  .chart-panel{padding:10px}
  .metric-value{font-size:21px}
  .header{margin-bottom:14px}
}
@media(prefers-reduced-motion:reduce){
  *{scroll-behavior:auto!important}
}
</style>
</head>
<body>
<header class="header">
  <div>
    <div class="eyebrow">PRIZE ANALYTICS</div>
    <div id="title" class="title"></div>
    <div id="subtitle" class="subtitle"></div>
  </div>
  <button
    id="about"
    type="button"
    aria-label="About these totals">
    About totals
  </button>
</header>

<div class="metrics">
  <button type="button" class="metric" id="kpiTotal">
    <span class="metric-label">Recorded prize</span>
    <span class="metric-value" id="total"></span>
  </button>
  <button type="button" class="metric" id="kpiRecords">
    <span class="metric-label">Valid-prize checklists</span>
    <span class="metric-value" id="records"></span>
  </button>
  <button type="button" class="metric" id="kpiNames">
    <span class="metric-label" id="namesLabel"></span>
    <span class="metric-value" id="names"></span>
  </button>
  <button type="button" class="metric" id="kpiVenues">
    <span class="metric-label">Venues</span>
    <span class="metric-value" id="venues"></span>
  </button>
</div>

<section class="chart-panel">
  <div class="chart-heading">
    <div>
      <div class="section-title">Prize by venue</div>
      <div class="micro">
        Ranked by total prize. Tap a segment for details;
        tap a name for every venue.
      </div>
    </div>
    <button
      id="quality"
      class="quality"
      type="button">
    </button>
  </div>

  <div id="legend"></div>

  <div class="toolbar">
    <div class="navigation">
      <button
        id="previous"
        type="button"
        aria-label="Previous chart view">
        Previous
      </button>
      <span id="page" class="micro"></span>
      <button
        id="next"
        type="button"
        aria-label="Next chart view">
        Next
      </button>
    </div>
    <label class="size-label" for="pageSize">
      Bars per view
      <select id="pageSize">
        <option>8</option>
        <option>12</option>
        <option>20</option>
        <option>50</option>
        <option>100</option>
      </select>
    </label>
  </div>

  <svg id="axis" aria-label="Recorded prize scale"></svg>
  <div id="rows"></div>

  <div class="toolbar footer">
    <span id="range" class="micro"></span>
    <div class="navigation">
      <button id="previousBottom" type="button">Previous</button>
      <button id="nextBottom" type="button">Next</button>
    </div>
  </div>
</section>

<div
  id="tip"
  role="dialog"
  aria-label="Prize details"
  hidden>
</div>

<script>
"use strict";

const data=__MPD_DATA__;
const byId=id=>document.getElementById(id);
const ns="http://www.w3.org/2000/svg";
const tip=byId("tip");

const colors=[
  "#88a8ff","#55d4c4","#f0bb72","#bd9bff","#f08fa8",
  "#70bbeb","#b6d87c","#de9be2","#ed9c72","#a1b8d4",
  "#6798e8","#39b4a6","#d5a35d","#9874dd","#ce718d",
  "#5499c5","#92b15e","#bb79bd","#c97e53","#7b95b5"
];

const color=index=>index<colors.length
  ?colors[index]
  :"hsl("+((index*137.508)%360)+",65%,65%)";

const number=value=>new Intl.NumberFormat(
  undefined,
  {maximumFractionDigits:20}
).format(value);

const money=value=>"JPY "+number(value);
const percent=value=>(value*100).toFixed(1)+"%";

const matrix=new Map();
const totals=new Map();

data.entities.forEach(name=>{
  matrix.set(name,new Map());
  totals.set(name,0);
});

data.rows.forEach(row=>{
  if(matrix.has(row.entity)){
    matrix.get(row.entity).set(row.venue,row);
    totals.set(row.entity,row.entity_total);
  }
});

const maximum=Math.max(
  1,
  data.entities.reduce(
    (current,name)=>Math.max(
      current,
      totals.get(name)||0
    ),
    0
  )
);

let page=0;
let pageSize=8;
let entries=new Map();
let active=null;
let pinned=false;
let hideTimer=null;

byId("title").textContent=
  data.label+" prize comparison";

byId("subtitle").textContent=
  data.period+"  /  "+data.dates;

byId("total").textContent=money(data.total);
byId("records").textContent=number(data.valid);

byId("namesLabel").textContent=
  "Selected "+
  (
    data.label==="Horse Owner"
      ?"horse owners"
      :data.label.toLowerCase()+"s"
  );

byId("names").textContent=
  number(data.entities.length);

byId("venues").textContent=
  number(data.venues.length);

const excluded=
  data.missing+data.invalid+data.invalid_dates;

byId("quality").textContent=excluded
  ?number(excluded)+" excluded records"
  :"Recorded data";

data.venues.forEach((name,index)=>{
  const item=document.createElement("span");
  const swatch=document.createElement("span");
  const label=document.createElement("span");

  item.className="legend-item";
  swatch.className="swatch";
  swatch.style.background=color(index);
  label.textContent=name;

  item.append(swatch,label);
  byId("legend").appendChild(item);
});

function text(parent,tag,value,className){
  const item=document.createElement(tag);
  item.textContent=value;

  if(className){
    item.className=className;
  }

  parent.appendChild(item);
  return item;
}

function line(key,value){
  const row=document.createElement("div");
  row.className="tip-line";

  text(row,"span",key);
  text(row,"span",value);
  tip.appendChild(row);
}

function rule(){
  const item=document.createElement("div");
  item.className="tip-rule";
  tip.appendChild(item);
}

function resetTip(){
  tip.replaceChildren();

  const close=text(
    tip,
    "button",
    "Close",
    "close"
  );

  close.type="button";
  close.addEventListener("click",hide);
}

function highlight(){
  entries.forEach((entry,entityIndex)=>{
    entry.segments.forEach((rect,venueIndex)=>{
      rect.setAttribute(
        "stroke",
        active&&
        active.type==="bar"&&
        active.ei===entityIndex&&
        active.vi===venueIndex
          ?"#edf3ff"
          :"none"
      );
    });
  });
}

function hide(){
  clearTimeout(hideTimer);
  tip.hidden=true;
  active=null;
  pinned=false;
  document.body.style.paddingBottom="28px";
  highlight();
}

function anchor(){
  if(!active){
    return null;
  }

  if(active.type==="bar"){
    return (
      entries.get(active.ei)||{}
    ).svg;
  }

  return byId(active.id);
}

function place(scroll){
  const item=anchor();

  if(!item){
    return;
  }

  tip.hidden=false;

  const box=item.getBoundingClientRect();
  const width=tip.offsetWidth;

  tip.style.left=Math.max(
    12,
    Math.min(
      box.left+window.scrollX,
      window.innerWidth-width-12
    )
  )+"px";

  // Bar details stay below the selected bar.
  tip.style.top=(
    box.bottom+window.scrollY+8
  )+"px";

  document.body.style.paddingBottom=(
    tip.offsetHeight+30
  )+"px";

  if(scroll){
    const rect=tip.getBoundingClientRect();

    if(
      rect.bottom>window.innerHeight||
      rect.top<0
    ){
      tip.scrollIntoView({
        block:"nearest",
        behavior:window.matchMedia(
          "(prefers-reduced-motion: reduce)"
        ).matches
          ?"auto"
          :"smooth"
      });
    }
  }
}

function about(id,pin){
  clearTimeout(hideTimer);
  active={type:"about",id:id};
  pinned=pin;

  resetTip();

  text(
    tip,
    "strong",
    "About the recorded totals"
  );

  text(tip,"div",data.dates,"micro");
  rule();

  line("Recorded prize",money(data.total));
  line("Valid-prize checklists",number(data.valid));
  line("Missing prize",number(data.missing));
  line("Invalid prize",number(data.invalid));
  line("Invalid race date",number(data.invalid_dates));

  text(
    tip,
    "div",
    "Uses your saved checklist prizes and race dates, "+
    "across all finishing places. Review filters do not apply. "+
    "Zero prizes are valid; missing, negative and non-finite "+
    "prizes are excluded. These totals are not calculated "+
    "jockey fees, trainer fees or ownership payout shares. "+
    "Missing reference names are not selectable. "+
    "A calendar-year period includes January–December; "+
    "rolling periods end in the selected month.",
    "note"
  );

  highlight();
  place(pin);
}

function barDetails(entityIndex,venueIndex,pin){
  clearTimeout(hideTimer);

  const entry=entries.get(entityIndex);

  if(!entry){
    return;
  }

  const name=data.entities[entityIndex];
  const total=totals.get(name)||0;

  const row=venueIndex===null
    ?null
    :matrix.get(name).get(data.venues[venueIndex]);

  active={
    type:"bar",
    ei:entityIndex,
    vi:venueIndex
  };

  pinned=pin;
  resetTip();

  text(tip,"strong",name);
  text(tip,"div",data.dates,"micro");
  rule();

  if(venueIndex!==null){
    line("Venue",data.venues[venueIndex]);
    line("Venue prize",money(row?row.prize:0));

    line(
      "Share of participant total",
      percent(
        total>0
          ?(row?row.prize:0)/total
          :0
      )
    );

    line(
      "Valid-prize checklists",
      number(row?row.checklists:0)
    );

    rule();
  }

  line("Participant total",money(total));

  line(
    "Share of comparison total",
    percent(
      data.total>0
        ?total/data.total
        :0
    )
  );

  if(venueIndex===null){
    line(
      "Valid-prize checklists",
      number(
        Array.from(
          matrix.get(name).values()
        ).reduce(
          (sum,item)=>sum+item.checklists,
          0
        )
      )
    );

    if(data.venues.length){
      const table=document.createElement("table");
      table.className="breakdown";

      const head=document.createElement("tr");

      ["Venue","Prize (JPY)","Records"].forEach(value=>{
        text(head,"th",value);
      });

      table.appendChild(head);

      data.venues.forEach(venue=>{
        const record=matrix.get(name).get(venue);
        const tableRow=document.createElement("tr");

        text(tableRow,"td",venue);

        text(
          tableRow,
          "td",
          number(record?record.prize:0)
        );

        text(
          tableRow,
          "td",
          number(record?record.checklists:0)
        );

        table.appendChild(tableRow);
      });

      tip.appendChild(table);

    }else{
      text(
        tip,
        "div",
        "No valid prize values were recorded for this selection.",
        "note"
      );
    }
  }

  highlight();
  place(pin);
}

function laterHide(){
  if(!pinned){
    clearTimeout(hideTimer);
    hideTimer=setTimeout(hide,180);
  }
}

function svgElement(svg,tag,attributes,value){
  const node=document.createElementNS(ns,tag);

  Object.entries(attributes).forEach(([key,item])=>{
    node.setAttribute(key,String(item));
  });

  if(value!==undefined){
    node.textContent=value;
  }

  svg.appendChild(node);
  return node;
}

function bindSegment(node,entityIndex,venueIndex){
  node.setAttribute("tabindex","0");
  node.setAttribute("role","button");
  node.classList.add("segment");

  node.setAttribute(
    "aria-label",
    data.entities[entityIndex]+", "+
    (
      venueIndex===null
        ?"all venues"
        :data.venues[venueIndex]
    )+", show prize details"
  );

  node.addEventListener("click",()=>{
    barDetails(entityIndex,venueIndex,true);
  });

  node.addEventListener("keydown",event=>{
    if(
      event.key==="Enter"||
      event.key===" "
    ){
      event.preventDefault();
      barDetails(entityIndex,venueIndex,true);
    }
  });

  node.addEventListener("pointerenter",event=>{
    if(
      event.pointerType==="mouse"&&
      !pinned
    ){
      barDetails(entityIndex,venueIndex,false);
    }
  });

  node.addEventListener("pointerleave",laterHide);

  node.addEventListener("focus",()=>{
    if(!pinned){
      barDetails(entityIndex,venueIndex,false);
    }
  });

  node.addEventListener("blur",laterHide);
}

function paint(){
  const axis=byId("axis");
  const width=Math.max(
    240,
    axis.clientWidth||700
  );

  axis.replaceChildren();
  axis.setAttribute(
    "viewBox",
    "0 0 "+width+" 28"
  );

  [0,maximum/2,maximum].forEach((value,index)=>{
    svgElement(
      axis,
      "text",
      {
        x:(value/maximum)*width,
        y:19,
        fill:"#8398b8",
        "font-size":10,
        "text-anchor":index===0
          ?"start"
          :index===2
            ?"end"
            :"middle"
      },
      new Intl.NumberFormat(
        undefined,
        {
          notation:"compact",
          maximumFractionDigits:1
        }
      ).format(value)
    );
  });

  entries.forEach((entry,entityIndex)=>{
    entry.svg.replaceChildren();
    entry.segments=new Map();

    const width=Math.max(
      240,
      entry.svg.clientWidth||700
    );

    entry.svg.setAttribute(
      "viewBox",
      "0 0 "+width+" 34"
    );

    const hit=svgElement(
      entry.svg,
      "rect",
      {
        x:0,
        y:0,
        width:width,
        height:34,
        rx:5,
        fill:"#0c1526"
      }
    );

    bindSegment(
      hit,
      entityIndex,
      null
    );

    let offset=0;
    const name=data.entities[entityIndex];

    data.venues.forEach((venue,venueIndex)=>{
      const row=matrix.get(name).get(venue);
      const value=row?row.prize:0;

      if(value>0){
        const rect=svgElement(
          entry.svg,
          "rect",
          {
            x:(offset/maximum)*width,
            y:3,
            width:(value/maximum)*width,
            height:28,
            fill:color(venueIndex),
            stroke:"none",
            "stroke-width":2
          }
        );

        entry.segments.set(
          venueIndex,
          rect
        );

        bindSegment(
          rect,
          entityIndex,
          venueIndex
        );
      }

      offset+=value;
    });
  });

  highlight();

  if(active&&!tip.hidden){
    place(false);
  }
}

function render(){
  byId("rows").replaceChildren();
  entries=new Map();

  const start=page*pageSize;

  const end=Math.min(
    data.entities.length,
    start+pageSize
  );

  for(
    let entityIndex=start;
    entityIndex<end;
    entityIndex++
  ){
    const row=document.createElement("section");
    const head=document.createElement("div");
    const name=document.createElement("button");
    const total=document.createElement("span");
    const svg=document.createElementNS(ns,"svg");

    row.className="bar-row";
    head.className="row-head";

    name.type="button";
    name.className="name";

    text(
      name,
      "span",
      String(entityIndex+1).padStart(2,"0"),
      "rank"
    );

    text(
      name,
      "span",
      data.entities[entityIndex],
      "entity-name"
    );

    name.addEventListener("click",()=>{
      barDetails(entityIndex,null,true);
    });

    total.className="row-total";
    total.textContent=money(
      totals.get(data.entities[entityIndex])||0
    );

    head.append(name,total);

    svg.classList.add("bar");
    svg.setAttribute("role","group");

    svg.setAttribute(
      "aria-label",
      data.entities[entityIndex]+" prize by venue"
    );

    row.append(head,svg);
    byId("rows").appendChild(row);

    entries.set(
      entityIndex,
      {
        svg:svg,
        segments:new Map()
      }
    );
  }

  const pages=Math.max(
    1,
    Math.ceil(data.entities.length/pageSize)
  );

  byId("page").textContent=
    (page+1)+" / "+pages;

  byId("range").textContent=
    "Showing "+(start+1)+"–"+end+
    " of "+data.entities.length+
    "  ·  Same prize scale across views";

  ["previous","previousBottom"].forEach(id=>{
    byId(id).disabled=page===0;
  });

  ["next","nextBottom"].forEach(id=>{
    byId(id).disabled=page>=pages-1;
  });

  paint();
}

function move(amount){
  hide();

  page=Math.max(
    0,
    Math.min(
      Math.ceil(data.entities.length/pageSize)-1,
      page+amount
    )
  );

  render();
  window.scrollTo({top:0});
}

["previous","previousBottom"].forEach(id=>{
  byId(id).addEventListener("click",()=>{
    move(-1);
  });
});

["next","nextBottom"].forEach(id=>{
  byId(id).addEventListener("click",()=>{
    move(1);
  });
});

byId("pageSize").addEventListener("change",event=>{
  hide();
  pageSize=Number(event.target.value);
  page=0;
  render();
});

[
  "about",
  "quality",
  "kpiTotal",
  "kpiRecords",
  "kpiNames",
  "kpiVenues"
].forEach(id=>{
  const item=byId(id);

  item.addEventListener("click",()=>{
    about(id,true);
  });

  item.addEventListener("pointerenter",event=>{
    if(
      event.pointerType==="mouse"&&
      !pinned
    ){
      about(id,false);
    }
  });

  item.addEventListener(
    "pointerleave",
    laterHide
  );
});

tip.addEventListener("pointerenter",()=>{
  clearTimeout(hideTimer);
});

tip.addEventListener(
  "pointerleave",
  laterHide
);

document.addEventListener("pointerdown",event=>{
  if(
    !tip.hidden&&
    !tip.contains(event.target)&&
    !event.target.closest(
      ".bar-row,.metric,#about,#quality"
    )
  ){
    hide();
  }
});

document.addEventListener("keydown",event=>{
  if(event.key==="Escape"){
    hide();
  }
});

let resizeTimer;

window.addEventListener("resize",()=>{
  clearTimeout(resizeTimer);
  resizeTimer=setTimeout(paint,100);
});

render();
</script>
</body>
</html>"""

    components.html(
        html.replace("__MPD_DATA__", payload, 1),
        height=880,
        scrolling=True,
    )

'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# PRIZE_ANALYTICS_DARK_DESIGN_V1"


def find_function(tree, name):
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(found) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(found)}."
        )

    return found[0]


def assignment_names(node):
    if not isinstance(node, ast.Assign):
        return set()

    return {
        item.id
        for target in node.targets
        for item in ast.walk(target)
        if isinstance(item, ast.Name)
    }


def definition_start(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in node.decorator_list
        ]
    ) - 1


class CleanPageTransformer(ast.NodeTransformer):
    NOTES = (
        "Defaults use the current year and month",
        "Uses race date, not entry date",
        "Excluded within the selection:",
        "Each checklist contributes its recorded prize once",
        "Included race dates:",
        "Annual means January",
        "The rolling period includes",
    )

    def __init__(self):
        self.metric_blocks = 0
        self.metric_calls = 0
        self.charts = 0

    def visit_Assign(self, node):
        if (
            assignment_names(node) == {"a", "b", "c", "d"}
            and isinstance(node.value, ast.Call)
        ):
            call = node.value

            if (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "st"
                and call.func.attr == "columns"
            ):
                self.metric_blocks += 1
                return None

        return self.generic_visit(node)

    def visit_Expr(self, node):
        call = node.value

        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
        ):
            if (
                call.func.attr == "metric"
                and call.func.value.id in {"a", "b", "c", "d"}
            ):
                self.metric_calls += 1
                return None

            if call.func.value.id == "st" and call.args:
                messages = [
                    item.value
                    for item in ast.walk(call.args[0])
                    if (
                        isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                    )
                ]

                if (
                    call.func.attr == "caption"
                    and any(
                        token in message
                        for token in self.NOTES
                        for message in messages
                    )
                ):
                    return None

                if (
                    call.func.attr == "warning"
                    and messages == [
                        "Many names are selected. "
                        "Narrow the selection for a more readable chart."
                    ]
                ):
                    return None

        return self.generic_visit(node)

    def visit_If(self, node):
        chart_calls = [
            statement
            for statement in node.body
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name)
                and statement.value.func.id == "_mct_chart"
            )
        ]

        if chart_calls:
            if (
                len(node.body) != 1
                or len(chart_calls) != 1
            ):
                raise ValueError(
                    "Unexpected conditional chart block."
                )

            if not any(
                isinstance(item, ast.Name)
                and item.id == "chart_rows"
                for item in ast.walk(node.test)
            ):
                raise ValueError(
                    "Unexpected chart condition."
                )

            self.charts += 1

            # Render the summary even when valid totals are zero.
            # No artificial positive bars are introduced.
            return chart_calls[0]

        self.generic_visit(node)

        if not node.body:
            if not node.orelse:
                return None

            node.body = [ast.Pass()]

        return node


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    page = find_function(tree, "_mc_page")
    old_chart = find_function(tree, "_mct_chart")

    for name in (
        "_mp_dates",
        "_mc_fetch",
        "_mc_prepare",
        "_mc_config",
    ):
        find_function(tree, name)

    chart_arguments = {
        argument.arg
        for argument in (
            old_chart.args.args
            + old_chart.args.kwonlyargs
        )
    }

    if "period" not in chart_arguments:
        raise ValueError(
            "Install the preceding multi-period "
            "prize update first."
        )

    page_span = (
        definition_start(page),
        page.end_lineno,
    )

    visitor = CleanPageTransformer()
    visitor.visit(page)

    if (
        visitor.metric_blocks,
        visitor.metric_calls,
        visitor.charts,
    ) != (1, 4, 1):
        raise ValueError(
            "Cannot safely identify the old "
            "summary metrics and chart block."
        )

    if any(
        isinstance(node, ast.Name)
        and node.id in {"a", "b", "c", "d"}
        for node in ast.walk(page)
    ):
        raise ValueError(
            "An unexpected reference to "
            "the old metric columns remains."
        )

    ast.fix_missing_locations(page)

    edits = [
        (
            page_span[0],
            page_span[1],
            ast.unparse(page) + "\n\n",
        ),
        (
            definition_start(old_chart),
            old_chart.end_lineno,
            RUNTIME.strip("\n") + "\n\n",
        ),
    ]

    edits.sort()

    if any(
        right[0] < left[1]
        for left, right in zip(edits, edits[1:])
    ):
        raise ValueError(
            "Overlapping source edits."
        )

    lines = source.splitlines(keepends=True)

    for start, end, text in reversed(edits):
        lines[start:end] = [text]

    updated = "".join(lines)

    compile(
        updated,
        "<prize-analytics-dark-design>",
        "exec",
    )

    def normalize(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in {
                    "_mc_page",
                    "_mct_chart",
                }
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the prize "
            "comparison presentation functions."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid prize-design patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Redesign prize comparison dashboards with dark "
            "charts and tooltip-only details, "
            "without extra detail inputs."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    app = Path(
        parser.parse_args().app_file
    ).resolve()

    if not app.is_file():
        raise SystemExit(
            f"Application file not found: {app}"
        )

    original = app.read_bytes()

    try:
        updated, changed = patch_application(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}\n"
            "This patch requires "
            "fix-prize-a-month-feature.py "
            "to be installed first."
        ) from error

    if not changed:
        print(
            "The dark prize-analytics design "
            "is already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-prize-design-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed during validation. "
                "Retry the patch."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app.parent,
            prefix=f".{app.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(updated)

        shutil.copymode(app, temporary)

        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed before replacement. "
                "Retry the patch."
            )

        temporary.replace(app)
        temporary = None

    finally:
        if (
            temporary is not None
            and temporary.exists()
        ):
            temporary.unlink()

    print(f"Updated application: {app}")
    print(f"Source backup: {backup}")
    print("Syntax and AST change-scope validation passed.")
    print(
        "Removed duplicate detail selectors "
        "and the exact-details expander."
    )
    print(
        "Added dark summary cards and tooltip-only "
        "chart details on all three comparison pages."
    )
    print(
        "Tap a segment for venue details; tap a name "
        "for all venue values, including zeros."
    )
    print(
        "Kept existing filters and "
        "8/12/20/50/100-bar pagination."
    )
    print(
        "No new data inputs were added."
    )
    print(
        "Tables, exports, date ranges, account scoping, "
        "and prize calculations were preserved."
    )
    print(
        "Other pages and global Streamlit theme "
        "configuration were not changed."
    )
    print(
        "No database records or schema were changed."
    )
    print(
        "Restart Streamlit and verify iPad/Safari "
        "tapping, scrolling, and rotation."
    )


if __name__ == "__main__":
    main()