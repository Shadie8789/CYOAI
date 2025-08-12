#!/usr/bin/env python3
"""
CYOAI_with_admin.py

Single-file Flask app:
- Public chat UI at '/'
- Admin dashboard at '/admin' (login required) to view/add/remove blocked keywords (rules.json)
- Uses a local Hugging Face text-generation model (default gpt2)
- Enforces blocked keywords for safety; only admin can modify rules.

Security notes:
- Set ADMIN_PASSWORD and FLASK_SECRET as environment variables before running.
- Only use the bot for educational/legal purposes on systems you own or have permission to test.
"""

import os
import re
import json
from pathlib import Path
from flask import (
    Flask, request, jsonify, render_template_string,
    session, redirect, url_for, flash
)
from transformers import pipeline, set_seed

# ---------- Configuration ----------
APP_PORT = int(os.getenv("PORT", "5000"))
MODEL_NAME = os.getenv("MODEL_NAME", "gpt2")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", None)
FLASK_SECRET = os.getenv("FLASK_SECRET", "change_this_secret")
RULES_PATH = Path("rules.json")

if ADMIN_PASSWORD is None:
    raise RuntimeError("Please set ADMIN_PASSWORD environment variable before running.")

# ---------- Flask app setup ----------
app = Flask(__name__)
app.secret_key = FLASK_SECRET

# ---------- Rules management ----------
DEFAULT_RULES = [
    "ddos", "exploit", "zero-day", "backdoor", "rootkit",
    "trojan", "password cracking", "brute-force", "bypass security",
    "unauthorized", "how to hack", "delete data"
]

def load_rules():
    if not RULES_PATH.exists():
        save_rules(DEFAULT_RULES)
    try:
        with RULES_PATH.open("r", encoding="utf8") as f:
            rules = json.load(f)
            if not isinstance(rules, list):
                raise ValueError
            return rules
    except Exception:
        save_rules(DEFAULT_RULES)
        return DEFAULT_RULES.copy()

def save_rules(rules_list):
    with RULES_PATH.open("w", encoding="utf8") as f:
        json.dump(rules_list, f, indent=2)

# Load rules into memory (refreshed from disk on admin changes)
BLOCKED_PATTERNS = load_rules()

def is_malicious(text: str):
    t = text.lower()
    for pat in BLOCKED_PATTERNS:
        try:
            # treat rules as literal substring unless they look like regex
            if pat.startswith("re:"):
                if re.search(pat[3:], t):
                    return True
            else:
                if pat.lower() in t:
                    return True
        except Exception:
            # fallback substring check
            if pat.lower() in t:
                return True
    return False

# ---------- Load model pipeline ----------
print("Loading model pipeline (this may take time). Model:", MODEL_NAME)
generator = pipeline("text-generation", model=MODEL_NAME)
set_seed(0)

SYSTEM_INSTRUCTION = (
    "You are CYOAI, an educational ethical-hacking assistant. Provide defensive, legal, "
    "and instructional guidance and code examples suitable for learning in a private lab. "
    "If the user asks for illegal or weaponized steps, refuse and provide safe alternatives "
    "and learning resources."
)

def generate_text(prompt: str, max_tokens: int = 256) -> str:
    out = generator(prompt, max_new_tokens=max_tokens, do_sample=True, top_p=0.9, temperature=0.7)
    text = out[0]["generated_text"]
    # attempt to remove the prompt echo if present
    if prompt in text:
        text = text.split(prompt, 1)[1]
    return text.strip()

# ---------- Templates (inline for single-file convenience) ----------
CHAT_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>CYOAI — Chat</title>
  <style>
    body{font-family: Arial, Helvetica, sans-serif; margin:30px;}
    #chat{border:1px solid #ccc;padding:12px;height:400px;overflow:auto;}
    .msg.user{color:#0b5; margin:6px 0;}
    .msg.bot{color:#05f; margin:6px 0;}
    #controls{margin-top:10px;}
    input[type=text]{width:70%;}
    button{padding:6px 12px;}
    .small{font-size:0.9em;color:#666;}
    .admin-link{float:right;}
  </style>
</head>
<body>
  <h2>CYOAI — Educational Chatbot</h2>
  <div><a class="admin-link" href="/admin">Admin</a></div>
  <div id="chat"></div>
  <div id="controls">
    <input id="prompt" type="text" placeholder="Ask CYOAI a question..." />
    <button id="send">Send</button>
    <div class="small">CYOAI provides educational guidance only. Do not request illegal actions.</div>
  </div>

<script>
const chatEl = document.getElementById('chat');
const promptEl = document.getElementById('prompt');
const sendBtn = document.getElementById('send');

function appendMessage(who, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + (who==='user' ? 'user' : 'bot');
  div.innerText = (who==='user' ? 'You: ' : 'CYOAI: ') + text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

sendBtn.addEventListener('click', async () => {
  const prompt = promptEl.value.trim();
  if(!prompt) return;
  appendMessage('user', prompt);
  promptEl.value = '';
  appendMessage('bot', '...thinking...');
  // call /chat
  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({prompt})
    });
    const data = await resp.json();
    // remove last "...thinking..." message
    chatEl.removeChild(chatEl.lastChild);
    if(resp.status === 200 && data.answer) {
      appendMessage('bot', data.answer);
    } else if(data.answer) {
      appendMessage('bot', data.answer);
    } else if(data.error) {
      appendMessage('bot', '[ERROR] ' + data.error);
    } else {
      appendMessage('bot', '[ERROR] Unexpected response');
    }
  } catch (e) {
    chatEl.removeChild(chatEl.lastChild);
    appendMessage('bot', '[ERROR] ' + e.toString());
  }
});

promptEl.addEventListener('keydown', (e) => {
  if(e.key === 'Enter') sendBtn.click();
});
</script>
</body>
</html>
"""

ADMIN_LOGIN_HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>CYOAI Admin Login</title></head>
<body>
  <h3>CYOAI Admin — Login</h3>
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <ul style="color:red">
      {% for m in messages %}<li>{{ m }}</li>{% endfor %}
      </ul>
    {% endif %}
  {% endwith %}
  <form method="post" action="/admin/login">
    <label>Password: <input type="password" name="password" /></label>
    <button type="submit">Login</button>
  </form>
  <p><a href="/">Back to Chat</a></p>
</body>
</html>
"""

ADMIN_DASH_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>CYOAI Admin</title>
  <style>body{font-family:Arial;margin:20px;} table{border-collapse:collapse;} td,th{border:1px solid #ccc;padding:6px;}</style>
</head>
<body>
  <h3>CYOAI Admin Dashboard</h3>
  <p><a href="/">View Chat</a> | <a href="/admin/logout">Logout</a></p>

  <h4>Blocked Rules ({{ rules|length }})</h4>
  <table>
    <tr><th>Index</th><th>Pattern / Keyword</th><th>Action</th></tr>
    {% for i,r in enumerate(rules) %}
      <tr>
        <td>{{ i }}</td>
        <td><code>{{ r }}</code></td>
        <td>
          <form method="post" action="/admin/remove" style="display:inline">
            <input type="hidden" name="index" value="{{ i }}" />
            <button type="submit">Remove</button>
          </form>
        </td>
      </tr>
    {% endfor %}
  </table>

  <h4>Add New Rule</h4>
  <form method="post" action="/admin/add">
    <label>Keyword or pattern: <input type="text" name="pattern" /></label>
    <p>To use a regex, prefix with <code>re:</code> (e.g. <code>re:\\bexploit\\b</code>)</p>
    <button type="submit">Add</button>
  </form>

  <h4>Actions</h4>
  <form method="post" action="/admin/reload" style="display:inline">
    <button type="submit">Reload rules from disk</button>
  </form>
  <form method="post" action="/admin/reset" style="display:inline" onsubmit="return confirm('Reset rules to defaults?');">
    <button type="submit">Reset to defaults</button>
  </form>

  <p><small>Changes are saved immediately to <code>rules.json</code>.</small></p>
</body>
</html>
"""

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def chat_ui():
    return render_template_string(CHAT_HTML)

@app.route("/chat", methods=["POST"])
def chat_api():
    data = request.get_json(force=True)
    if not data or "prompt" not in data:
        return jsonify({"error": "Please send JSON with a 'prompt' field."}), 400
    prompt = data["prompt"].strip()
    if is_malicious(prompt):
        return jsonify({"answer": "[REFUSED] Your request appears to contain blocked content. "
                                  "Contact admin if you believe this is an error."}), 403

    # Compose the prompt for the LLM
    full_prompt = f"{SYSTEM_INSTRUCTION}\n\nUser: {prompt}\nCYOAI (concise, educational):"
    try:
        answer = generate_text(full_prompt, max_tokens=300)
    except Exception as e:
        return jsonify({"error": f"Model generation failed: {e}"}), 500

    if is_malicious(answer):
        # If model accidentally generated blocked content, refuse
        return jsonify({"answer": "[REFUSED] Generated content may be unsafe. Try a different question."}), 403

    return jsonify({"answer": answer})

# ---------- Admin authentication ----------
def is_admin_logged_in():
    return session.get("is_admin", False) is True

@app.route("/admin", methods=["GET"])
def admin_index():
    if not is_admin_logged_in():
        return render_template_string(ADMIN_LOGIN_HTML)
    rules = load_rules()
    return render_template_string(ADMIN_DASH_HTML, rules=rules)

@app.route("/admin/login", methods=["POST"])
def admin_login():
    pw = request.form.get("password", "")
    if not ADMIN_PASSWORD:
        flash("Admin password not set on server.")
        return redirect(url_for("admin_index"))
    if pw == ADMIN_PASSWORD:
        session["is_admin"] = True
        flash("Logged in.")
        return redirect(url_for("admin_index"))
    else:
        flash("Incorrect password.")
        return redirect(url_for("admin_index"))

@app.route("/admin/logout", methods=["GET"])
def admin_logout():
    session.pop("is_admin", None)
    flash("Logged out.")
    return redirect(url_for("admin_index"))

@app.route("/admin/add", methods=["POST"])
def admin_add_rule():
    if not is_admin_logged_in():
        return redirect(url_for("admin_index"))
    pattern = (request.form.get("pattern") or "").strip()
    if not pattern:
        flash("Empty pattern cannot be added.")
        return redirect(url_for("admin_index"))
    rules = load_rules()
    rules.append(pattern)
    save_rules(rules)
    # refresh in-memory patterns
    global BLOCKED_PATTERNS
    BLOCKED_PATTERNS = load_rules()
    flash(f"Added rule: {pattern}")
    return redirect(url_for("admin_index"))

@app.route("/admin/remove", methods=["POST"])
def admin_remove_rule():
    if not is_admin_logged_in():
        return redirect(url_for("admin_index"))
    try:
        idx = int(request.form.get("index", "-1"))
    except ValueError:
        flash("Invalid index.")
        return redirect(url_for("admin_index"))
    rules = load_rules()
    if 0 <= idx < len(rules):
        removed = rules.pop(idx)
        save_rules(rules)
        BLOCKED_PATTERNS = load_rules()
        flash(f"Removed rule: {removed}")
    else:
        flash("Index out of range.")
    return redirect(url_for("admin_index"))

@app.route("/admin/reload", methods=["POST"])
def admin_reload_rules():
    if not is_admin_logged_in():
        return redirect(url_for("admin_index"))
    global BLOCKED_PATTERNS
    BLOCKED_PATTERNS = load_rules()
    flash("Rules reloaded from disk.")
    return redirect(url_for("admin_index"))

@app.route("/admin/reset", methods=["POST"])
def admin_reset_rules():
    if not is_admin_logged_in():
        return redirect(url_for("admin_index"))
    save_rules(DEFAULT_RULES.copy())
    global BLOCKED_PATTERNS
    BLOCKED_PATTERNS = load_rules()
    flash("Rules reset to default.")
    return redirect(url_for("admin_index"))

# ---------- Run ----------
if __name__ == "__main__":
    print("CYOAI_with_admin starting...")
    print("Model:", MODEL_NAME)
    print("Admin login at /admin (use ADMIN_PASSWORD env var).")
    app.run(host="0.0.0.0", port=APP_PORT)
