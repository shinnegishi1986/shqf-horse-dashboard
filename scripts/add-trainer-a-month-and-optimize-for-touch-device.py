# scripts/add-trainer-a-month-and-optimize-for-touch-device.py
#
# Requires the earlier add-month-comparison.py update.
#
# Adds:
#   - Monthly Trainer Prize page
#   - Touch-friendly charts on jockey, horse-owner, and trainer pages
#   - Tap-to-pin prize details
#   - Larger controls and responsive SVG charts
#   - Name/venue selectors for tiny and zero-value segments
#   - Chart pagination with a consistent prize scale
#   - Native Streamlit exact-value alternative
#
# No external JavaScript libraries or CDN requests are required.
#
# Preserves:
#   - Monthly aggregation and account scoping
#   - Current year/month defaults
#   - Selection controls
#   - Breakdown tables and CSV exports
#   - Existing checklist, template, and blog features
#
# Creates a timestamped source backup.
# Does not modify database records or schema.
#
# Stop Streamlit before running:
#
# python scripts/add-trainer-a-month-and-optimize-for-touch-device.py app.py

RUNTIME = r'''
# MONTHLY_TRAINER_AND_TOUCH_CHART_V1

def _mct_chart(chart_rows, stats, label, kind, year, month):
    import json
    import streamlit.components.v1 as components

    entities = list(stats["entity_order"])
    venues = list(stats["venue_order"])

    if not entities or not venues:
        st.info("No chart data is available.")
        return

    payload = json.dumps(
        {
            "rows": chart_rows,
            "entities": entities,
            "venues": venues,
            "label": label,
            "period": f"{year}-{month:02d}",
        },
        ensure_ascii=True,
        allow_nan=False,
    )

    # Prevent user-entered names from terminating the script element.
    # User labels are inserted into the DOM with textContent.
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
  --bg:#fff;--fg:#172033;--line:#cbd5e1;
  --muted:#475569;--panel:#f1f5f9;
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0f172a;--fg:#f8fafc;--line:#475569;
    --muted:#cbd5e1;--panel:#1e293b;
  }
}
*{box-sizing:border-box}
body{
  margin:0;padding:10px;background:var(--bg);color:var(--fg);
  font-family:system-ui,-apple-system,sans-serif;font-size:14px;
  -webkit-text-size-adjust:100%;
}
.controls{
  display:flex;flex-wrap:wrap;gap:8px;align-items:center;
  margin:8px 0;
}
button,select{
  min-height:44px;font:inherit;font-size:16px;
  border:1px solid var(--line);border-radius:7px;padding:8px;
  background:var(--bg);color:var(--fg);max-width:100%;
  touch-action:manipulation;
}
select{flex:1;min-width:140px}
button:disabled{opacity:.45}
button:focus-visible,select:focus-visible{
  outline:3px solid #60a5fa;outline-offset:2px;
}
.hint,.muted{color:var(--muted)}
.hint{margin:0 0 8px;line-height:1.5}
#details{
  position:sticky;top:0;z-index:3;
  border:1px solid var(--line);border-radius:8px;
  background:var(--panel);padding:12px;min-height:98px;
  line-height:1.5;overflow-wrap:anywhere;
}
#details strong{display:block}
#clear{float:right;margin-left:8px}
svg{
  display:block;width:100%;height:auto;
  touch-action:pan-y;overflow:hidden;
}
.hit{cursor:pointer;-webkit-tap-highlight-color:transparent}
.hit:focus{outline:none;stroke:var(--fg);stroke-width:2}
#legend{
  display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:10px;
}
.legend-item{
  display:inline-flex;align-items:center;gap:6px;
  max-width:100%;overflow-wrap:anywhere;
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
Tap a venue segment to pin its prize details. Details stay visible
until you tap another segment or Clear. For tiny or zero segments,
use the name and venue selectors. Swipe vertically to scroll.
</p>

<div id="details" role="status" aria-live="polite">
  <button id="clear" type="button">Clear</button>
  <strong id="detailTitle">Tap a bar or choose a name</strong>
  <div id="detailVenue"></div>
  <div id="detailPrize"></div>
  <div id="detailTotal"></div>
  <div id="detailCount"></div>
</div>

<div class="controls">
  <label class="sr" for="entity">Participant</label>
  <select id="entity"></select>
  <label class="sr" for="venue">Venue</label>
  <select id="venue"></select>
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
  </select>
</div>

<svg
  id="chart"
  role="group"
  aria-label="Monthly prize comparison, stacked by venue">
</svg>

<div id="legend" aria-label="Venue legend"></div>

<script>
"use strict";

const data=__MCT_DATA__;

const byId=id=>document.getElementById(id);
const svg=byId("chart");
const ns="http://www.w3.org/2000/svg";
const entitySelect=byId("entity");
const venueSelect=byId("venue");

const palette=[
  "#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
  "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac",
  "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
  "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"
];

const color=i=>i<palette.length
  ?palette[i]
  :"hsl("+((i*137.508)%360)+" 65% 52%)";

const money=value=>"JPY "+new Intl.NumberFormat(
  undefined,
  {maximumFractionDigits:20}
).format(value);

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
    (maximumValue,name)=>Math.max(
      maximumValue,
      totals.get(name)||0
    ),
    0
  )
);

let page=0;
let pageSize=8;
let pinned=null;

function option(select,value,label){
  const element=document.createElement("option");
  element.value=value;
  element.textContent=label;
  select.appendChild(element);
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
  item.className="legend-item";

  const swatch=document.createElement("span");
  swatch.className="swatch";
  swatch.style.background=color(index);

  const text=document.createElement("span");
  text.textContent=name;

  item.append(swatch,text);
  byId("legend").appendChild(item);
});

function detail(entityIndex,venueIndex,pin){
  const name=data.entities[entityIndex];

  if(name===undefined){
    return;
  }

  const total=totals.get(name)||0;

  const row=venueIndex===null
    ?null
    :matrix.get(name).get(data.venues[venueIndex]);

  if(pin){
    pinned={
      ei:entityIndex,
      vi:venueIndex
    };

    entitySelect.value=String(entityIndex);

    venueSelect.value=venueIndex===null
      ?""
      :String(venueIndex);
  }

  byId("detailTitle").textContent=
    data.label+": "+name+" | "+data.period+
    (pin?" | Pinned":"");

  byId("detailVenue").textContent=venueIndex===null
    ?"All venues"
    :"Venue: "+data.venues[venueIndex];

  byId("detailPrize").textContent=venueIndex===null
    ?""
    :"Venue prize: "+money(row?row.prize:0)+
      " | Share: "+
      (
        total>0
          ?((row?row.prize:0)/total*100).toFixed(1)
          :"0.0"
      )+"%";

  byId("detailTotal").textContent=
    "Participant total: "+money(total);

  const count=venueIndex===null
    ?Array.from(matrix.get(name).values()).reduce(
      (sum,item)=>sum+item.checklists,
      0
    )
    :(row?row.checklists:0);

  byId("detailCount").textContent=
    "Checklists with valid prize: "+count;
}

function blank(){
  byId("detailTitle").textContent=
    "Tap a bar or choose a name";

  [
    "detailVenue",
    "detailPrize",
    "detailTotal",
    "detailCount"
  ].forEach(id=>{
    byId(id).textContent="";
  });
}

function clear(){
  pinned=null;
  entitySelect.value="";
  venueSelect.value="";
  blank();
  draw();
}

function element(tag,attributes,text){
  const node=document.createElementNS(ns,tag);

  Object.entries(attributes).forEach(([key,value])=>{
    node.setAttribute(key,String(value));
  });

  if(text!==undefined){
    node.textContent=text;
  }

  svg.appendChild(node);
  return node;
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
    detail(entityIndex,venueIndex,true);
    draw();
  });

  node.addEventListener("keydown",event=>{
    if(event.key==="Enter"||event.key===" "){
      event.preventDefault();
      detail(entityIndex,venueIndex,true);
      draw();
    }
  });

  node.addEventListener("pointerenter",event=>{
    if(event.pointerType==="mouse"&&!pinned){
      detail(entityIndex,venueIndex,false);
    }
  });

  node.addEventListener("focus",()=>{
    if(!pinned){
      detail(entityIndex,venueIndex,false);
    }
  });
}

function draw(){
  svg.replaceChildren();

  const width=Math.max(320,svg.clientWidth||700);
  const left=Math.min(220,Math.max(105,width*.25));
  const right=82;
  const top=42;
  const rowHeight=58;
  const plotWidth=Math.max(80,width-left-right);
  const start=page*pageSize;
  const end=Math.min(
    data.entities.length,
    start+pageSize
  );

  const height=
    top+(end-start)*rowHeight+34;

  svg.setAttribute(
    "viewBox",
    "0 0 "+width+" "+height
  );

  [0,maximum/2,maximum].forEach(tick=>{
    const x=left+(tick/maximum)*plotWidth;

    element("line",{
      x1:x,
      x2:x,
      y1:top-8,
      y2:height-24,
      stroke:"var(--line)"
    });

    element(
      "text",
      {
        x:x,
        y:20,
        "text-anchor":"middle",
        fill:"var(--muted)",
        "font-size":11
      },
      new Intl.NumberFormat(
        undefined,
        {
          notation:"compact",
          maximumFractionDigits:1
        }
      ).format(tick)
    );
  });

  for(
    let entityIndex=start;
    entityIndex<end;
    entityIndex++
  ){
    const name=data.entities[entityIndex];
    const y=top+(entityIndex-start)*rowHeight;
    const total=totals.get(name)||0;

    const fullRow=element("rect",{
      x:left,
      y:y,
      width:plotWidth,
      height:44,
      fill:"transparent"
    });

    bind(fullRow,entityIndex,null);

    const maxChars=Math.max(
      6,
      Math.floor((left-12)/12)
    );

    const nameLabel=element(
      "text",
      {
        x:left-9,
        y:y+27,
        "text-anchor":"end",
        fill:"var(--fg)",
        "font-size":13
      },
      name.length>maxChars
        ?name.slice(0,maxChars-1)+"…"
        :name
    );

    const title=document.createElementNS(ns,"title");
    title.textContent=name;
    nameLabel.appendChild(title);

    let offset=0;

    data.venues.forEach((venue,venueIndex)=>{
      const row=matrix.get(name).get(venue);
      const value=row?row.prize:0;

      if(value>0){
        const highlighted=
          pinned&&
          pinned.ei===entityIndex&&
          pinned.vi===venueIndex;

        const rect=element("rect",{
          x:left+(offset/maximum)*plotWidth,
          y:y+7,
          width:(value/maximum)*plotWidth,
          height:30,
          fill:color(venueIndex),
          stroke:highlighted
            ?"var(--fg)"
            :"none",
          "stroke-width":2
        });

        bind(rect,entityIndex,venueIndex);
      }

      offset+=value;
    });

    element(
      "text",
      {
        x:width-right+7,
        y:y+27,
        fill:"var(--fg)",
        "font-size":12
      },
      new Intl.NumberFormat(
        undefined,
        {
          notation:"compact",
          maximumFractionDigits:2
        }
      ).format(total)
    );
  }

  const pages=Math.max(
    1,
    Math.ceil(data.entities.length/pageSize)
  );

  byId("page").textContent=
    "View "+(page+1)+" of "+pages+
    " | same prize scale across views";

  byId("previous").disabled=page===0;
  byId("next").disabled=page>=pages-1;
}

byId("clear").addEventListener("click",clear);

byId("previous").addEventListener("click",()=>{
  page=Math.max(0,page-1);
  clear();
});

byId("next").addEventListener("click",()=>{
  page=Math.min(
    Math.ceil(data.entities.length/pageSize)-1,
    page+1
  );
  clear();
});

byId("pageSize").addEventListener("change",event=>{
  pageSize=Number(event.target.value);
  page=0;
  clear();
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

  page=Math.floor(entityIndex/pageSize);
  detail(entityIndex,venueIndex,true);
  draw();
}

entitySelect.addEventListener(
  "change",
  selectedDetail
);

venueSelect.addEventListener(
  "change",
  selectedDetail
);

svg.addEventListener("pointerleave",()=>{
  if(!pinned){
    blank();
  }
});

svg.addEventListener("focusout",()=>{
  if(!pinned){
    blank();
  }
});

document.addEventListener("keydown",event=>{
  if(event.key==="Escape"){
    clear();
  }
});

let resizeTimer;

window.addEventListener("resize",()=>{
  clearTimeout(resizeTimer);
  resizeTimer=setTimeout(draw,100);
});

draw();
</script>
</body>
</html>"""

    components.html(
        html.replace("__MCT_DATA__", payload, 1),
        height=min(
            1050,
            max(
                560,
                310 + min(8, len(entities)) * 60,
            ),
        ),
        scrolling=True,
    )

    # This native alternative remains available when browser
    # settings restrict interaction inside the chart iframe.
    with st.expander(
        "Exact prize details — touch-friendly alternative",
        expanded=False,
    ):
        prefix = (
            f"mct_exact_{kind}_{st.session_state.user_id}_"
            f"{year}_{month}"
        )

        entity_key = prefix + "_entity"
        venue_key = prefix + "_venue"

        for key, options in (
            (entity_key, entities),
            (venue_key, venues),
        ):
            if (
                key in st.session_state
                and st.session_state[key] not in options
            ):
                st.session_state.pop(key, None)

        entity = st.selectbox(
            label,
            entities,
            key=entity_key,
        )

        venue = st.selectbox(
            "Venue",
            venues,
            key=venue_key,
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

        first, second, third = st.columns(3)

        first.metric(
            "Venue Prize",
            f"JPY {prize:,}",
        )

        second.metric(
            "Participant Total",
            f"JPY {total:,}",
        )

        third.metric(
            "Valid-Prize Checklists",
            str(count),
        )

        st.caption(
            f"{entity} | {venue} | {year}-{month:02d}. "
            "These exact values include small "
            "and zero-value venue segments."
        )

'''

import argparse
import ast
import copy
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# MONTHLY_TRAINER_AND_TOUCH_CHART_V1"
TRAINER_PAGE = "Monthly Trainer Prize"


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


class TouchChartTransformer(ast.NodeTransformer):
    def __init__(self):
        self.charts = 0
        self.specs = 0

    def visit_Assign(self, node):
        if assignment_names(node) == {"spec"}:
            self.specs += 1
            return None

        return self.generic_visit(node)

    def visit_Call(self, node):
        self.generic_visit(node)

        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "vega_lite_chart"
        ):
            self.charts += 1

            return ast.parse(
                "_mct_chart("
                "chart_rows, stats, label, kind, year, month)",
                mode="eval",
            ).body

        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            node.value = node.value.replace(
                "registered jockey/horse owner",
                "registered participant",
            )

        return node


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    main_function = find_function(tree, "main")
    config = find_function(tree, "_mc_config")
    page = find_function(tree, "_mc_page")

    for name in (
        "_mc_prepare",
        "_mc_fetch",
        "get_user_trainers",
    ):
        find_function(tree, name)

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

    if helpers & existing:
        raise ValueError(
            "Conflicting touch-chart helper names "
            "already exist."
        )

    modified = {
        node.name: node
        for node in (
            main_function,
            config,
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

    dictionaries = [
        node.value
        for node in ast.walk(config)
        if (
            isinstance(node, ast.Assign)
            and assignment_names(node) == {"options"}
            and isinstance(node.value, ast.Dict)
            and {"jockey", "owner"}.issubset(
                {
                    key.value
                    for key in node.value.keys
                    if isinstance(key, ast.Constant)
                }
            )
        )
    ]

    if len(dictionaries) != 1:
        raise ValueError(
            "Cannot locate the monthly comparison configuration."
        )

    options = dictionaries[0]

    if any(
        isinstance(key, ast.Constant)
        and key.value == "trainer"
        for key in options.keys
    ):
        raise ValueError(
            "Trainer configuration already exists "
            "without this patch marker."
        )

    options.keys.append(
        ast.Constant("trainer")
    )

    options.values.append(
        ast.parse(
            "('trainer_id', 'trainer_name', "
            "'Trainer', 'Trainers', get_user_trainers)",
            mode="eval",
        ).body
    )

    visitor = TouchChartTransformer()
    visitor.visit(page)

    if (
        visitor.charts,
        visitor.specs,
    ) != (1, 1):
        raise ValueError(
            "Cannot safely identify the original "
            "monthly chart and specification."
        )

    if any(
        isinstance(node, ast.Name)
        and node.id == "spec"
        for node in ast.walk(page)
    ):
        raise ValueError(
            "An unexpected chart specification "
            "reference remains."
        )

    navigation = [
        (index, node.value)
        for index, node in enumerate(main_function.body)
        if (
            isinstance(node, ast.Assign)
            and "page" in assignment_names(node)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "radio"
        )
    ]

    if len(navigation) != 1:
        raise ValueError(
            "Cannot locate main page navigation."
        )

    navigation_index, call = navigation[0]

    menu = (
        call.args[1]
        if len(call.args) > 1
        else next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "options"
            ),
            None,
        )
    )

    if not isinstance(menu, (ast.List, ast.Tuple)):
        raise ValueError(
            "Expected a literal navigation list."
        )

    labels = [
        node.value
        if isinstance(node, ast.Constant)
        else None
        for node in menu.elts
    ]

    if (
        TRAINER_PAGE in labels
        or "Monthly Horse Owner Prize" not in labels
    ):
        raise ValueError(
            "Unexpected monthly navigation; "
            "the trainer page may already exist."
        )

    menu.elts.insert(
        labels.index("Monthly Horse Owner Prize") + 1,
        ast.Constant(TRAINER_PAGE),
    )

    logout = [
        index
        for index, node in enumerate(main_function.body)
        if (
            index > navigation_index
            and isinstance(node, ast.If)
            and any(
                isinstance(value, ast.Constant)
                and value.value == "Logout"
                for value in ast.walk(node.test)
            )
        )
    ]

    if len(logout) != 1:
        raise ValueError(
            "Cannot locate the logout handler."
        )

    main_function.body[
        logout[0] + 1:logout[0] + 1
    ] = ast.parse(
        f"if page == {TRAINER_PAGE!r}:\n"
        "    _mc_page('trainer')\n"
        "    return\n"
    ).body

    edits = []

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

    configs = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "st"
            and node.value.func.attr == "set_page_config"
        )
    ]

    if len(configs) != 1:
        raise ValueError(
            "Expected one top-level Streamlit page configuration."
        )

    page_config = configs[0]

    layout = next(
        (
            keyword
            for keyword in page_config.value.keywords
            if keyword.arg == "layout"
        ),
        None,
    )

    layout_changed = False

    if layout is None:
        layout = ast.keyword(
            arg="layout",
            value=ast.Constant("centered"),
        )
        page_config.value.keywords.append(layout)

    if not (
        isinstance(layout.value, ast.Constant)
        and layout.value.value == "wide"
    ):
        test = ast.parse(
            "st.session_state.get('logged_in', False) and "
            "st.session_state.get('app_navigation_page') "
            f"== {TRAINER_PAGE!r}",
            mode="eval",
        ).body

        layout.value = ast.IfExp(
            test=test,
            body=ast.Constant("wide"),
            orelse=copy.deepcopy(layout.value),
        )

        ast.fix_missing_locations(page_config)

        edits.append(
            (
                page_config.lineno - 1,
                page_config.end_lineno,
                ast.unparse(page_config) + "\n",
            )
        )

        layout_changed = True

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
        "<monthly-trainer-touch-charts>",
        "exec",
    )

    def normalize(text):
        parsed = ast.parse(text)
        kept = []

        for node in parsed.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in helpers | set(modified)
            ):
                continue

            if (
                layout_changed
                and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "st"
                and node.value.func.attr == "set_page_config"
            ):
                continue

            kept.append(node)

        return ast.dump(
            ast.Module(
                body=kept,
                type_ignores=[],
            ),
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside monthly "
            "chart/trainer integration."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid trainer/touch patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add monthly trainer prize comparison and "
            "touch-friendly charts to all monthly prize pages."
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
            "This patch requires the earlier "
            "add-month-comparison.py update."
        ) from error

    if not changed:
        print(
            "Monthly trainer comparison and touch charts "
            "are already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-trainer-touch-{stamp}.bak"
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
        "Added Monthly Trainer Prize with the same "
        "year/month and selection controls."
    )
    print(
        "All three monthly prize pages now use "
        "responsive tap-to-pin charts."
    )
    print(
        "Charts include large controls, bar-view pagination, "
        "and exact-value selectors."
    )
    print(
        "Underlying aggregation, account isolation, tables, "
        "and CSV exports were preserved."
    )
    print(
        "No database records or schema were changed."
    )
    print(
        "Restart Streamlit. Test tapping and rotation "
        "in Safari on the actual iPad."
    )


if __name__ == "__main__":
    main()