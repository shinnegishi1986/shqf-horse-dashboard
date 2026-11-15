# scripts/fix-prize-a-month-feature.py
#
# Requires the preceding monthly trainer/touch-chart update.
#
# Updates jockey, horse-owner, and trainer comparison pages:
#   - Details directly below the selected bar
#   - 8, 12, 20, 50, or 100 bars per view
#   - Monthly, rolling 3-month, rolling 6-month, annual data
#   - Consistent date ranges for charts, totals, tables, and CSV
#
# Period definitions:
#   Month:
#       Selected calendar month.
#   3 months:
#       Selected month plus the preceding two calendar months.
#   6 months:
#       Selected month plus the preceding five calendar months.
#   Annual (calendar year):
#       January–December of the selected year.
#
# Preserves account scoping and prize-validation logic.
# No database records or schema are changed by this patch.
# Creates a timestamped application-source backup.
#
# Stop Streamlit before running:
#
#   python scripts/fix-prize-a-month-feature.py app.py

RUNTIME = r'''
# PRIZE_PERIODS_AND_INLINE_TOUCH_DETAILS_V1

def _mp_dates(year, month, period="Month"):
    from datetime import date

    year, month = int(year), int(month)

    # Validate the selected year/month.
    date(year, month, 1)

    if period == "Annual (calendar year)":
        return (
            date(year, 1, 1),
            date(year + 1, 1, 1),
        )

    spans = {
        "Month": 1,
        "3 months": 3,
        "6 months": 6,
    }

    if period not in spans:
        raise ValueError("Unknown comparison period.")

    index = year * 12 + month - 1

    first_year, first_month = divmod(
        index - spans[period] + 1,
        12,
    )

    next_year, next_month = divmod(
        index + 1,
        12,
    )

    return (
        date(first_year, first_month + 1, 1),
        date(next_year, next_month + 1, 1),
    )


def _mp_bounds(year, month, period="Month"):
    first, end = _mp_dates(
        year,
        month,
        period,
    )

    return first.isoformat(), end.isoformat()


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

    entities = list(stats["entity_order"])
    venues = list(stats["venue_order"])

    if not entities or not venues:
        st.info("No chart data is available.")
        return

    first, end = _mp_dates(year, month, period)
    last = end - timedelta(days=1)

    period_text = (
        f"{first.isoformat()} to {last.isoformat()}"
    )

    payload = json.dumps(
        {
            "rows": chart_rows,
            "entities": entities,
            "venues": venues,
            "label": label,
            "period": period_text,
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
<style>
:root{
  --bg:#fff;--fg:#172033;--muted:#475569;
  --line:#cbd5e1;--panel:#f1f5f9;
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0f172a;--fg:#f8fafc;--muted:#cbd5e1;
    --line:#475569;--panel:#1e293b;
  }
}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{
  margin:0;padding:10px;
  background:var(--bg);color:var(--fg);
  font:14px system-ui,-apple-system,sans-serif;
  -webkit-text-size-adjust:100%;
  -webkit-overflow-scrolling:touch;
}
.controls{
  display:flex;flex-wrap:wrap;gap:8px;
  align-items:center;margin:10px 0;
}
button,select{
  font:inherit;font-size:16px;min-height:44px;
  border:1px solid var(--line);border-radius:7px;
  padding:8px;background:var(--bg);color:var(--fg);
  max-width:100%;touch-action:manipulation;
}
select{flex:1;min-width:140px}
button:disabled{opacity:.45}
button:focus-visible,select:focus-visible{
  outline:3px solid #60a5fa;outline-offset:2px;
}
.hint,.muted{color:var(--muted);line-height:1.5}
.participant{
  border-bottom:1px solid var(--line);
  padding:10px 0;scroll-margin:10px;
}
.row-heading{
  display:flex;align-items:center;
  justify-content:space-between;gap:10px;
}
.name{
  flex:1;text-align:left;overflow-wrap:anywhere;
}
.total{
  max-width:45%;text-align:right;overflow-wrap:anywhere;
}
svg{
  display:block;width:100%;height:44px;touch-action:pan-y;
}
#axis{height:30px}
.hit{cursor:pointer;-webkit-tap-highlight-color:transparent}
.hit:focus{outline:none;stroke:var(--fg);stroke-width:2}
.details{
  position:static;margin:6px 0 4px;padding:12px;
  border:1px solid #60a5fa;border-radius:8px;
  background:var(--panel);line-height:1.6;
  overflow-wrap:anywhere;
}
.details strong{display:block}
.close{float:right;margin-left:8px}
#legend{
  display:flex;flex-wrap:wrap;gap:8px 16px;margin:12px 0;
}
.legend-item{
  display:inline-flex;gap:6px;align-items:center;
  overflow-wrap:anywhere;
}
.swatch{
  display:inline-block;width:15px;height:15px;
  flex-shrink:0;border:1px solid var(--line);
}
.sr{
  position:absolute;width:1px;height:1px;padding:0;
  overflow:hidden;clip:rect(0,0,0,0);
}
</style>
</head>
<body>
<p class="hint">
Tap or click a venue segment: its details appear directly below
that bar, not at the top. Tap the name or empty bar area for the
participant total. Select a name and venue for tiny or zero
segments. Larger views scroll vertically.
</p>

<div class="controls">
  <label class="sr" for="entity">Participant</label>
  <select id="entity"></select>
  <label class="sr" for="venue">Venue</label>
  <select id="venue"></select>
  <button id="clear" type="button">Clear details</button>
</div>

<div class="controls">
  <button id="previous" type="button">Previous</button>
  <span id="page" class="muted"></span>
  <button id="next" type="button">Next</button>
  <label for="pageSize">Bars per view</label>
  <select id="pageSize">
    <option>8</option>
    <option>12</option>
    <option>20</option>
    <option>50</option>
    <option>100</option>
  </select>
</div>

<svg id="axis" aria-label="Recorded prize scale"></svg>
<div id="rows"></div>

<div class="controls">
  <button id="previousBottom" type="button">Previous</button>
  <span id="pageBottom" class="muted"></span>
  <button id="nextBottom" type="button">Next</button>
</div>

<div id="legend" aria-label="Venue legend"></div>

<script>
"use strict";

const data=__MP_DATA__;
const ns="http://www.w3.org/2000/svg";
const byId=id=>document.getElementById(id);

const entitySelect=byId("entity");
const venueSelect=byId("venue");
const matrix=new Map();
const totals=new Map();

const palette=[
  "#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
  "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac",
  "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
  "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"
];

const color=index=>index<palette.length
  ?palette[index]
  :"hsl("+((index*137.508)%360)+",65%,52%)";

const money=value=>"JPY "+new Intl.NumberFormat(
  undefined,
  {maximumFractionDigits:20}
).format(value);

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
let active=null;
let entries=new Map();

function option(select,value,label){
  const item=document.createElement("option");
  item.value=value;
  item.textContent=label;
  select.appendChild(item);
}

option(
  entitySelect,
  "",
  "Select "+data.label.toLowerCase()
);

data.entities.forEach((name,index)=>{
  option(entitySelect,String(index),name);
});

option(
  venueSelect,
  "",
  "All venues: participant total"
);

data.venues.forEach((name,index)=>{
  option(venueSelect,String(index),name);
});

data.venues.forEach((name,index)=>{
  const item=document.createElement("span");
  const swatch=document.createElement("span");
  const text=document.createElement("span");

  item.className="legend-item";
  swatch.className="swatch";
  swatch.style.background=color(index);
  text.textContent=name;

  item.append(swatch,text);
  byId("legend").appendChild(item);
});

function svgElement(svg,tag,attributes,text){
  const item=document.createElementNS(ns,tag);

  Object.entries(attributes).forEach(([key,value])=>{
    item.setAttribute(key,String(value));
  });

  if(text!==undefined){
    item.textContent=text;
  }

  svg.appendChild(item);
  return item;
}

function textLine(parent,text,strong=false){
  const node=document.createElement(
    strong?"strong":"div"
  );

  node.textContent=text;
  parent.appendChild(node);
}

function hideDetails(){
  entries.forEach(entry=>{
    entry.details.hidden=true;

    entry.segments.forEach(rect=>{
      rect.setAttribute("stroke","none");
    });
  });
}

function clear(){
  active=null;
  entitySelect.value="";
  venueSelect.value="";
  hideDetails();
}

function show(entityIndex,venueIndex,scroll){
  const entry=entries.get(entityIndex);

  if(!entry){
    return;
  }

  hideDetails();

  active={
    ei:entityIndex,
    vi:venueIndex
  };

  entitySelect.value=String(entityIndex);

  venueSelect.value=venueIndex===null
    ?""
    :String(venueIndex);

  const name=data.entities[entityIndex];
  const total=totals.get(name)||0;

  const row=venueIndex===null
    ?null
    :matrix.get(name).get(data.venues[venueIndex]);

  entry.details.replaceChildren();

  const close=document.createElement("button");
  close.type="button";
  close.className="close";
  close.textContent="Close";
  close.addEventListener("click",clear);
  entry.details.appendChild(close);

  textLine(
    entry.details,
    data.label+": "+name,
    true
  );

  textLine(entry.details,data.period);

  if(venueIndex===null){
    textLine(entry.details,"All venues");
  }else{
    textLine(
      entry.details,
      "Venue: "+data.venues[venueIndex]
    );

    textLine(
      entry.details,
      "Venue prize: "+money(row?row.prize:0)
    );

    textLine(
      entry.details,
      "Share of participant total: "+
      (
        total>0
          ?((row?row.prize:0)/total*100).toFixed(1)
          :"0.0"
      )+"%"
    );

    if(entry.segments.has(venueIndex)){
      entry.segments.get(venueIndex).setAttribute(
        "stroke",
        "var(--fg)"
      );
    }
  }

  textLine(
    entry.details,
    "Participant total: "+money(total)
  );

  const count=venueIndex===null
    ?Array.from(matrix.get(name).values()).reduce(
      (sum,item)=>sum+item.checklists,
      0
    )
    :(row?row.checklists:0);

  textLine(
    entry.details,
    "Checklists with valid prize: "+count
  );

  entry.details.hidden=false;

  if(scroll){
    const rect=entry.details.getBoundingClientRect();

    if(
      rect.top<0||
      rect.bottom>window.innerHeight
    ){
      entry.details.scrollIntoView({
        block:"nearest",
        behavior:"smooth"
      });
    }
  }
}

function bind(node,entityIndex,venueIndex){
  node.setAttribute("tabindex","0");
  node.setAttribute("role","button");
  node.classList.add("hit");

  const name=data.entities[entityIndex];

  const row=venueIndex===null
    ?null
    :matrix.get(name).get(data.venues[venueIndex]);

  node.setAttribute(
    "aria-label",
    name+", "+
    (
      venueIndex===null
        ?"all venues"
        :data.venues[venueIndex]
    )+", "+
    money(
      venueIndex===null
        ?(totals.get(name)||0)
        :(row?row.prize:0)
    )
  );

  node.addEventListener("click",()=>{
    show(entityIndex,venueIndex,true);
  });

  node.addEventListener("keydown",event=>{
    if(
      event.key==="Enter"||
      event.key===" "
    ){
      event.preventDefault();
      show(entityIndex,venueIndex,true);
    }
  });
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
    "0 0 "+width+" 30"
  );

  [0,maximum/2,maximum].forEach((value,index)=>{
    svgElement(
      axis,
      "text",
      {
        x:(value/maximum)*width,
        y:20,
        fill:"var(--muted)",
        "font-size":12,
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
      "0 0 "+width+" 44"
    );

    const hit=svgElement(
      entry.svg,
      "rect",
      {
        x:0,
        y:0,
        width:width,
        height:44,
        fill:"var(--panel)"
      }
    );

    bind(hit,entityIndex,null);

    let offset=0;
    const name=data.entities[entityIndex];

    data.venues.forEach((venue,venueIndex)=>{
      const row=matrix.get(name).get(venue);
      const value=row?row.prize:0;

      if(value>0){
        const highlighted=
          active&&
          active.ei===entityIndex&&
          active.vi===venueIndex;

        const rect=svgElement(
          entry.svg,
          "rect",
          {
            x:(offset/maximum)*width,
            y:7,
            width:(value/maximum)*width,
            height:30,
            fill:color(venueIndex),
            stroke:highlighted
              ?"var(--fg)"
              :"none",
            "stroke-width":2
          }
        );

        entry.segments.set(
          venueIndex,
          rect
        );

        bind(
          rect,
          entityIndex,
          venueIndex
        );
      }

      offset+=value;
    });
  });
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
    const root=document.createElement("section");
    const heading=document.createElement("div");
    const name=document.createElement("button");
    const total=document.createElement("span");
    const svg=document.createElementNS(ns,"svg");
    const details=document.createElement("div");

    root.className="participant";
    heading.className="row-heading";

    name.className="name";
    name.type="button";
    name.textContent=data.entities[entityIndex];

    name.addEventListener("click",()=>{
      show(entityIndex,null,true);
    });

    total.className="total";
    total.textContent=money(
      totals.get(data.entities[entityIndex])||0
    );

    heading.append(name,total);

    svg.setAttribute("role","group");
    svg.setAttribute(
      "aria-label",
      data.entities[entityIndex]+" prize by venue"
    );

    details.className="details";
    details.hidden=true;
    details.setAttribute("role","status");
    details.setAttribute("aria-live","polite");

    // Details are physically below this participant's bar.
    root.append(heading,svg,details);
    byId("rows").appendChild(root);

    entries.set(
      entityIndex,
      {
        root:root,
        svg:svg,
        details:details,
        segments:new Map()
      }
    );
  }

  const pages=Math.max(
    1,
    Math.ceil(data.entities.length/pageSize)
  );

  const description=
    "View "+(page+1)+" of "+pages+
    " | "+(end-start)+" bars"+
    " | same prize scale across views";

  ["page","pageBottom"].forEach(id=>{
    byId(id).textContent=description;
  });

  ["previous","previousBottom"].forEach(id=>{
    byId(id).disabled=page===0;
  });

  ["next","nextBottom"].forEach(id=>{
    byId(id).disabled=page>=pages-1;
  });

  paint();

  if(active&&entries.has(active.ei)){
    show(
      active.ei,
      active.vi,
      false
    );
  }
}

function move(amount){
  page=Math.max(
    0,
    Math.min(
      Math.ceil(data.entities.length/pageSize)-1,
      page+amount
    )
  );

  clear();
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

byId("clear").addEventListener(
  "click",
  clear
);

byId("pageSize").addEventListener("change",event=>{
  pageSize=Number(event.target.value);
  page=0;
  clear();
  render();
});

function selectedDetail(){
  if(entitySelect.value===""){
    clear();
    return;
  }

  const entityIndex=Number(entitySelect.value);

  const venueIndex=venueSelect.value===""
    ?null
    :Number(venueSelect.value);

  page=Math.floor(
    entityIndex/pageSize
  );

  active={
    ei:entityIndex,
    vi:venueIndex
  };

  render();

  show(
    entityIndex,
    venueIndex,
    true
  );
}

entitySelect.addEventListener(
  "change",
  selectedDetail
);

venueSelect.addEventListener(
  "change",
  selectedDetail
);

document.addEventListener("keydown",event=>{
  if(event.key==="Escape"){
    clear();
  }
});

let timer;

window.addEventListener("resize",()=>{
  clearTimeout(timer);
  timer=setTimeout(paint,100);
});

render();
</script>
</body>
</html>"""

    components.html(
        html.replace("__MP_DATA__", payload, 1),
        height=860,
        scrolling=True,
    )

    with st.expander(
        "Exact prize details — touch-friendly alternative",
        expanded=False,
    ):
        prefix = (
            f"mp_exact_{kind}_{st.session_state.user_id}_"
            f"{first}_{end}"
        )

        for key, options in (
            (prefix + "_entity", entities),
            (prefix + "_venue", venues),
        ):
            if (
                key in st.session_state
                and st.session_state[key] not in options
            ):
                st.session_state.pop(key, None)

        entity = st.selectbox(
            label,
            entities,
            key=prefix + "_entity",
        )

        venue = st.selectbox(
            "Venue",
            venues,
            key=prefix + "_venue",
        )

        row = next(
            (
                row
                for row in chart_rows
                if row["entity"] == entity
                and row["venue"] == venue
            ),
            None,
        )

        if row:
            prize = row["prize"]
            total = row["entity_total"]
            count = row["checklists"]
        else:
            prize, total, count = 0.0, 0.0, 0

        a, b, c = st.columns(3)

        a.metric("Venue Prize", f"JPY {prize:,}")
        b.metric("Participant Total", f"JPY {total:,}")
        c.metric("Valid-Prize Checklists", str(count))

        st.caption(
            f"{entity} | {venue} | {period_text}"
        )

'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# PRIZE_PERIODS_AND_INLINE_TOUCH_DETAILS_V1"


def find_function(tree, name):
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(nodes) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(nodes)}."
        )

    return nodes[0]


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


def add_period_argument(function):
    arguments = {
        argument.arg
        for argument in (
            function.args.args
            + function.args.kwonlyargs
        )
    }

    if "period" in arguments:
        raise ValueError(
            f"{function.name} already has "
            "an unexpected period argument."
        )

    function.args.kwonlyargs.append(
        ast.arg(arg="period")
    )

    function.args.kw_defaults.append(
        ast.Constant("Month")
    )


class PeriodPageTransformer(ast.NodeTransformer):
    def __init__(self):
        self.calls = {
            "_mc_fetch": 0,
            "_mc_prepare": 0,
            "_mct_chart": 0,
        }

        self.selections = 0
        self.downloads = 0
        self.headings = 0

    def visit_Assign(self, node):
        self.generic_visit(node)

        if assignment_names(node) == {"selection_key"}:
            node.value = ast.parse(
                "f'{prefix}_selected_"
                "{range_start.isoformat()}_"
                "{range_end.isoformat()}'",
                mode="eval",
            ).body

            self.selections += 1

        return node

    def visit_Call(self, node):
        self.generic_visit(node)

        if (
            isinstance(node.func, ast.Name)
            and node.func.id in self.calls
        ):
            if any(
                keyword.arg == "period"
                for keyword in node.keywords
            ):
                raise ValueError(
                    "A comparison call already passes a period."
                )

            node.keywords.append(
                ast.keyword(
                    arg="period",
                    value=ast.Name(
                        id="period",
                        ctx=ast.Load(),
                    ),
                )
            )

            self.calls[node.func.id] += 1

        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
        ):
            if node.func.attr == "download_button":
                filename = next(
                    (
                        keyword
                        for keyword in node.keywords
                        if keyword.arg == "file_name"
                    ),
                    None,
                )

                if filename is not None:
                    filename.value = ast.parse(
                        "f'prize_{kind}_"
                        "{range_start.isoformat()}_to_"
                        "{range_last.isoformat()}.csv'",
                        mode="eval",
                    ).body

                    self.downloads += 1

            if (
                node.func.attr == "subheader"
                and node.args
                and any(
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and "Prize Totals and Venue Breakdown"
                    in value.value
                    for value in ast.walk(node.args[0])
                )
            ):
                node.args[0] = ast.parse(
                    "f'{period} — Prize Totals "
                    "and Venue Breakdown'",
                    mode="eval",
                ).body

                self.headings += 1

        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            node.value = node.value.replace(
                "Monthly Prize by ",
                "Prize Comparison by ",
            )

            node.value = node.value.replace(
                "this month's checklist records",
                "the selected period's checklist records",
            )

            node.value = node.value.replace(
                "Download Monthly Comparison CSV",
                "Download Comparison CSV",
            )

        return node


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    fetch = find_function(tree, "_mc_fetch")
    prepare = find_function(tree, "_mc_prepare")
    page = find_function(tree, "_mc_page")
    old_chart = find_function(tree, "_mct_chart")

    find_function(tree, "_mc_config")

    helpers = {
        node.name
        for node in ast.parse(RUNTIME).body
        if isinstance(node, ast.FunctionDef)
    }

    existing = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    if (
        helpers - {"_mct_chart"}
    ) & existing:
        raise ValueError(
            "Conflicting period-comparison helper names "
            "already exist."
        )

    if old_chart.decorator_list:
        raise ValueError(
            "Unexpected decorators on the touch chart."
        )

    modified = {
        node.name: node
        for node in (
            fetch,
            prepare,
            page,
        )
    }

    spans = {
        name: (
            definition_start(node),
            node.end_lineno,
        )
        for name, node in modified.items()
    }

    # Expand the database query to the selected date range.
    add_period_argument(fetch)

    bounds = [
        node
        for node in ast.walk(fetch)
        if (
            isinstance(node, ast.Assign)
            and assignment_names(node) == {"start", "end"}
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_mc_bounds"
        )
    ]

    if len(bounds) != 1:
        raise ValueError(
            "Cannot identify the monthly database date bounds."
        )

    bounds[0].value = ast.parse(
        "_mp_bounds(year, month, period)",
        mode="eval",
    ).body

    # Expand the aggregation's own date filter too.
    # This avoids fetching several months but summing only one.
    add_period_argument(prepare)

    date_filters = []

    for node in ast.walk(prepare):
        if isinstance(node, ast.If):
            attributes = {
                item.attr
                for item in ast.walk(node.test)
                if (
                    isinstance(item, ast.Attribute)
                    and isinstance(item.value, ast.Name)
                    and item.value.id == "race_date"
                )
            }

            if (
                {"year", "month"}.issubset(attributes)
                and any(
                    isinstance(item, ast.Continue)
                    for item in node.body
                )
            ):
                date_filters.append(node)

    if len(date_filters) != 1:
        raise ValueError(
            "Cannot identify the original monthly "
            "aggregation date filter."
        )

    date_filters[0].test = ast.parse(
        "not (_mp_range_start <= race_date < _mp_range_end)",
        mode="eval",
    ).body

    prepare.body[0:0] = ast.parse(
        "_mp_range_start, _mp_range_end = "
        "_mp_dates(year, month, period)"
    ).body

    visitor = PeriodPageTransformer()
    visitor.visit(page)

    if (
        any(
            value != 1
            for value in visitor.calls.values()
        )
        or (
            visitor.selections,
            visitor.downloads,
            visitor.headings,
        ) != (1, 1, 1)
    ):
        raise ValueError(
            "Cannot safely identify all comparison calls "
            "and period-specific UI fields."
        )

    insertions = [
        index
        for index, node in enumerate(page.body)
        if (
            isinstance(node, ast.Assign)
            and assignment_names(node) == {"names"}
        )
    ]

    if len(insertions) != 1:
        raise ValueError(
            "Cannot find a safe position "
            "for the data-period controls."
        )

    block = ast.parse("""
from datetime import timedelta

period = st.radio(
    'Data period',
    ['Month', '3 months', '6 months', 'Annual (calendar year)'],
    horizontal=True,
    key=prefix + '_period',
)

range_start, range_end = _mp_dates(year, month, period)
range_last = range_end - timedelta(days=1)

st.caption(
    f'Included race dates: {range_start.isoformat()} '
    f'to {range_last.isoformat()} (inclusive).'
)

if period == 'Annual (calendar year)':
    st.caption(
        'Annual means January–December of the selected year; '
        'the month selector is ignored.'
    )
elif period != 'Month':
    st.caption(
        'The rolling period includes the selected month '
        'and the preceding complete calendar months.'
    )
""").body

    page.body[
        insertions[0]:insertions[0]
    ] = block

    edits = [
        (
            definition_start(old_chart),
            old_chart.end_lineno,
            "",
        )
    ]

    for name, node in modified.items():
        ast.fix_missing_locations(node)
        start, end = spans[name]

        edits.append(
            (
                start,
                end,
                ast.unparse(node) + "\n\n",
            )
        )

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

    intermediate = "".join(lines)

    first = next(
        node
        for node in ast.parse(intermediate).body
        if isinstance(
            node,
            (ast.FunctionDef, ast.ClassDef),
        )
    )

    lines = intermediate.splitlines(keepends=True)

    lines.insert(
        definition_start(first),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<prize-periods-inline-tooltips>",
        "exec",
    )

    permitted = helpers | set(modified)

    def normalize(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in permitted
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside "
            "prize-period/chart integration."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid period/touch patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add multi-month/annual prize comparisons "
            "and below-bar touch details "
            "with 50/100-bar views."
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
            "Install the preceding monthly trainer/"
            "touch chart update first."
        ) from error

    if not changed:
        print(
            "Prize periods and below-bar touch details "
            "are already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-prize-periods-{stamp}.bak"
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
        "Touch details now appear directly below "
        "the selected bar."
    )
    print(
        "Bars per view: 8, 12, 20, 50, 100, "
        "with scrolling for larger views."
    )
    print(
        "Added rolling 3-month, rolling 6-month, "
        "and calendar-year periods to all three pages."
    )
    print(
        "Tables, totals, tooltips, and CSV files "
        "use the same selected date range."
    )
    print(
        "Account scoping and prize-validation logic "
        "were preserved."
    )
    print(
        "No database records or schema were changed."
    )
    print(
        "Restart Streamlit and test Safari/iPad "
        "tapping, scrolling, and rotation."
    )


if __name__ == "__main__":
    main()