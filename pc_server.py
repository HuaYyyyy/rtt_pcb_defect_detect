import socket, struct, sys, ctypes, time, json, threading, hashlib, os, io
import numpy as np, cv2
from PIL import Image
from datetime import datetime

HOST = '0.0.0.0'
PORT = 8888
JPEG_FILE = 'test.jpg'
WEB_PORT = 5000
USERS_FILE = 'users.json'
RESULTS_MAX = 500
results = []

# ---- User Management ----
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(u):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(u, f, ensure_ascii=False, indent=2)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ---- OPT SciCam SDK ----
SDK_PATH = r"C:\Program Files (x86)\OPTMV\SciCam\Development\Samples\Python"
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)
from SciCam import *
from SciCamPixelType import SciCamPixelType

BAYER_TO_BGR = {
    SciCamPixelType.SCICAM_PIXEL_BayerRG8: cv2.COLOR_BayerRG2BGR,
    SciCamPixelType.SCICAM_PIXEL_BayerGR8: cv2.COLOR_BayerGR2BGR,
    SciCamPixelType.SCICAM_PIXEL_BayerGB8: cv2.COLOR_BayerGB2BGR,
    SciCamPixelType.SCICAM_PIXEL_BayerBG8: cv2.COLOR_BayerBG2BGR,
}
g_cam = None

def init_camera():
    global g_cam
    dev_info = SciCamDevInfoList()
    ret = SciCam.DiscoverDevices(SciCamTLType.SCICAM_TL_GIGE, dev_info)
    if ret != SCICAM_OK or dev_info.uCount == 0:
        print(f"GigE camera not found (ret={ret}, count={dev_info.uCount})")
        return None
    print(f"Found {dev_info.uCount} camera(s)")
    g_cam = SciCam()
    if g_cam.CreateDevice(dev_info.astDevInfo[0]) != SCICAM_OK: return None
    if g_cam.OpenDevice() != SCICAM_OK: return None
    g_cam.SetNodeEnumValueByStringEx(SciCamXmlType.SCICAM_XML_CAMERA, "TriggerMode", "Off")
    if g_cam.StartGrabbing() != SCICAM_OK: return None
    print("Camera initialized OK")
    return g_cam

def grab_frame(cam):
    cam.StopGrabbing(); time.sleep(0.1); cam.StartGrabbing(); time.sleep(0.3)
    payload = ctypes.c_void_p()
    if cam.Grab(payload) != SCICAM_OK: return None
    try:
        pa = SciCamPayloadProperties()
        if SciCam.PayloadGetProperties(payload, pa) != SCICAM_OK: return None
        if pa.ePayloadMode != SciCamPayloadMode.SCICAM_PAYLOAD_MODE_2D: return None
        w, h = int(pa.stImgProperties.ullWidth), int(pa.stImgProperties.ullHeight)
        ptype = pa.stImgProperties.ePixelType
        raw_data = ctypes.c_void_p()
        if SciCam.PayloadGetImageData(payload, raw_data) != SCICAM_OK: return None
        if ptype == SciCamPixelType.SCICAM_PIXEL_Mono8:
            buf_size = w * h
            arr = np.ctypeslib.as_array(ctypes.cast(raw_data, ctypes.POINTER(ctypes.c_ubyte * buf_size)).contents).reshape(h, w)
            frame = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif ptype == SciCamPixelType.SCICAM_PIXEL_BGR8:
            buf_size = w * h * 3
            arr = np.ctypeslib.as_array(ctypes.cast(raw_data, ctypes.POINTER(ctypes.c_ubyte * buf_size)).contents).reshape(h, w, 3)
            frame = arr.copy()
        elif ptype == SciCamPixelType.SCICAM_PIXEL_RGB8:
            buf_size = w * h * 3
            arr = np.ctypeslib.as_array(ctypes.cast(raw_data, ctypes.POINTER(ctypes.c_ubyte * buf_size)).contents).reshape(h, w, 3)
            frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        elif ptype in BAYER_TO_BGR:
            buf_size = w * h
            arr = np.ctypeslib.as_array(ctypes.cast(raw_data, ctypes.POINTER(ctypes.c_ubyte * buf_size)).contents).reshape(h, w)
            frame = cv2.cvtColor(arr, BAYER_TO_BGR[ptype])
        else: return None
        cv2.imwrite('C:/Users/zhhyy/Desktop/cap_debug.jpg', frame)
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img.thumbnail((620, 480), Image.LANCZOS)
        fw, fh = img.size
        cam.FreePayload(payload)
        return fw, fh, img.tobytes('raw', 'RGB')
    except: return None

def prepare_test():
    img = Image.open(JPEG_FILE).convert('RGB')
    img.thumbnail((800, 480), Image.LANCZOS)
    return img.size[0], img.size[1], img.tobytes('raw', 'RGB')

# ---- Flask Web App ----
def start_web_server():
    try:
        from flask import Flask, request, redirect, url_for, session, Response, make_response
    except ImportError:
        print("[WEB] Flask not installed, run: pip install flask")
        return

    app = Flask(__name__)
    app.secret_key = os.urandom(24).hex()
    BG_IMAGE = r'C:\Users\zhhyy\Desktop\OIP-C.jpg'

    @app.route('/static/bg.jpg')
    def serve_bg():
        with open(BG_IMAGE, 'rb') as f:
            return Response(f.read(), mimetype='image/jpeg')

    # ---- Base HTML template with navbar ----
    def base_page(title, body_html, extra_head=''):
        return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
{extra_head}
<style>
 *{{margin:0;padding:0;box-sizing:border-box}}
 body{{font-family:'Microsoft YaHei',sans-serif;background:#0f1923;color:#e0e0e0;min-height:100vh}}
 .nav{{background:#1a2a3a;padding:0 20px;display:flex;align-items:center;height:50px;border-bottom:2px solid #00e5ff}}
 .nav a{{color:#78909c;text-decoration:none;padding:0 16px;font-size:14px;line-height:50px}}
 .nav a:hover,.nav a.active{{color:#00e5ff;background:#0f1923}}
 .nav .brand{{color:#00e5ff;font-size:18px;font-weight:bold;margin-right:24px}}
 .nav .right{{margin-left:auto;display:flex;align-items:center}}
 .nav .right span{{color:#888;font-size:13px;margin-right:12px}}
 .container{{max-width:1100px;margin:0 auto;padding:24px 16px}}
 .card{{background:#1a2a3a;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 4px 16px rgba(0,0,0,.3)}}
 .card h3{{color:#00e5ff;margin-bottom:16px}}
 .btn{{display:inline-block;padding:10px 20px;border:none;border-radius:6px;cursor:pointer;font-size:14px;text-decoration:none}}
 .btn-primary{{background:#00e5ff;color:#0f1923}}
 .btn-danger{{background:#ff5252;color:#fff}}
 .btn-success{{background:#69f0ae;color:#0f1923}}
 .btn-warning{{background:#ff9100;color:#fff}}
 .btn:hover{{opacity:0.85}}
 input,select{{padding:10px;border:1px solid #263238;border-radius:6px;background:#0f1923;color:#e0e0e0;font-size:14px;width:100%;margin-bottom:12px}}
 input:focus{{border-color:#00e5ff;outline:none}}
 table{{width:100%;border-collapse:collapse;font-size:13px}}
 th{{color:#78909c;border-bottom:2px solid #263238;padding:10px 8px;text-align:left}}
 td{{color:#e0e0e0;border-bottom:1px solid #1a2a3a;padding:10px 8px}}
 .bad{{color:#ff5252;font-weight:bold}} .good{{color:#69f0ae;font-weight:bold}}
 .stats{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}}
 .stat{{background:#1a2a3a;border-radius:12px;padding:16px 24px;text-align:center;flex:1;min-width:100px}}
 .stat .num{{font-size:36px;font-weight:bold;color:#00e5ff}}
 .stat .lbl{{font-size:13px;color:#78909c;margin-top:4px}}
 .form-box{{max-width:400px;margin:80px auto}}
 .flash{{background:#ff5252;color:#fff;padding:8px 16px;border-radius:6px;margin-bottom:12px;text-align:center}}
 .flash-success{{background:#69f0ae;color:#0f1923}}
 .row{{display:flex;gap:20px;flex-wrap:wrap}}
 .col{{flex:1;min-width:300px}}
</style></head><body>
<div class="nav">
 <a class="brand" href="/">PCB 缺陷检测</a>
 <a href="/" class="{'active' if title.find('仪表盘')>=0 else ''}">仪表盘</a>
 <a href="/data" class="{'active' if title.find('数据中心')>=0 else ''}">数据中心</a>
 <a href="/profile" class="{'active' if title.find('个人中心')>=0 else ''}">个人中心</a>
 <div class="right">
  <span>{session.get('username','')}</span>
  <a href="/logout">退出</a>
 </div>
</div>
<div class="container">{body_html}</div>
</body></html>'''

    # ---- Login required decorator ----
    def login_required(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*a, **kw):
            if 'username' not in session:
                return redirect(url_for('login_page'))
            return f(*a, **kw)
        return wrapper

    # ---- Auth routes ----
    @app.route('/login', methods=['GET', 'POST'])
    def login_page():
        error = ''
        if request.method == 'POST':
            u = request.form.get('username','').strip()
            p = request.form.get('password','')
            if not u or not p:
                error = '请输入用户名和密码'
            else:
                users = load_users()
                if u in users and users[u] == hash_pw(p):
                    session['username'] = u
                    return redirect(url_for('dashboard'))
                error = '用户名或密码错误'
        return base_page('登录 - PCB 缺陷检测', f'''
<style>body{{background:url(/static/bg.jpg) center/cover no-repeat fixed}}</style>
<div class="form-box"><div class="card" style="background:rgba(26,42,58,0.92)"><h3>登录</h3>
{f'<div class="flash">{error}</div>' if error else ''}
<form method="post" onsubmit="var u=this.username.value.trim();var p=this.password.value;if(!u||!p){{alert('请输入用户名和密码');return false}}">
 <input name="username" placeholder="用户名">
 <input name="password" type="password" placeholder="密码">
 <button class="btn btn-primary" style="width:100%">登录</button>
</form>
<p style="text-align:center;margin-top:12px;color:#78909c">没有账号？<a href="/register" style="color:#00e5ff">注册</a></p>
</div></div>''')

    @app.route('/register', methods=['GET', 'POST'])
    def register_page():
        error = ''
        if request.method == 'POST':
            u = request.form.get('username','').strip()
            p = request.form.get('password','')
            p2 = request.form.get('password2','')
            if not u or not p:
                error = '请填写所有字段'
            elif len(u) < 2:
                error = '用户名至少2个字符'
            elif len(p) < 4:
                error = '密码至少4个字符'
            elif p != p2:
                error = '两次密码不一致'
            else:
                users = load_users()
                if u in users:
                    error = '用户名已存在'
                else:
                    users[u] = hash_pw(p)
                    save_users(users)
                    session['username'] = u
                    return redirect(url_for('dashboard'))
        return base_page('注册 - PCB 缺陷检测', f'''
<style>body{{background:url(/static/bg.jpg) center/cover no-repeat fixed}}</style>
<div class="form-box"><div class="card" style="background:rgba(26,42,58,0.92)"><h3>注册新用户</h3>
{f'<div class="flash">{error}</div>' if error else ''}
<form method="post" onsubmit="var u=this.username.value.trim();var p=this.password.value;var p2=this.password2.value;if(!u||!p){{alert('请填写用户名和密码');return false}}if(p!==p2){{alert('两次密码不一致');return false}}if(p.length<4){{alert('密码至少4位');return false}}">
 <input name="username" placeholder="用户名">
 <input name="password" type="password" placeholder="密码(至少4位)">
 <input name="password2" type="password" placeholder="确认密码">
 <button class="btn btn-primary" style="width:100%">注册</button>
</form>
<p style="text-align:center;margin-top:12px;color:#78909c">已有账号？<a href="/login" style="color:#00e5ff">登录</a></p>
</div></div>''')

    @app.route('/logout')
    def logout():
        session.pop('username', None)
        return redirect(url_for('login_page'))

    # ---- Dashboard (main page) ----
    @app.route('/')
    @login_required
    def dashboard():
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        n = len(results)
        total_def = sum(r['total'] for r in results)
        pass_n = sum(1 for r in results if r['total'] == 0)
        pass_rate = round(pass_n / n * 100, 1) if n > 0 else 0
        last = results[-1]['total'] if n > 0 else '-'
        recent = results[-30:]
        labels = [r['time'][11:19] for r in recent]
        totals = [r['total'] for r in recent]
        sum_m = sum(r['misshole'] for r in results)
        sum_o = sum(r['open'] for r in results)
        sum_s = sum(r['short'] for r in results)

        rows = ''
        for r in reversed(results[-20:]):
            b = '<span class="bad">NG</span>' if r['total'] > 0 else '<span class="good">OK</span>'
            rows += f"<tr><td>{r['time']}</td><td>{r['total']}</td><td>{r['misshole']}</td><td>{r['open']}</td><td>{r['short']}</td><td>{b}</td></tr>"

        return base_page('仪表盘 - PCB 缺陷检测', f'''
<p style="color:#888;margin-bottom:16px">实时数据 | {now}</p>
<div class="stats">
 <div class="stat"><div class="num" style="color:#ff9100">{n}</div><div class="lbl">检测次数</div></div>
 <div class="stat"><div class="num" style="color:#ff5252">{total_def}</div><div class="lbl">累计缺陷</div></div>
 <div class="stat"><div class="num" style="color:#69f0ae">{pass_rate}%</div><div class="lbl">合格率</div></div>
 <div class="stat"><div class="num">{last}</div><div class="lbl">最新检测</div></div>
</div>
<div class="row">
 <div class="col"><div class="card"><h3>缺陷趋势（最近30次）</h3><canvas id="trendChart"></canvas></div></div>
 <div class="col"><div class="card"><h3>缺陷类别分布</h3><canvas id="pieChart"></canvas></div></div>
</div>
<div class="card"><h3>最近检测记录</h3>
 <table><tr><th>时间</th><th>总数</th><th>缺失孔</th><th>开路</th><th>短路</th><th>结果</th></tr>{rows}</table>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
new Chart(document.getElementById('trendChart').getContext('2d'),{{
 type:'line',data:{{labels:{json.dumps(labels)},datasets:[
  {{label:'总数',data:{json.dumps(totals)},borderColor:'#00e5ff',tension:0.3,pointRadius:3}}
 ]}},options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#78909c'}}}}}},scales:{{x:{{ticks:{{color:'#78909c',maxTicksLimit:10}}}},y:{{ticks:{{color:'#78909c',beginAtZero:true}}}}}}}}
}});
new Chart(document.getElementById('pieChart').getContext('2d'),{{
 type:'doughnut',data:{{labels:['缺失孔','开路','短路'],datasets:[{{data:[{sum_m},{sum_o},{sum_s}],backgroundColor:['#ff5252','#ffeb3b','#e0e0e0']}}]}},
 options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#78909c'}}}}}}}}
}});
</script>
<meta http-equiv="refresh" content="3">
''')

    # ---- Personal Center ----
    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        msg = ''
        msg_type = ''
        if request.method == 'POST':
            old = request.form.get('old_pw','')
            new = request.form.get('new_pw','')
            new2 = request.form.get('new_pw2','')
            users = load_users()
            u = session['username']
            if not old or not new:
                msg = '请填写所有字段'; msg_type = 'flash'
            elif users[u] != hash_pw(old):
                msg = '原密码错误'; msg_type = 'flash'
            elif len(new) < 4:
                msg = '新密码至少4位'; msg_type = 'flash'
            elif new != new2:
                msg = '两次新密码不一致'; msg_type = 'flash'
            else:
                users[u] = hash_pw(new)
                save_users(users)
                msg = '密码修改成功'; msg_type = 'flash-success'
        return base_page('个人中心 - PCB 缺陷检测', f'''
<div class="card" style="max-width:500px"><h3>个人中心</h3>
<p style="color:#78909c;margin-bottom:16px">当前用户：<b style="color:#00e5ff">{session['username']}</b></p>
{f'<div class="{msg_type}">{msg}</div>' if msg else ''}
<form method="post" style="margin-top:16px">
 <input name="old_pw" type="password" placeholder="原密码" required>
 <input name="new_pw" type="password" placeholder="新密码(至少4位)" required>
 <input name="new_pw2" type="password" placeholder="确认新密码" required>
 <button class="btn btn-primary" style="width:100%">修改密码</button>
</form>
</div>''')

    # ---- Data Center ----
    @app.route('/data')
    @login_required
    def data_center():
        n = len(results)
        rows = ''
        for i, r in enumerate(reversed(results)):
            b = '<span class="bad">NG</span>' if r['total'] > 0 else '<span class="good">OK</span>'
            rows += f"<tr><td>{i+1}</td><td>{r['time']}</td><td>{r['total']}</td><td>{r['misshole']}</td><td>{r['open']}</td><td>{r['short']}</td><td>{b}</td></tr>"

        sum_m = sum(r['misshole'] for r in results)
        sum_o = sum(r['open'] for r in results)
        sum_s = sum(r['short'] for r in results)
        total_def = sum(r['total'] for r in results)
        pass_n = sum(1 for r in results if r['total'] == 0)
        pass_rate = round(pass_n / n * 100, 1) if n > 0 else 0

        return base_page('数据中心 - PCB 缺陷检测', f'''
<div class="stats">
 <div class="stat"><div class="num">{n}</div><div class="lbl">总记录数</div></div>
 <div class="stat"><div class="num" style="color:#69f0ae">{pass_rate}%</div><div class="lbl">合格率</div></div>
 <div class="stat"><div class="num" style="color:#ff5252">{total_def}</div><div class="lbl">累计缺陷</div></div>
</div>
<div class="card">
 <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
  <h3 style="margin:0">全部检测记录</h3>
  <div>
   <a href="/export/csv" class="btn btn-success">导出 CSV</a>
   <a href="/export/excel" class="btn btn-primary" style="margin-left:8px">导出 Excel</a>
</div></div>
 <table><tr><th>#</th><th>时间</th><th>总数</th><th>缺失孔</th><th>开路</th><th>短路</th><th>结果</th></tr>{rows}</table>
</div>''')

    # ---- Export routes ----
    @app.route('/export/csv')
    @login_required
    def export_csv():
        import csv
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(['序号','时间','总数','缺失孔','开路','短路','结果'])
        for i, r in enumerate(results):
            w.writerow([i+1, r['time'], r['total'], r['misshole'], r['open'], r['short'],
                       'NG' if r['total']>0 else 'OK'])
        resp = Response(output.getvalue(), mimetype='text/csv')
        resp.headers['Content-Disposition'] = f'attachment; filename=pdb_defects_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        return resp

    @app.route('/export/excel')
    @login_required
    def export_excel():
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active; ws.title = '检测记录'
            ws.append(['序号','时间','总数','缺失孔','开路','短路','结果'])
            for i, r in enumerate(results):
                ws.append([i+1, r['time'], r['total'], r['misshole'], r['open'], r['short'],
                          'NG' if r['total']>0 else 'OK'])
            output = io.BytesIO()
            wb.save(output); output.seek(0)
            resp = Response(output.getvalue(),
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            resp.headers['Content-Disposition'] = f'attachment; filename=pdb_defects_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
            return resp
        except ImportError:
            return redirect('/export/csv')

    # ---- API ----
    @app.route('/api/results')
    def api_results():
        return Response(json.dumps(results, ensure_ascii=False), mimetype='application/json')

    print(f"[WEB] Dashboard at http://localhost:{WEB_PORT}")
    print("[WEB] First-time: register a new account at /register")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)

# ---- Main ----
print("Init OPT GigE camera...")
init_camera()
web_thread = threading.Thread(target=start_web_server, daemon=True)
web_thread.start()

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((HOST, PORT)); s.listen(1)
print(f"TCP waiting on port {PORT}...")
conn, addr = s.accept()
print(f"Connected: {addr}")
recv_buf = b""

while True:
    data = conn.recv(4096)
    if not data: break
    recv_buf += data
    while b'\n' in recv_buf:
        line, recv_buf = recv_buf.split(b'\n', 1)
        cmd = line.decode().strip()
        if not cmd: continue
        print(f"Received: {cmd}")

        if cmd.startswith("RESULT"):
            parts = cmd.split()
            if len(parts) == 5:
                results.append({
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'total': int(parts[1]), 'misshole': int(parts[2]),
                    'open': int(parts[3]), 'short': int(parts[4]),
                })
                if len(results) > RESULTS_MAX: del results[:len(results)-RESULTS_MAX]
                print(f"  Result saved: total={parts[1]} miss={parts[2]} open={parts[3]} short={parts[4]}")

        elif cmd == "CAPTURE":
            print("Capturing...")
            if g_cam:
                r = grab_frame(g_cam)
                w, h, raw = r if r else prepare_test()
            else:
                w, h, raw = prepare_test()
            payload = struct.pack('>II', w, h) + raw
            print(f"Sending {w}x{h} RGB ({len(raw)} bytes)")
            conn.sendall(struct.pack('>I', len(payload)))
            conn.sendall(payload)

        elif cmd == "HELLO":
            w, h, raw = prepare_test()
            payload = struct.pack('>II', w, h) + raw
            conn.sendall(struct.pack('>I', len(payload)))
            conn.sendall(payload)

conn.close()
if g_cam: g_cam.StopGrabbing(); g_cam.CloseDevice(); g_cam.DeleteDevice()
s.close()
