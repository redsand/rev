#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# from __future__ import annotations

# system libraries
import os
import sys
import time
import datetime
import signal
import logging
import logging.handlers
import configparser
import argparse
import pickle
import json
import requests
import hashlib
from collections import defaultdict
import urllib3
import ssl
import threading
import websocket
from websocket._exceptions import WebSocketConnectionClosedException
import re
import uuid
from queue import Queue
import random as r
from urllib.parse import urlparse, urlunparse
from pathlib import Path

from rev import config as rev_config
from rev.execution.orchestrator import run_orchestrated

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

config = {}


def default_config_path() -> str:
    env_path = os.getenv("HAWK_SOC_CONFIG")
    if env_path:
        return env_path

    candidates = [
        Path("/opt/hawk/etc/hawk-ai-agent-soc.cfg"),
        Path.home() / ".config" / "hawk" / "hawk-ai-agent-soc.cfg",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[-1])


def default_log_path() -> Path:
    env_path = os.getenv("HAWK_LOG_FILE")
    if env_path:
        return Path(env_path)

    log_dir = os.getenv("HAWK_LOG_DIR")
    if log_dir:
        return Path(log_dir) / "hawk-ai-agent-soc.log"

    return Path.home() / ".hawk" / "logs" / "hawk-ai-agent-soc.log"


# ============================================================================
# LLM Helpers (shared Rev LLM client)
# ============================================================================

# ============================================================================
# Helpers
# ============================================================================

class DefaultOption(dict):
    def __init__(self, config, section, **kv):
        self._config = config
        self._section = section
        super().__init__(**kv)
    def items(self):
        items = []
        for option, default in super().items():
            if self._config.has_option(self._section, option):
                value = self._config.get(self._section, option)
            else:
                value = default
            items.append((option, value))
        return items

def extract_fields_from_js(js_code):
    body_match = re.search(r'let\s+body\s*=\s*{([^}]+)}', js_code, re.DOTALL)
    body_keys = []
    if body_match:
        body_content = body_match.group(1)
        body_keys = re.findall(r'["\']?([a-zA-Z0-9_]+)["\']?\s*:', body_content)
    route_match = re.search(r'route\s*:\s*["\']([^"\']+)["\']', js_code)
    route_value = route_match.group(1) if route_match else None
    return body_keys, route_value

def _index_for_group_static(case, cfg, explicit=None):

    """
    Return index name in form hawkio-{group_guid}.
    Precedence: explicit arg > case.group_id > cfg.group_guid.
    """
    gid = None
    if explicit and isinstance(explicit, str) and explicit.strip():
        gid = explicit.strip()
    elif case and isinstance(case.get("group_id"), str) and case.get("group_id").strip():
        gid = case.get("group_id").strip()
    else:
        gid = (cfg.get("group_guid") or "").strip()
    return f"hawkio-{gid}" if gid else "hawkio-unknown"

def parse_iso_datetime(dt_str):
    try:
        return datetime.datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        try:
            return datetime.datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            raise ValueError(f"Unrecognized date format: {dt_str}")

def parseConfig(cfg_path):
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path)
    servers = cfg.get("API", "server", vars=DefaultOption(cfg, "API", server='localhost'))
    if isinstance(servers, str) and ',' in servers:
        servers = [s.strip() for s in servers.split(',')]
    else:
        servers = [servers]

    return {
        'server': servers,
        'access_token': cfg.get("API","access_token",vars=DefaultOption(cfg,"API",access_token='')),
        'secret_key': cfg.get("API","secret_key",vars=DefaultOption(cfg,"API",secret_key='password')),
        'insecure': cfg.getboolean("SETTINGS","insecure",vars=DefaultOption(cfg,"SETTINGS",insecure="False")),
        'timeout': cfg.getint("SETTINGS","timeout",vars=DefaultOption(cfg,"SETTINGS",timeout="300")),
        'token': cfg.get("VAULT","token",vars=DefaultOption(cfg,"VAULT",token="")),
        'retry': cfg.getint("SETTINGS","retry",vars=DefaultOption(cfg,"SETTINGS",retry="5")),
        'timezone': cfg.get("SETTINGS","timezone",vars=DefaultOption(cfg,"SETTINGS",timezone="America/Chicago")),
        # LLM
        'llm_provider': cfg.get("LLM","provider",vars=DefaultOption(cfg,"LLM",provider="openai")),
        'openai_api_key': cfg.get("LLM","openai_api_key",vars=DefaultOption(cfg,"LLM",openai_api_key=os.getenv('OPENAI_API_KEY',''))),
        'openai_model': cfg.get("LLM","openai_model",vars=DefaultOption(cfg,"LLM",openai_model="gpt-4o")),
        'anthropic_api_key': cfg.get("LLM","anthropic_api_key",vars=DefaultOption(cfg,"LLM",anthropic_api_key=os.getenv('ANTHROPIC_API_KEY',''))),
        'anthropic_model': cfg.get("LLM","anthropic_model",vars=DefaultOption(cfg,"LLM",anthropic_model="claude-sonnet-4-20250514")),
        # --- AI Search PoC (natural-language -> SIEM search) ---
        'ai_search_url': cfg.get("SEARCH","ai_search_url",vars=DefaultOption(cfg,"SEARCH",ai_search_url=os.getenv('HAWK_AI_SEARCH_URL',''))),
        # If not provided at call-time, we build index as hawkio-{group_guid}
        'group_guid':   cfg.get("SEARCH","group_guid",vars=DefaultOption(cfg,"SEARCH",group_guid=os.getenv('HAWK_GROUP_GUID',''))),
        # Optional request header to PoC service
        'search_token': cfg.get("SEARCH","search_token",vars=DefaultOption(cfg,"SEARCH",search_token=os.getenv('HAWK_SEARCH_TOKEN',''))),
    }

# ============================================================================
# Daemon
# ============================================================================

class HawkDaemon:
    def __init__(self, options):
        global config
        self.options = options
        config = self.config = parseConfig(options.config)

        self.request = requests.Session()
        self.case_last_update = {}
        self.load_state()
        self.define_openai_functions()
        self.openapi_funcs_global = list(self.openapi_funcs)
        self._refresh_tools()
        self.last_case_time = 0

        # WS-related shared state
        self.ws_pending = {}
        self.inv_clients = {}
        self.inv_queues  = {}
        # openapi_funcs_global initialized after base functions are defined

        # Dynamic actions/tooling handshake
        self.actions = []
        self._actions_ready = threading.Event()

        # Robust WS client state/locks
        self.ws = None
        self.ws_open = threading.Event()
        self.ws_send_lock = threading.Lock()
        self.ws_reconnect_lock = threading.Lock()
        self._ws_backoff = 1  # seconds; doubles up to 60

        self.func_fail_counts = defaultdict(int)
        self.max_repeat_failures = 2

        # LLM configuration via Rev config
        if getattr(self.options, "llm_provider", None):
            rev_config.set_llm_provider(self.options.llm_provider)
        if getattr(self.options, "model", None):
            rev_config.set_model(self.options.model)
        logger.info(
            "Initialized Rev LLM provider=%s model=%s",
            rev_config.LLM_PROVIDER,
            rev_config.EXECUTION_MODEL,
        )

    def _ws_url(self):
        u = urlparse(self.config['server'][0])
        scheme = 'wss' if u.scheme == 'https' else 'ws'
        path = (u.path.rstrip('/') + '/websocket') if u.path else '/websocket'
        return urlunparse((scheme, u.netloc, path, '', '', ''))

    # ---------------------------
    # WS helpers
    # ---------------------------
    def is_ws_connected(self):
        try:
            return self.ws is not None and self.ws.sock and self.ws.sock.connected
        except Exception:
            return False

    def _wait_for_ws(self, timeout=30):
        if self.is_ws_connected():
            return True
        return self.ws_open.wait(timeout)

    def _force_ws_reconnect(self):
        if not self.ws_reconnect_lock.acquire(False):
            return
        try:
            self.ws_open.clear()
            try:
                if self.ws is not None:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
            finally:
                self.ws = None
        finally:
            self.ws_reconnect_lock.release()

    # ---------------------------

    def _fc_signature(self, fc):
        # Stable signature for "same tool + same args"
        try:
            args = fc.get('arguments', '')
            return "{}::{}".format(fc.get('name',''), hashlib.sha256(args.encode('utf-8')).hexdigest()[:10])
        except Exception:
            return fc.get('name','unknown')

    def define_openai_functions(self):
        self.openapi_funcs = [
            {"name":"add_case_note","description":"Attach a note to a case","parameters":{"type":"object","properties":{"case_id":{"type":"string"},"note":{"type":"string"}},"required":["case_id","note"]}},
            {"name":"set_case_title","description":"Set the case title describing the incident.","parameters":{"type":"object","properties":{"case_id":{"type":"string"},"title":{"type":"string"}},"required":["case_id","title"]}},
            {"name":"set_case_risk","description":"Set the case risk describing the incident.","parameters":{"type":"object","properties":{"case_id":{"type":"string"},"risk":{"type":"string", "enum":["Critical","High","Moderate","Low"]}},"required":["case_id","risk"]}},
            {"name":"close_case","description":"Close case as benign","parameters":{"type":"object","properties":{"case_id":{"type":"string"},"reason":{"type":"string"}},"required":["case_id","reason"]}},
            {"name":"reopen_case","description":"Reopen a closed case","parameters":{"type":"object","properties":{"case_id":{"type":"string"},"reason":  {"type":"string"}},"required":["case_id","reason"]}},
            {"name":"merge_case","description":"Merge this case into another","parameters":{"type":"object","properties":{"source_case_id":{"type":"string"},"target_case_id":{"type":"string"}},"required":["source_case_id","target_case_id"]}},
            {"name":"trigger_base64_decode","description":"Decode a base64 blob","parameters":{"type":"object","properties":{"blob":{"type":"string"}},"required":["blob"]}},
            {"name":"trigger_user_lookup","description":"Lookup the user's record within Axonius","parameters":{"type":"object","properties":{"user":{"type":"string"}},"required":["user"]}},
            {"name":"trigger_asset_lookup","description":"Lookup the asset's record within Axonius","parameters":{"type":"object","properties":{"host":{"type":"string"}},"required":["host"]}},
            {"name":"escalate_case","description":"Escalate case priority","parameters":{"type":"object","properties":{"case_id":{"type":"string"},"priority":{"type":"string","enum":["P1","P2","P3", "P4", "P5"]},"justification":{"type":"string"}},"required":["case_id","priority","justification"]}},
            {
              "name": "notify_support_email",
              "description": "Send an email to SOC support staff to continue investigation or reach out to user.",
              "parameters": {
                "type": "object",
                "properties": {
                  "subject": { "type": "string", "description": "Email subject line" },
                  "body": { "type": "string", "description": "Email body text" }
                },
                "required": ["subject", "body"]
              }
            },
            {
              "name": "trigger_sleep",
              "description": "Sleep the given amount of seconds.",
              "parameters": {
                "type": "object",
                "properties": {
                  "seconds": { "type": "integer", "description": "Amount of seconds to sleep." },
                },
                "required": ["seconds"]
              }
            },
            {
             "name": "trigger_hawkio_ai_search",
              "description": "Use the HAWK.io AI search PoC to translate plain English to Lucene and query the correct index for this customer.",
              "parameters": {
                "type": "object",
                "properties": {
                  "nl":      { "type": "string", "description": "Natural language query (e.g., 'dropbox hits for julia last 2h')" },
                  "group_id":{ "type": "string", "description": "Override customer group GUID for index selection (optional)" },
                  "from":    { "type": "string", "description": "RFC3339 start time (optional)" },
                  "to":      { "type": "string", "description": "RFC3339 end time (optional)" },
                  "fields":  { "type": "array",  "items": { "type": "string" }, "description": "Optional field allowlist" }
                },
                "required": ["nl"]
              }
            },
        ]
        self.tools = [{"type":"function","function": f} for f in self.openapi_funcs]
        self.tools_global = list(self.tools)

    def sync_openai_functions(self, playbook_actions, base_functions):
        synced = {f['name']: f for f in base_functions}
        excluded_names = {"trigger_asn", "trigger_geoip"}
        excluded_keywords = ("quarantine", "contain", "misp")
        excluded_categories = {"contain"}

        for action in playbook_actions:
            if not action.get("enabled"):
                continue
            module_id = action.get("module_id", "").lower()
            category_id = action.get("category_id", "").lower()
            if any(kw in module_id for kw in excluded_keywords):
                continue
            if category_id in excluded_categories:
                continue
            func_name = "trigger_" + module_id.replace('-', '_')
            if func_name in excluded_names or func_name in synced:
                continue
            synced[func_name] = {
                "action_rid" : action.get("@rid"),
                "action_id" : action.get("action_id"),
                "module_id" : action.get("module_id"),
                "app_id" : action.get("app_id"),
                "config" : action.get("config"),
                "name": func_name,
                "description": action.get('description') or "Run {} playbook".format(action.get('name')),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"}
                    },
                    "required": ["input"]
                }
            }
        return list(synced.values())

    def _refresh_tools(self):
        self.tools_global = [{"type": "function", "function": f} for f in self.openapi_funcs_global]

    def load_state(self):
        try:
            with open('case_state.pkl','rb') as f:
                self.case_last_update = pickle.load(f)
        except FileNotFoundError:
            self.case_last_update = {}

    def save_state(self):
        with open('case_state.pkl','wb') as f:
            pickle.dump(self.case_last_update, f)

    def start_up(self):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        self.authenticate()
        self.running = True
        threading.Thread(target=self._run_inv_ws_server, daemon=True).start()
        threading.Thread(target=self.websocket_loop, daemon=True).start()
        if self.options.id:
            self.poll_case()
            return
        if self.options.ci:
            self.polling_loop()
            return
        while self.running:
            time.sleep(1)

    def _run_inv_ws_server(self):
        from websocket_server import WebsocketServer

        def new_client(client, server):
            logger.info("[investigate‐WS] new client {}".format(client['id']))

        def recv_msg(client, server, raw):
            try:
                msg = json.loads(raw)
            except Exception:
                return

            cid = msg.get('id')
            cmd = msg.get('cmd')
            route = msg.get('route')

            if cmd == 'investigate' and route == 'start':
                token = msg.get('token')
                self.inv_clients[cid] = {
                  'client': client,
                  'server': server,
                  'token': token
                }
                self.inv_queues[cid]  = Queue()
                case_id = msg['case'].lstrip('#')
                url = "{}/case/{}".format(self.config['server'][0], case_id)
                resp = self.request.get(url, verify=not self.config['insecure'])

                if resp.status_code == 401:
                  self.authenticate()
                  self.get_actions()
                  resp = self.request.get(url, verify=not self.config['insecure'])

                resp.raise_for_status()
                js = resp.json()
                if len(js) > 0:
                    case = js[0]
                    threading.Thread(
                        target=self._investigate_run,
                        args=(cid, case),
                        daemon=True
                    ).start()
                    return

            if cmd == 'confirm' and cid in self.inv_queues:
                self.inv_queues[cid].put(msg['data']['confirmed'])
                return

        server = WebsocketServer(port=8070, host='127.0.0.1')
        server.set_fn_new_client(new_client)
        server.set_fn_message_received(recv_msg)
        server.run_forever()

    def _investigate_run(self, request_id, case):
        def on_step(step_data):
            entry  = self.inv_clients[request_id]
            client = entry['client']
            server = entry['server']
            server.send_message(client, json.dumps({
              'cmd': 'stepUpdate', 'id': request_id, 'data': step_data
            }))

        def on_request_confirm(step, reason):
            if not re.search(r'quarantine|contain', reason, re.IGNORECASE):
                return True
            entry  = self.inv_clients[request_id]
            client = entry['client']
            server = entry['server']
            server.send_message(client, json.dumps({
              'cmd': 'requestConfirmation',
              'id':  request_id,
              'step': step,
              'reason': reason
            }))
            return self.inv_queues[request_id].get(timeout=300)

        def on_complete(result):
            entry  = self.inv_clients.pop(request_id)
            client = entry['client']
            server = entry['server']
            self.inv_queues.pop(request_id)
            server.send_message(client, json.dumps({
              'cmd': 'investigateResult',
              'id':  request_id,
              'data': result
            }))

        # Ensure dynamic tools available before LLM planning/execution
        try:
            if not self.ensure_actions_ready(timeout=30):
                logger.warning("[tools] actions not ready in 30s; proceeding with base functions only")
        except Exception as _e:
            logger.error("ensure_actions_ready error: %s", _e)

        on_step({'status': 'queued', 'case_id': case.get("@rid")})
        self.process_case(case, on_complete=on_complete)

    def stop(self, *args):
        self.running = False

    def authenticate(self):
        url = "{}/auth".format(self.config['server'][0])
        creds = {'access_token':self.config['access_token'],'secret_key':self.config['secret_key']}
        resp = self.request.post(url, json=creds, verify=not self.config['insecure'], timeout=self.config['timeout'])
        resp.raise_for_status()
        return resp.json()

    def generate_uuid(self):
        return str(uuid.uuid4())

    # -------- Dynamic actions handshake --------
    def get_actions(self):
        request_id = self.generate_uuid()
        req = {
            "cmd": "actions",
            "route": "get",
            "data": True,
        }
        req['id'] = request_id
        self.send_websocket_message(req)

    def ensure_actions_ready(self, timeout=30):
        # already populated?
        if isinstance(self.openapi_funcs_global, list) and len(self.openapi_funcs_global) > 0:
            return True
        try:
            self._actions_ready.clear()
        except Exception:
            pass
        try:
            self.get_actions()
        except Exception:
            pass
        return self._actions_ready.wait(timeout)

    # ------------------------------------------

    def extract_event_features(self, event):
        exact_keys = {'alert_name', 'payload'}
        prefix_patterns = [
            r'^http_', r'^ip_', r'^file_', r'^audit_', r'^resource_',
            r'^product_', r'^vendor_', r'command', r'^packet_',
            r'_username', r'^event_', r'^threat_',
        ]
        extracted = {}
        for key, value in event.items():
            if key in exact_keys:
                extracted[key] = value
            elif any(re.match(pattern, key, re.IGNORECASE) for pattern in prefix_patterns):
                extracted[key] = value
        return extracted

    def polling_loop(self):
        while self.running:
            try:
                self.poll_cases()
            except Exception as e:
                logger.error("Loop error: %s", e)
                self.authenticate()
                self.get_actions()
            time.sleep(10)
        self.save_state()

    def poll_case(self):
        cid = self.options.id
        url = "{}/case/{}".format(self.config['server'][0], cid)
        resp = self.request.get(url, verify=not self.config['insecure'], timeout=self.config['timeout'])
        resp.raise_for_status()
        case = resp.json()[0]
        print("[+] Processing case {}".format(cid))
        self.process_case(case)
        sys.exit(0)

    def poll_cases(self):
        now = time.time()
        if now - self.last_case_time < 60:
            return
        since = self._load_timestamp()
        since_dt = parse_iso_datetime(since.replace('Z', '')) - datetime.timedelta(hours=1)
        url = "{}/cases?start_date={}".format(self.config['server'][0], since)
        resp = self.request.get(url, verify=not self.config['insecure'], timeout=self.config['timeout'])
        resp.raise_for_status()
        cases = resp.json()

        for case in cases:
            if case.get('progress_status') == 'closed':
                continue
            last_seen_str = case.get('last_seen')
            if not last_seen_str:
                continue
            notes = case.get('notes', [])
            if len(notes) > 1:
                found = False
                for note in notes:
                    if note.get("owner_name") == "HAWK.io AI SOC Agent":
                        found = True
                        break
                if found:
                    continue
            if case.get('risk_level') not in ("High", "Critical"):
                continue
            last_seen_dt = parse_iso_datetime(last_seen_str.replace('Z', ''))
            if last_seen_dt <= since_dt:
                continue
            cid = case.get('@rid')
            url = "{}/case/{}".format(self.config['server'][0], cid[1:])
            resp = self.request.get(url, verify=not self.config['insecure'], timeout=self.config['timeout'])
            resp.raise_for_status()
            case = resp.json()[0]
            updated = case.get('last_seen')
            prev = self.case_last_update.get(cid)
            if prev and updated <= prev:
                continue
            print("[+] Processing case {}".format(cid))
            self.process_case(case)
            self.case_last_update[cid] = updated
            self.last_case_time = now
        self._save_timestamp(datetime.datetime.utcnow().isoformat()+'Z')

    def format_cookies(self, cookie_jar):
        # cookie_jar is a RequestsCookieJar; iterate items()
        try:
            return '; '.join(["{}={}".format(c.name, c.value) for c in cookie_jar])
        except Exception:
            return '; '.join(["{}={}".format(name, value) for name, value in cookie_jar.items()])

    def send_websocket_message(self, message_obj):
        """Thread-safe send that auto-reconnects and retries once on a closed socket."""
        data = json.dumps(message_obj)
        for attempt in range(2):
            try:
                if not self._wait_for_ws(timeout=15):
                    raise RuntimeError("WebSocket not connected.")
                with self.ws_send_lock:
                    if not self.is_ws_connected():
                        raise WebSocketConnectionClosedException("Connection is already closed.")
                    self.ws.send(data)
                return True
            except WebSocketConnectionClosedException as e:
                logger.warning("WebSocket send failed (closed): %s", e)
                self._force_ws_reconnect()
            except Exception as e:
                logger.error("WebSocket send failed: %s", e)
                if attempt == 0:
                    self._force_ws_reconnect()
                else:
                    return False
        return False

    def websocket_loop(self):
        """Persistent WS loop with auto-reconnect and keep-alives."""

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                request_id = msg.get("id")
                if request_id and request_id in self.ws_pending:
                    self.ws_pending[request_id].put(msg)
                    print("[✓] WebSocket result matched and queued: {}".format(request_id))
                    return
                if msg.get('cmd') == 'hello':
                    self.get_actions()
                    return
                if msg.get('cmd') == 'actions':
                    self.actions = msg.get('data', []) or []
                    self.openapi_funcs_global = self.sync_openai_functions(self.actions, self.openapi_funcs)
                    self._refresh_tools()
                    logger.info("[tools] base=%d dynamic=%d total=%d",
                                len(self.openapi_funcs),
                                len(self.openapi_funcs_global) - len(self.openapi_funcs),
                                len(self.openapi_funcs_global))
                    try:
                        self._actions_ready.set()
                    except Exception:
                        pass
                    return
                print("[~] Unmatched WebSocket message (no handler)")
            except Exception as e:
                logger.error("WebSocket error: %s", e)

        def on_error(ws, error):
            logger.error("WebSocket error: %s", error)

        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket closed (%s): %s", close_status_code, close_msg)
            self.ws_open.clear()

        def on_open(ws):
            logger.info("WebSocket connected")
            self.ws_open.set()
            self._ws_backoff = 1
            try:
                self._actions_ready.clear()
            except Exception:
                pass
            self.get_actions()

        max_backoff = 60
        while self.running:
            try:
                try:
                    self.authenticate()
                except Exception as e:
                    logger.error("Auth refresh failed before WS connect: %s", e)
                ws_url = self._ws_url()
                cookie_header = self.format_cookies(self.request.cookies)
                self.ws_open.clear()
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    cookie=cookie_header
                )
                ssl_opts = {"cert_reqs": ssl.CERT_NONE} if self.config.get("insecure") else None
                self.ws.run_forever(
                    sslopt=ssl_opts,
                    ping_interval=30,
                    ping_timeout=10
                )
            except Exception as e:
                logger.error("WS run_forever exception: %s", e)
            finally:
                self.ws_open.clear()
                if not self.running:
                    break
                delay = min(self._ws_backoff, max_backoff)
                jitter = r.uniform(0.0, 1.0)
                logger.info("Reconnecting WebSocket in %.1fs...", delay + jitter)
                time.sleep(delay + jitter)
                self._ws_backoff = min(self._ws_backoff * 2, max_backoff)

    def _case_prompt(self, case):
        cid = case.get('@rid')
        alerts = case.get('alert_names', [])
        src_ips = case.get('ip_srcs', [])
        dst_ips = case.get('ip_dsts', [])
        assets = case.get('assets', [])
        users = case.get('users', [])
        categories = case.get('category', [])
        analytics = case.get('analytics', [])

        summary = """
        * Case Summary:
        - Case ID: {cid}
        - Name: {name}
        - Status: {status}
        - Risk: {risk}
        - Category: {cat}
        - Alerts: {alerts}
        - Src IPs: {src}
        - Dst IPs: {dst}
        - Users: {users}
        - Assets: {assets}
        - Analytics: {analytics}
        """.format(
            cid=cid,
            name=case.get('name'),
            status=case.get('progress_status'),
            risk=case.get('risk_level'),
            cat=', '.join(categories),
            alerts=', '.join(alerts),
            src=', '.join(src_ips),
            dst=', '.join(dst_ips),
            users=', '.join(users),
            assets=', '.join(assets),
            analytics=', '.join(analytics)
        )

        notes = case.get('notes', [])
        note_lines = ["[{ts}] {owner}: {note}".format(
            ts=n['timestamp'], owner=n.get('owner_name', ''), note=n['note']
        ) for n in notes[-3:]]
        note_str = "- Recent Notes:\n" + "\n".join(note_lines) if note_lines else ""

        event_summaries = []
        for e in case.get('events', [])[:5]:
            event_summaries.append(json.dumps(self.extract_event_features(e)))
        event_str = "\n".join(event_summaries)

        action_names = [a.get("name") for a in (self.actions or []) if a.get("name")]
        action_hint = ""
        if action_names:
            action_hint = "\nAvailable playbook actions:\n- " + "\n- ".join(sorted(set(action_names)))

        system_prompt = """
You are a highly skilled cyber security SOC analyst AI.
Work in the HAWK.io IR platform. Use the available playbook actions where helpful.

- INVESTIGATION STRATEGY:
- Do NOT write your plan to a case note; plan inline only.
- Do NOT call add_case_note / set_case_title / set_case_risk / close_case until after you have executed at least one investigative trigger_* tool.
- Start by examining indicators (IPs, alerts, analytics, users).
- Lookup user/asset/IP if needed.
- Avoid asking for confirmation unless necessary (quarantine/contain).
- Avoid redundant function calls — assume previous steps are remembered.
- if a url is found and contains urldefense.com, decode it using proofpoint_urldecode
- Once a url is decoded, take a screenshot and analyze the results for malicious content
- If a trigger_ function returns a status of pending or queued, call trigger_sleep({args: seconds}) then retry
- Do not lookup internal addresses with threat intel feeds.

- WHEN COMPLETE:
Call up to 4 summary functions in this exact order:
  1. `set_case_title`
  2. `add_case_note`
  3. `set_case_risk` (optional)
  4. `close_case`

- All cases are reachable at: https://ir.hawk.io/case/<case_id>
            """

        return "\n".join([
            system_prompt.strip(),
            summary.strip(),
            note_str.strip(),
            ("\n- Sample Events:\n" + event_str) if event_summaries else "",
            action_hint,
        ]).strip()

    def truncate_json_data(self, data, max_tokens=1024):
        max_chars = max_tokens * 4
        json_str = json.dumps(data)
        if len(json_str) <= max_chars:
            return data
        if isinstance(data, dict):
            truncated_data = {}
            for key, value in data.items():
                if isinstance(value, str):
                    truncated_value = value[:max_chars // max(1, len(data))]
                    truncated_data[key] = truncated_value
                else:
                    truncated_data[key] = value
            return truncated_data
        if isinstance(data, list):
            truncated_list = data[:max_chars // 100]
            return truncated_list
        return data

    def process_case(self, case, on_complete=None):
        cid = case.get("@rid")
        try:
            self.ensure_actions_ready(timeout=30)
        except Exception as _e:
            logger.error("ensure_actions_ready error: %s", _e)

        prompt = self._case_prompt(case)
        try:
            result = run_orchestrated(
                prompt,
                rev_config.ROOT,
                enable_learning=False,
                enable_research=True,
                enable_review=True,
                enable_validation=True,
                review_strictness="moderate",
                enable_action_review=False,
                enable_auto_fix=False,
                parallel_workers=1,
                auto_approve=True,
                research_depth="medium",
                resume=False,
                resume_plan=True,
            )
        except Exception as e:
            logger.error("SOC case processing failed: %s", e)
            if on_complete:
                on_complete({"case_id": cid, "error": str(e)})
            return

        if on_complete:
            on_complete({"case_id": cid, "result": str(result)})

    def websocket_send_inline(self, name, msg):
        q = Queue()
        request_id = self.generate_uuid()
        self.ws_pending[request_id] = q
        req = msg
        req['id'] = request_id
        self.send_websocket_message(req)
        try:
            print("[↑] Waiting for reply to {} / request_id={}".format(name, request_id))
            result = q.get(timeout=300)
            print("[↓] Got WebSocket response: {}".format(result))
        except Exception as e:
            result = {"error": "Timeout waiting for WebSocket response for {}".format(name)}
            print("[!] {}".format(result['error']))
        finally:
            try:
                del self.ws_pending[request_id]
            except Exception:
                pass
        return result

    def execute_function(self, fc, case):
        cid = case.get("@rid")
        name = fc['name']
        args = json.loads(fc['arguments'])
        server = self.config['server'][0]

        # Guard: defer summary functions until at least one investigative trigger_* ran
        summary_fns = {'set_case_title','add_case_note','set_case_risk','close_case'}
        if name in summary_fns and not getattr(self, '_did_investigate', False):
            return {
                'status': 'deferred',
                'reason': 'Perform investigative trigger_* step(s) before summary functions.',
                'hint': 'Start with trigger_user_lookup / trigger_asset_lookup / trigger_lucene_search_events or any dynamic trigger_* tool relevant to indicators.'
            }

        if name == 'trigger_geoip_lookup':
            ret = self.request.get("{}/utils/ip2geo/{}".format(server, args['ip_address']), verify=not self.config['insecure']).json()
            ret['status'] = 'success'; ret['code'] = 200; ret['message'] = 'GeoIP was successfully fetched.'
            return ret

        elif name == 'trigger_asn_lookup':
            ret = self.request.get("{}/utils/ip2asn/{}".format(server, args['ip_address']), verify=not self.config['insecure']).json()
            if not ret.get('asn'): ret['asn'] = "Unknown"
            ret['status'] = 'success'; ret['code'] = 200; ret['message'] = 'ASN was successfully fetched.'
            return ret

        elif name == 'trigger_asset_lookup':
            ret = self.request.get("{}/assets/{}".format(server, args['host']), verify=not self.config['insecure']).json()
            if len(ret) == 0:
                return {"status": "success", "reason": "No record found", "message": "The host `{}` was not found in the system.".format(args['host']), "code": 404}
            if 'specific_data' in ret[0]:
                ret[0]['specific_data'] = ret[0]['specific_data'][0:2]
            return self.truncate_json_data(ret[0])

        elif name == 'trigger_user_lookup':
            ret = self.request.get("{}/identities/{}".format(server, args['user']), verify=not self.config['insecure']).json()
            if len(ret) == 0:
                return {"status": "success", "reason": "No record found", "message": "The user `{}` was not found in the system.".format(args['user']), "code": 404}
            if 'specific_data' in ret[0]:
                ret[0]['specific_data'] = ret[0]['specific_data'][0:2]
            return self.truncate_json_data(ret[0])

        elif name == 'set_case_title':
            req = {"cmd": "cases", "route": "setName", "case": cid, "data": args['title']}
            return self.websocket_send_inline(name, req)

        elif name == 'set_case_risk':
            req = {"cmd": "cases", "route": "setRisk", "case": cid, "data": args["risk"]}
            return self.websocket_send_inline(name, req)

        elif name == 'add_case_note':
            req = {
                "cmd": "cases",
                "route": "addNote",
                "data": {
                    "id": cid,
                    "owner_name": "HAWK.io AI SOC Agent",
                    "note": args['note']
                }
            }
            return self.websocket_send_inline(name, req)

        elif name == 'close_case':
            req = {"cmd": "cases", "route": "addNote", "data": {"id": cid, "owner_name": "HAWK.io AI SOC Agent", "note": args['reason']}}
            self.websocket_send_inline(name, req)
            req = {"cmd": "cases", "route": "setStatus", "case": cid, "data": "closed"}
            return self.websocket_send_inline(name, req)

        elif name == 'escalate_case':
            logger.info("Escalating case...")
            logger.info(json.dumps(args))
            return {"status": "success", "details": "Escalated case successfully."}

        elif name == 'reopen_case':
            req = {"cmd": "cases", "route": "addNote", "data": {"id": cid, "owner_name": "HAWK.io AI SOC Agent", "note": args['reason']}}
            self.websocket_send_inline(name, req)
            req = {"cmd": "cases", "route": "setStatus", "case": cid, "data": "in progress"}
            return self.websocket_send_inline(name, req)
        elif name == "trigger_sleep":
            time.sleep(args['seconds'])
            return {"status": "success", "details": "Sleep successfully."}

        elif name == 'trigger_hawkio_ai_search':
            # Natural-language SIEM search via PoC service
            nl = (args.get('nl') or '').strip()
            if not nl:
                return {"status":"error","retriable":False,"reason":"nl is required"}
            frm = args.get('from')
            to  = args.get('to')
            fields = args.get('fields')
            if fields is not None and not isinstance(fields, list):
                return {"status":"error","retriable":False,"reason":"fields must be an array of strings"}

            url = (self.config.get('ai_search_url') or '').strip()
            if not url:
                return {"status":"error","retriable":True,"reason":"ai_search_url not configured","hint":"Set [SEARCH].ai_search_url in cfg or HAWK_AI_SEARCH_URL env."}

            index_name = _index_for_group_static(case, self.config, explicit=args.get('group_id'))
            payload = {"text": nl, "index": index_name}
            if frm:  payload["from"] = frm
            if to:   payload["to"] = to
            if fields: payload["fields"] = fields

            headers = {"Content-Type":"application/json"}
            tok = (self.config.get('search_token') or os.getenv("HAWK_SEARCH_TOKEN") or "").strip()
            if tok:
                headers["X-Auth-Token"] = tok

            try:
                r = self.request.post(
                    url, json=payload, headers=headers,
                    verify=not self.config['insecure'],
                    timeout=self.config['timeout']
                )
                r.raise_for_status()
                try:
                    js = r.json()
                except Exception:
                    js = {"raw": r.text}
                return {"status":"success","index":index_name,"data":js}
            except Exception as e:
                logger.error("[ai-search] request failed: %s", e)
                return {"status":"error","retriable":True,"reason":str(e),"hint":"Check PoC service, credentials, or index name."}

        elif 'trigger_' in name:
            # dynamic tool execution
            f = None
            for g in self.openapi_funcs_global:
                if g['name'] == name:
                    f = g
                    break
            if not f or 'module_id' not in f:
                return {"error": "No module id in function: {}".format(name)}

            fe = None
            for a in self.actions:
                if a.get('module_id') == f['module_id']:
                    fe = a
                    break
            if not fe:
                return {"error": "Action not found for {}".format(name)}

            fields, route = extract_fields_from_js(fe.get('code', ''))
            req = { "cmd": f['module_id'], "route": route, "data": {} }

            # request token: prefer investigate client-scoped token
            request_token = self.inv_clients.get(cid, {}).get('token', self.config['token'])
            req['data']['token'] = request_token
            req['data']['action_id'] = fe.get('@rid')
            req['data']['group_id'] = fe.get('group_id')
            if isinstance(fe.get('config'), dict) and 'credential' in fe['config']:
                req['data']['credential_id'] = fe['config']['credential']

            if fields and len(fields) > 0:
                req['data'][fields[-1]] = args.get('input')
            else:
                req['data'] = args.get('input')

            logger.info("Fetching %s response with: %s", name, json.dumps(req))
            x = self.websocket_send_inline(name, req)

            # If the dynamic action failed, try ONE targeted retry for credential-mismatch
            if isinstance(x, dict) and x.get('status') is False:
                err_blob = json.dumps(x).lower()
                logger.error(f"Failed to call trigger action: {json.dumps(x)}")
                # Heuristic: backend said the credential token didn't match; retry with config token
                if 'credential token failed' in err_blob or 'unable to fetch credential secret' in err_blob:
                    try:
                        req2 = json.loads(json.dumps(req))  # deep copy
                        req2['data']['token'] = self.config.get('token', '')
                        logger.info("Retrying %s once with config token fallback", name)
                        x2 = self.websocket_send_inline(name, req2)
                        if isinstance(x2, dict) and x2.get('status') is False:
                            # Shape a retriable error so the LLM pivots, not loops
                            shaped = {
                                "status": "error",
                                "retriable": True,
                                "code": x2.get('code', 500),
                                "reason": x2.get('details') or "credential_mismatch",
                                "hint": "Credential token mismatch; pivot to an alternate enrichment (e.g., user_lookup via Axonius) or a search step."
                            }
                            return shaped
                        else:
                            x = x2  # success after retry; continue below to artefact
                    except Exception as e:
                        shaped = {
                            "status":"error","retriable":True,
                            "reason": str(e),
                            "hint": "Retry path failed; choose a different tool or proceed with available indicators."
                        }
                        return shaped
                else:
                    # Generic failure -> shape as retriable so the model pivots
                    shaped = {
                        "status": "error",
                        "retriable": True,
                        "code": x.get('code', 500),
                        "reason": x.get('details') or "dynamic_action_failed",
                        "hint": "Try a different enrichment or search alias; avoid repeating the same failing tool."
                    }
                    return shaped


            # Store enrichment artefact
            req = {
                "cmd": "artefacts",
                "route": "add",
                "data": {
                    "key": args.get('input'),
                    "type": "enrichment",
                    "value": x.get('data'),
                    "data": x.get('data'),
                    "malicious": False,
                    "case_id": cid,
                    "group_id": case.get("group_id"),
                    "module": f['module_id']
                }
            }
            self.websocket_send_inline(name, req)
            return x

        return {"error": "unimplemented function"}

    def _load_timestamp(self):
        try:
            return open('.timestamp').read().strip()
        except Exception:
            return (datetime.datetime.utcnow()-datetime.timedelta(days=1)).isoformat()+'Z'

    def _save_timestamp(self, ts):
        with open('.timestamp','w') as f:
            f.write(ts)


def run_soc_agent(options):
    logger = logging.getLogger(__name__)
    log_path = Path(options.log) if options.log else default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    hdlr = logging.handlers.WatchedFileHandler(str(log_path))
    hdlr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(hdlr)
    logger.setLevel(logging.DEBUG if options.debug else logging.INFO)
    daemon = HawkDaemon(options)
    daemon.start_up()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-c','--config', default=default_config_path())
    parser.add_argument('-l','--log')
    parser.add_argument('-i','--id')
    parser.add_argument('-d','--debug', action='store_true')
    parser.add_argument('--ci', action='store_true', help='Monitor the case queue in a CI loop.')
    parser.add_argument('--model', help='LLM model override (uses Rev LLM client)')
    parser.add_argument('-p','--llm-provider', help='LLM provider override (ollama, openai, anthropic, gemini)')
    opt = parser.parse_args()
    run_soc_agent(opt)
