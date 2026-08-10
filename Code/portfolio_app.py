# -*- coding: utf-8 -*-
"""
持仓流水管理（portfolio_app.py）
================================
本地 Web 界面：增删改查统一持仓数据库 data/portfolio.db
（指数定投 / 行业基金 / 余额宝资金池，三类流水一张表）

数据模型：
  trans(id, date, category, fund, code, direction, amount, gain, note)
  - code 用 TEXT 存储（保留前导零，如 004643 / 021457）
  - category: 指数 / 行业 / 资金池
  - direction: 指数/行业 = 买入/卖出；资金池 = 转入/转出/收益

用法：
  python portfolio_app.py          # 启动后浏览器打开 http://127.0.0.1:8051
"""
import json
import os
import sys
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 打包成 exe 后：BASE = exe 所在目录（Code/ 或根目录）；脚本运行时 = 脚本所在目录（Code/）
if getattr(sys, 'frozen', False):
    BASE = os.path.dirname(sys.executable)
    _cands = [os.path.join(BASE, 'data', 'portfolio.db'),                # exe 旁 data/（exe 在 Code/ 时）
              os.path.join(os.path.dirname(BASE), 'Code', 'data', 'portfolio.db'),  # 上级/Code/data（exe 在根目录时）
              os.path.join(os.getcwd(), 'data', 'portfolio.db')]          # 工作目录 data/
    DB = next((p for p in _cands if os.path.exists(p)), _cands[0])
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    DB = os.path.join(BASE, 'data', 'portfolio.db')
PORT = 8051

# ---- 定投下拉标的（指数类别：选基金自动带出代码，避免手输丢前导零）----
INDEX_FUNDS = [
    ('华泰柏瑞沪深300ETF联接A', '460300'),
    ('南方中证500ETF联接(LOF)A', '160119'),
    ('易方达创业板ETF联接A', '110026'),
    ('富国中证红利指数增强A', '100032'),
    ('汇添富恒生指数(QDII-LOF)A', '164705'),
    ('易方达恒生红利低波ETF联接A', '021457'),
    ('摩根标普500指数(QDII)A', '019305'),
    ('摩根纳斯达克100指数(QDII)A', '019172'),
]
CASHPOOL_FUND = ('余额宝', 'ZFB')

DIRECTIONS = {'指数': ['买入', '卖出'], '行业': ['买入', '卖出'], '资金池': ['转入', '转出', '收益']}


def db():
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        print(f'[db-error] {e} | DB={DB} | exists={os.path.exists(DB)}', flush=True)
        raise


def get_summary():
    conn = db()
    rows = conn.execute('''
        SELECT category, fund, code,
          SUM(CASE WHEN direction IN ('买入','转入','收益') THEN amount
                   WHEN direction IN ('卖出','转出') THEN -amount ELSE 0 END) AS amt,
          SUM(CASE WHEN direction IN ('买入','转入') THEN amount ELSE 0 END) AS cost
        FROM trans GROUP BY code, category''').fetchall()
    # 资金池推算余额：首次转入日之后，基金买入都从余额宝扣款
    # 推算余额 = 资金池手工余额 - (自首次转入日起 指数/行业 买入 - 卖出)
    cash_implied = None
    r0 = conn.execute("SELECT MIN(date) FROM trans WHERE category='资金池' AND direction='转入'").fetchone()
    if r0 and r0[0]:
        first_in = r0[0]
        fund_net = conn.execute('''
            SELECT SUM(CASE WHEN direction IN ('买入') THEN amount
                            WHEN direction IN ('卖出') THEN -amount ELSE 0 END)
            FROM trans WHERE category IN ('指数','行业') AND date >= ?''', (first_in,)).fetchone()[0] or 0
        cash_manual = conn.execute('''
            SELECT SUM(CASE WHEN direction IN ('转入','收益') THEN amount
                            WHEN direction IN ('转出') THEN -amount ELSE 0 END)
            FROM trans WHERE category='资金池' ''').fetchone()[0] or 0
        cash_implied = round(cash_manual - fund_net, 2)
    conn.close()
    summary = {'指数': {'funds': [], 'total': 0.0, 'cost': 0.0},
               '行业': {'funds': [], 'total': 0.0, 'cost': 0.0},
               '资金池': {'funds': [], 'total': 0.0, 'cost': 0.0}}
    for r in rows:
        if r['amt'] <= 0:
            continue
        cat = summary[r['category']]
        cat['funds'].append({'fund': r['fund'], 'code': r['code'],
                             'amt': round(r['amt'], 2), 'cost': round(r['cost'], 2)})
        cat['total'] += r['amt']
        cat['cost'] += r['cost']
    for c in summary:
        summary[c]['total'] = round(summary[c]['total'], 2)
    # 总资产 = 可用现金（推算余额）+ 基金持仓成本；无推算时用资金池手工总额
    if cash_implied is not None:
        total = round(cash_implied + summary['指数']['total'] + summary['行业']['total'], 2)
    else:
        total = round(sum(summary[c]['total'] for c in summary), 2)
    return {'summary': summary, 'total': total, 'cash_implied': cash_implied}


def list_trans(category='', q='', tid=None):
    conn = db()
    sql = 'SELECT * FROM trans WHERE 1=1'
    params = []
    if tid:
        sql += ' AND id=?'
        params.append(int(tid))
    if category:
        sql += ' AND category=?'
        params.append(category)
    if q:
        sql += ' AND (fund LIKE ? OR code LIKE ?)'
        params += [f'%{q}%', f'%{q}%']
    sql += ' ORDER BY date DESC, id DESC'
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    if tid:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def list_names(category=''):
    conn = db()
    if category:
        rows = conn.execute('SELECT DISTINCT fund, code FROM trans WHERE category=? ORDER BY fund', (category,)).fetchall()
    else:
        rows = conn.execute('SELECT DISTINCT fund, code FROM trans ORDER BY fund').fetchall()
    conn.close()
    return [{'fund': r['fund'], 'code': r['code']} for r in rows]


def add_trans(p):
    conn = db()
    conn.execute('INSERT INTO trans(date,category,fund,code,direction,amount,gain,note) VALUES(?,?,?,?,?,?,?,?)',
                 (p['date'], p['category'], p['fund'], p['code'], p['direction'], float(p['amount']),
                  float(p.get('gain') or 0), p.get('note', '')))
    conn.commit()
    conn.close()


def update_trans(pid, p):
    conn = db()
    conn.execute('''UPDATE trans SET date=?,category=?,fund=?,code=?,direction=?,amount=?,gain=?,note=?
                    WHERE id=?''',
                 (p['date'], p['category'], p['fund'], p['code'], p['direction'], float(p['amount']),
                  float(p.get('gain') or 0), p.get('note', ''), pid))
    conn.commit()
    conn.close()


def delete_trans(pid):
    conn = db()
    conn.execute('DELETE FROM trans WHERE id=?', (pid,))
    conn.commit()
    conn.close()


PAGE = '''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>持仓流水管理</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--line:#e3e6eb;--tx:#1c2333;--mut:#5b6472;--blue:#185FA5;--blue2:#E6F1FB}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,"Microsoft YaHei",sans-serif;font-size:14px}
header{background:#fff;border-bottom:1px solid var(--line);padding:18px 0}
.wrap{max-width:1100px;margin:0 auto;padding:0 20px}
header h1{font-size:20px}
header .sub{color:var(--mut);font-size:13px;margin-top:4px}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.kpi{flex:1;min-width:150px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.kpi .k{color:var(--mut);font-size:12px}
.kpi .v{font-size:20px;font-weight:700;margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.card h2{font-size:15px;margin-bottom:10px}
.filters{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
select,input[type=text],input[type=number]{padding:7px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;font-family:inherit}
select:focus,input:focus{outline:2px solid #B5D4F4;border-color:var(--blue)}
.btn{padding:7px 16px;border:none;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit}
.btn-p{background:var(--blue);color:#fff}.btn-p:hover{background:#0C447C}
.btn-g{background:#f1f3f5;color:var(--tx)}.btn-g:hover{background:#e3e6eb}
.btn-r{background:#FCEBEB;color:#A32D2D}.btn-r:hover{background:#F7C1C1}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#f1f3f5;padding:8px;text-align:center;border-bottom:2px solid var(--line)}
td{padding:7px 8px;text-align:center;border-bottom:1px solid #f1f3f5}
tr:hover td{background:#f8f9fa}
.tag{display:inline-block;padding:1px 8px;border-radius:8px;font-size:12px;font-weight:500}
.tag-index{background:var(--blue2);color:var(--blue)}
.tag-industry{background:#EBFBEE;color:#0F6E56}
.tag-cash{background:#FFF3BF;color:#854F0B}
form#editForm{display:grid;grid-template-columns:repeat(7,auto) 1fr auto;gap:8px;align-items:end;margin-top:10px}
form#editForm label{font-size:12px;color:var(--mut);display:block;margin-bottom:3px}
.err{color:#A32D2D;font-size:12px;margin-top:6px}
.hint{font-size:12px;color:var(--mut);margin-top:8px}
</style></head><body>
<header><div class="wrap"><h1>持仓流水管理</h1>
<div class="sub">统一数据库 data/portfolio.db · 指数定投 / 行业基金 / 余额宝资金池 · 代码文本存储保留前导零</div></div></header>
<div class="wrap">
<div class="kpis">
<div class="kpi"><div class="k">指数持仓</div><div class="v" id="kIdx">-</div></div>
<div class="kpi"><div class="k">行业持仓</div><div class="v" id="kInd">-</div></div>
<div class="kpi"><div class="k">余额宝</div><div class="v" id="kCashImplied">-</div><div class="hint" style="margin-top:2px">可用现金</div></div>
<div class="kpi"><div class="k">总资产</div><div class="v" id="kTotal">-</div></div>
</div>
<div class="card"><h2>当前持仓</h2>
<table><thead><tr><th>类别</th><th>基金</th><th>代码</th><th>当前持仓</th><th>累计成本</th></tr></thead>
<tbody id="holdTbody"></tbody></table>
</div>
<div class="card"><h2>新增 / 编辑流水</h2>
<form id="editForm" autocomplete="off">
<div><label>日期(YYYYMMDD)</label><input type="text" id="fDate" size="9" placeholder="20260810"></div>
<div><label>类别</label><select id="fCat"><option>指数</option><option>行业</option><option>资金池</option></select></div>
<div><label>基金</label><span id="fundField"></span></div>
<div><label>代码</label><input type="text" id="fCode" size="8" readonly></div>
<div><label>方向</label><select id="fDir"></select></div>
<div><label>金额</label><input type="number" id="fAmt" step="0.01" style="width:90px"></div>
<div><label>备注</label><input type="text" id="fNote" size="14"></div>
<div><button class="btn btn-p" type="button" onclick="save()" id="saveBtn">新增</button>
<button class="btn btn-g" type="button" onclick="resetForm()" style="display:none" id="cancelBtn">取消</button></div>
</form>
<datalist id="fundSuggest"></datalist>
<div class="err" id="err"></div>
</div>
<div class="card"><h2>流水明细</h2>
<div class="filters">
<select id="fltCat" onchange="load()"><option value="">全部类别</option><option>指数</option><option>行业</option><option>资金池</option></select>
<input type="text" id="fltQ" placeholder="搜索基金/代码" oninput="load()" style="width:200px">
<button class="btn btn-g" type="button" onclick="load();loadSummary()">刷新</button>
<span class="hint">共 <b id="cnt">0</b> 条</span>
</div>
<table><thead><tr><th>ID</th><th>日期</th><th>类别</th><th>基金</th><th>代码</th><th>方向</th><th>金额</th><th>备注</th><th>操作</th></tr></thead>
<tbody id="tbody"></tbody></table>
</div>
</div>
<script>
const INDEX_FUNDS = ''' + json.dumps(INDEX_FUNDS, ensure_ascii=False) + ''';
const CASH_FUND = ''' + json.dumps(CASHPOOL_FUND, ensure_ascii=False) + ''';
const DIRS = ''' + json.dumps(DIRECTIONS, ensure_ascii=False) + ''';
let editingId = null;

function today(){ const d=new Date(); const p=n=>String(n).padStart(2,'0');
  return ''+d.getFullYear()+p(d.getMonth()+1)+p(d.getDate()); }

function buildFundField(cat, curFund, curCode){
  const box=document.getElementById('fundField');
  const code=document.getElementById('fCode');
  if(cat==='指数'||cat==='资金池'){
    const list = cat==='指数' ? INDEX_FUNDS : [CASH_FUND];
    const sel=document.createElement('select'); sel.id='fFund'; sel.style.minWidth='230px';
    list.forEach(([n,c])=>{const o=document.createElement('option');o.value=n;o.dataset.code=c;o.textContent=n;sel.appendChild(o);});
    sel.onchange=()=>{ code.value=sel.selectedOptions[0].dataset.code||''; };
    box.innerHTML=''; box.appendChild(sel);
    if(curFund){ for(const o of sel.options){ if(o.value===curFund){ sel.value=curFund; break; } } }
    code.value = curFund ? (curCode||sel.selectedOptions[0].dataset.code) : (list[0][1]);
    code.readOnly=true;
  } else {
    const inp=document.createElement('input'); inp.id='fFund'; inp.type='text';
    inp.list='fundSuggest'; inp.style.minWidth='230px'; inp.placeholder='输入基金名（如 国泰创新药ETF联接C）';
    box.innerHTML=''; box.appendChild(inp);
    code.readOnly=false;
    if(curFund){ inp.value=curFund; code.value=curCode||''; } else { code.value=''; }
  }
  buildDirOptions(cat);
}
function buildDirOptions(cat){
  const sel=document.getElementById('fDir'); sel.innerHTML='';
  DIRS[cat].forEach(d=>{const o=document.createElement('option');o.value=d;o.textContent=d;sel.appendChild(o);});
}
function loadSuggest(){
  fetch('/api/names?category='+encodeURIComponent('行业')).then(r=>r.json()).then(list=>{
    const dl=document.getElementById('fundSuggest'); dl.innerHTML='';
    const seen=new Set();
    list.forEach(x=>{ if(!seen.has(x.fund)){ seen.add(x.fund); const o=document.createElement('option'); o.value=x.fund; dl.appendChild(o); } });
  });
}
document.getElementById('fCat').onchange=()=>{ buildFundField(document.getElementById('fCat').value); };

function load(){
  const cat=document.getElementById('fltCat').value;
  const q=document.getElementById('fltQ').value;
  fetch('/api/trans?category='+encodeURIComponent(cat)+'&q='+encodeURIComponent(q)).then(r=>r.json()).then(data=>{
    const tb=document.getElementById('tbody'); tb.innerHTML='';
    document.getElementById('cnt').textContent=data.length;
    data.forEach(t=>{
      const cls=t.category==='指数'?'tag-index':(t.category==='行业'?'tag-industry':'tag-cash');
      const tr=document.createElement('tr');
      tr.innerHTML='<td>'+t.id+'</td><td>'+t.date+'</td><td><span class="tag '+cls+'">'+t.category+'</span></td>'
        +'<td style="text-align:left">'+t.fund+'</td><td>'+t.code+'</td><td>'+t.direction+'</td>'
        +'<td class="'+(t.direction==='卖出'||t.direction==='转出'?'down':'up')+'">'+t.amount.toFixed(2)+'</td>'
        +'<td>'+(t.note||'')+'</td>'
        +'<td><button class="btn btn-g" onclick="edit('+t.id+')">编辑</button> '
        +'<button class="btn btn-r" onclick="del('+t.id+')">删</button></td>';
      tb.appendChild(tr);
    });
  });
}
function loadSummary(){
  fetch('/api/summary').then(r=>r.json()).then(s=>{
    document.getElementById('kIdx').textContent='¥'+s.summary['指数'].total.toLocaleString();
    document.getElementById('kInd').textContent='¥'+s.summary['行业'].total.toLocaleString();
    document.getElementById('kCashImplied').textContent = (s.cash_implied!=null) ? '¥'+s.cash_implied.toLocaleString() : '—';
    document.getElementById('kTotal').textContent='¥'+s.total.toLocaleString();
    const tb=document.getElementById('holdTbody'); tb.innerHTML='';
    // 指数/行业按当前持仓降序，余额宝固定放最后
    const order=['指数','行业','资金池'];
    order.forEach(cat=>{
      const funds = (cat==='资金池') ? s.summary[cat].funds
        : s.summary[cat].funds.slice().sort((a,b)=>b.amt-a.amt);
      funds.forEach(f=>{
        const cls=cat==='指数'?'tag-index':(cat==='行业'?'tag-industry':'tag-cash');
        // 资金池显示「推算余额」（可用现金 = 转入-已投），而非转入累计
        const amtShow = (cat==='资金池' && s.cash_implied!=null) ? s.cash_implied : f.amt;
        const tr=document.createElement('tr');
        tr.innerHTML='<td><span class="tag '+cls+'">'+cat+'</span></td><td style="text-align:left">'+f.fund
          +'</td><td>'+f.code+'</td><td>¥'+amtShow.toLocaleString(undefined,{minimumFractionDigits:2})
          +'</td><td>¥'+f.cost.toLocaleString(undefined,{minimumFractionDigits:2})+'</td>';
        tb.appendChild(tr);
      });
    });
    if(!tb.children.length){
      const tr=document.createElement('tr');
      tr.innerHTML='<td colspan="5" style="color:#adb5bd">暂无持仓（资金池可先录一笔初始转入）</td>';
      tb.appendChild(tr);
    }
  });
}
function edit(id){
  fetch('/api/trans?id='+id).then(r=>r.json()).then(t=>{
    if(!t){ alert('未找到该流水'); return; }
    editingId=t.id;
    document.getElementById('fDate').value=t.date;
    document.getElementById('fCat').value=t.category;
    buildFundField(t.category, t.fund, t.code);
    document.getElementById('fDir').value=t.direction;
    document.getElementById('fAmt').value=t.amount;
    document.getElementById('fNote').value=t.note||'';
    document.getElementById('saveBtn').textContent='保存修改';
    document.getElementById('cancelBtn').style.display='inline-block';
    document.getElementById('err').textContent='';
    window.scrollTo({top:0,behavior:'smooth'});
  });
}
function resetForm(){
  editingId=null;
  document.getElementById('fDate').value=today();
  document.getElementById('fCat').value='指数';
  buildFundField('指数');
  document.getElementById('fAmt').value=''; document.getElementById('fNote').value='';
  document.getElementById('saveBtn').textContent='新增';
  document.getElementById('cancelBtn').style.display='none';
  document.getElementById('err').textContent='';
}
function save(){
  const fundEl=document.getElementById('fFund');
  const p={ date:document.getElementById('fDate').value.trim(),
    category:document.getElementById('fCat').value,
    fund:fundEl.value.trim(),
    code:document.getElementById('fCode').value.trim(),
    direction:document.getElementById('fDir').value,
    amount:document.getElementById('fAmt').value,
    note:document.getElementById('fNote').value.trim() };
  if(!p.date||!p.code||!p.amount){ document.getElementById('err').textContent='日期/代码/金额 必填'; return; }
  if(p.category==='行业'&&!p.fund){ document.getElementById('err').textContent='行业基金需填基金名'; return; }
  const url=editingId?'/api/update?id='+editingId:'/api/add';
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)}).then(r=>r.json()).then(d=>{
    if(d.ok){ resetForm(); load(); loadSummary(); loadSuggest(); }
    else document.getElementById('err').textContent=d.err||'保存失败';
  });
}
function del(id){
  if(!confirm('确认删除这条流水？')) return;
  fetch('/api/delete?id='+id).then(r=>r.json()).then(d=>{ if(d.ok){load();loadSummary();} });
}
document.getElementById('fDate').value=today();
buildFundField('指数');
load(); loadSummary(); loadSuggest();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == '/' or u.path == '/index.html':
            self._send(200, PAGE, 'text/html; charset=utf-8')
        elif u.path == '/api/summary':
            self._send(200, json.dumps(get_summary(), ensure_ascii=False))
        elif u.path == '/api/trans':
            rows = list_trans(q.get('category', [''])[0], q.get('q', [''])[0],
                              q.get('id', [None])[0])
            self._send(200, json.dumps(rows, ensure_ascii=False))
        elif u.path == '/api/names':
            self._send(200, json.dumps(list_names(q.get('category', [''])[0]), ensure_ascii=False))
        else:
            self._send(404, '{"err":"not found"}')

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        ln = int(self.headers.get('Content-Length', 0))
        p = json.loads(self.rfile.read(ln).decode('utf-8')) if ln else {}
        q = parse_qs(u.query)
        try:
            if u.path == '/api/add':
                add_trans(p)
            elif u.path == '/api/update':
                update_trans(int(q.get('id', [0])[0]), p)
            elif u.path == '/api/delete':
                delete_trans(int(q.get('id', [0])[0]))
            else:
                self._send(404, '{"err":"not found"}'); return
            self._send(200, '{"ok":true}')
        except Exception as e:
            self._send(200, json.dumps({'ok': False, 'err': str(e)}, ensure_ascii=False))

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    import webbrowser
    import threading
    print(f'[debug] frozen={getattr(sys, "frozen", False)} DB={DB} exists={os.path.exists(DB)}')
    if not os.path.exists(DB):
        print(f'[warn] 未找到数据库 {DB}，界面将显示空数据')
    # 延迟打开浏览器（等服务起来）
    threading.Timer(0.8, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    print(f'持仓流水管理已启动: http://127.0.0.1:{PORT}')
    print('浏览器已自动打开；关闭本窗口即停止服务')
    try:
        ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
