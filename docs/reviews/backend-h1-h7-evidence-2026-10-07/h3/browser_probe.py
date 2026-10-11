import json
import os
from pathlib import Path
import sys
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "backend/manage.py").exists())
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "oj.settings")
assert os.environ.get("POSTGRES_DB") == "xmuoj_h3"
import django
django.setup()
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.test import Client
from account.models import User, AdminType
from learning.models import TeachingClass, TeachingAccessEvent

settings.SESSION_COOKIE_NAME = "h3_probe_session"
admin, _ = User.objects.get_or_create(username="h3-browser-admin", defaults={"admin_type": AdminType.SUPER_ADMIN})
klass, _ = TeachingClass.objects.get_or_create(code="h3-browser", defaults={"name": "Browser probe", "created_by": admin, "status": "active"})
client = Client()
client.force_login(admin)
cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
app = get_wsgi_application()
TeachingAccessEvent.objects.filter(teaching_class=klass).delete()
html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>中文审计真实浏览器验收</title>
<style>body{font:18px system-ui;max-width:900px;margin:50px auto;padding:0 24px}button{padding:12px 20px}pre{white-space:pre-wrap;line-height:1.7}</style>
<h1>H3 中文审计传输验收</h1><p>隔离数据库 xmuoj_h3 · 真实浏览器 → HTTP → Django → PostgreSQL</p>
<button id="run">运行中文审计测试</button><pre id="result">尚未运行</pre>
<script src="/probe/axios.js"></script><script type="module">
import {getClassKnowledgeStats} from '/probe/learning.js';
document.querySelector('#run').onclick=async()=>{
 const out=document.querySelector('#result');
 try{
  const reason='教学支持：进度 100% + 工单%2F / 🙂';
  const response=await getClassKnowledgeStats(CLASS_ID,reason);
  const invalid=await fetch('/api/admin/learning/class/knowledge-stats?class_id='+CLASS_ID,{headers:{'X-Audit-Reason':'%FF'}});
  let rawBlocked=false;
  try {await fetch('/api/admin/learning/class/knowledge-stats?class_id='+CLASS_ID,{headers:{'X-Audit-Reason':'中文'}});}catch(e){rawBlocked=e instanceof TypeError;}
  const rows=await (await fetch('/probe/events')).json();
  const passed=response.status===200 && invalid.status===400 && rawBlocked && rows.length===1 && rows[0]===reason;
  out.textContent=JSON.stringify({passed,valid_http:response.status,invalid_utf8_http:invalid.status,raw_unicode_blocked_by_browser:rawBlocked,stored_reasons:rows,decoded_exactly_once:rows[0]===reason},null,2);
 }catch(e){out.textContent='FAILED: '+String(e);}
};</script></html>'''.replace('CLASS_ID', json.dumps(str(klass.pk)))


def probe(environ, start_response):
    path = environ["PATH_INFO"]
    headers = [("Cache-Control", "no-store")]
    if path == "/":
        content, kind = html.encode(), "text/html; charset=utf-8"
        headers.append(("Set-Cookie", settings.SESSION_COOKIE_NAME + "=" + cookie + "; Path=/; HttpOnly; SameSite=Strict"))
    elif path == "/probe/learning.js":
        content = (ROOT / "frontend/src/api/learning.js").read_text().replace("import axios from 'axios'", "const axios = window.axios").encode()
        kind = "application/javascript"
    elif path == "/probe/axios.js":
        content, kind = (ROOT / "frontend/node_modules/axios/dist/axios.min.js").read_bytes(), "application/javascript"
    elif path == "/probe/events":
        content = json.dumps(list(TeachingAccessEvent.objects.filter(teaching_class=klass).order_by("created_time").values_list("reason", flat=True)), ensure_ascii=False).encode()
        kind = "application/json; charset=utf-8"
    else:
        return app(environ, start_response)
    start_response("200 OK", headers + [("Content-Type", kind), ("Content-Length", str(len(content)))])
    return [content]


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


print("H3 browser probe ready on 127.0.0.1:18003", flush=True)
with make_server("127.0.0.1", 18003, probe, handler_class=QuietHandler) as server:
    server.serve_forever()
