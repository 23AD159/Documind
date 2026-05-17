import streamlit as st
import re
import time
import json
import pandas as pd
import altair as alt
from datetime import datetime
from pathlib import Path
import rag_engine as rag
import bcrypt
import os

# ─── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DocuMind – AI Document Intelligence",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── User Database (JSON file) ──────────────────────────────────────────────────
_USERS_FILE = Path("users.json")

def _load_users() -> dict:
    if _USERS_FILE.exists():
        return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    # Seed default admin on first run
    admin_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
    default = {"admin": {"password": admin_hash, "email": "admin@documind.ai", "name": "Admin"}}
    _USERS_FILE.write_text(json.dumps(default, indent=2), encoding="utf-8")
    return default

def _save_users(users: dict):
    _USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")

def _check_password(users: dict, username: str, password: str) -> bool:
    user = users.get(username)
    if not user:
        return False
    try:
        return bcrypt.checkpw(password.encode(), user["password"].encode())
    except Exception:
        return False

def _register_user(users: dict, username: str, password: str, email: str, name: str) -> str:
    """Returns error message or empty string on success."""
    if not username or not password or not name:
        return "Username, name and password are required."
    if len(username) < 3:
        return "Username must be at least 3 characters."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    if username in users:
        return "Username already exists. Please choose another."
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {"password": hashed, "email": email, "name": name}
    _save_users(users)
    return ""

# ─── Global State & Styling ───────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap');

:root {
    --bg-main: #FFFFFF; --bg-card: #F8F9FA;
    --accent: #4C1D95; --accent-light: rgba(76, 29, 149, 0.1);
    --text-p: #1E293B; --text-s: #475569; --text-m: #64748B;
    --border: #E2E8F0;
}

.stApp { 
    background-color: #FFFFFF !important; 
    color: var(--text-p) !important; 
    font-family: 'Inter', sans-serif !important;
    font-size: 1.1rem !important;
}

/* Global Typography */
h1, h2, h3, h4, .stHeader, .page-title, .auth-title { 
    font-family: 'Outfit', sans-serif !important; 
    color: var(--accent) !important;
    font-weight: 700 !important;
}

html, body, [class*="st-"] {
    font-family: 'Inter', sans-serif !important;
}
.material-symbols-rounded, .material-icons, .st-icon {
    font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #F8F9FA !important;
    border-right: 1px solid var(--border) !important;
}
/* Ensure selected sidebar item is visible */
[data-testid="stSidebarNav"] div[data-testid="stSidebarNavItem"] > a[aria-current="page"] {
    background-color: var(--accent-light) !important;
    border-right: 3px solid var(--accent) !important;
}

#MainMenu, footer { visibility: hidden; } /* Do NOT hide header, it contains the mobile sidebar toggle! */
header { background: transparent !important; }

/* Dashboard Cards */
.dm-card { 
    background: #FFFFFF; 
    border: 1px solid var(--border); 
    border-radius: 12px; 
    padding: 1.5rem; 
    margin-bottom: 1.2rem; 
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); 
}

.metric-card { 
    background: #FFFFFF; 
    border: 1px solid var(--border); 
    border-radius: 12px; 
    padding: 1.25rem; 
    text-align: center;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.metric-value { font-family: 'Outfit', sans-serif !important; font-size: 2.4rem; font-weight: 700; color: var(--accent); }
.metric-label { color: var(--text-m); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
.page-title { font-size: 2.6rem; margin-bottom: 1rem; }

/* Chat Components */
.badge { padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; }
.badge-success { background: #DCFCE7; color: #166534; }
.badge-warning { background: #FEF3C7; color: #92400E; }

/* Markdown visibility */
.stMarkdown p, .stMarkdown li, .stMarkdown span, .stMarkdown div {
    color: var(--text-p) !important;
}

/* Main content area background */
[data-testid="stAppViewContainer"] > .main {
    background-color: #FFFFFF !important;
}

/* Alert Visibility Fixes */
[data-testid="stNotification"] {
    border-radius: 8px !important;
}

/* Chat Component Overrides to ensure text is visible */
.chat-user-bubble { 
    background: var(--accent); color: #FFFFFF !important; border-radius: 12px 12px 0 12px; padding: 1rem; margin: 0.6rem 0; 
    max-width: 80%; margin-left: auto; box-shadow: 0 4px 12px rgba(88, 28, 135, 0.1);
}
.chat-user-bubble * { color: #FFFFFF !important; }

.chat-ai-bubble { 
    background: #F1F5F9; border: 1px solid var(--border); border-radius: 12px 12px 12px 0; padding: 1rem; 
    margin: 0.6rem 0; max-width: 90%; color: var(--text-p) !important;
}
.chat-ai-bubble * { color: var(--text-p) !important; }

/* Auth Screen Specific overrides */
.auth-title { font-size: 2.8rem !important; margin-bottom: 0.5rem; text-align: center; }
.auth-sub   { color: var(--text-s); font-size: 1.1rem; margin-bottom: 2rem; text-align: center; }

/* Text Inputs */
.stTextInput label p { color: var(--text-p) !important; font-weight: 600 !important; }
.stTextInput > div > div > input { color: var(--text-p) !important; }

/* Force Tabs to Dark Mode */
div[data-testid="stTabs"] button p { font-weight: 600 !important; color: var(--text-m) !important; }
div[data-testid="stTabs"] button[aria-selected="true"] p { color: var(--accent) !important; font-weight: 700 !important; }

/* File Uploader */
[data-testid="stFileUploader"] * { color: var(--text-p) !important; }
[data-testid="stFileUploaderDropzone"] { border: 2px dashed var(--border) !important; }

/* Selectboxes */
.stSelectbox label { color: var(--text-p) !important; font-weight: 600 !important; }

/* Radio Buttons */
.stRadio label { color: var(--text-p) !important; font-weight: 600 !important; }

/* Buttons */
.stButton > button, [data-testid="stDownloadButton"] > button { background-color: var(--accent) !important; color: #FFFFFF !important; border: none !important; border-radius: 8px !important; font-weight: 600 !important; }
.stButton > button p, [data-testid="stDownloadButton"] > button p { color: #FFFFFF !important; font-weight: 600 !important; }
.stButton > button:hover, [data-testid="stDownloadButton"] > button:hover { background-color: #8B5CF6 !important; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(124, 58, 237, 0.3); }

/* Sidebar buttons */
[data-testid="stSidebar"] .stButton > button { background-color: #FFFFFF !important; color: var(--accent) !important; border: 1px solid var(--accent) !important; font-weight: 600 !important; }
[data-testid="stSidebar"] .stButton > button p { color: var(--accent) !important; }
[data-testid="stSidebar"] .stButton > button:hover { background-color: var(--accent) !important; color: #FFFFFF !important; }
</style>
""", unsafe_allow_html=True)

# ─── Session State Init ────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "auth_user" not in st.session_state:
    st.session_state.auth_user = ""

# ─── Auth Screen ─────────────────────────────────────────────────────────────────
if not st.session_state.authenticated:
    st.markdown("<div class='auth-title'>🧠 DocuMind AI</div>", unsafe_allow_html=True)
    st.markdown("<div class='auth-sub'>AI-Powered Document Intelligence</div>", unsafe_allow_html=True)

    _users = _load_users()

    # Center the authentication forms for a premium layout
    _, auth_col, _ = st.columns([1, 2, 1])
    with auth_col:
        tab_login, tab_reg = st.tabs(["🔑 Login", "📝 Register"])

        with tab_login:
            _lu = st.text_input("Username", key="login_u")
            _lp = st.text_input("Password", type="password", key="login_p")
            if st.button("Login", use_container_width=True, key="btn_login"):
                if _check_password(_users, _lu, _lp):
                    st.session_state.authenticated = True
                    st.session_state.auth_user = _lu
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password")

        with tab_reg:
            _rname = st.text_input("Full Name", key="reg_name")
            _ru    = st.text_input("Username", key="reg_u")
            _remail = st.text_input("Email (optional)", key="reg_email")
            _rp    = st.text_input("Password", type="password", key="reg_p")
            _rp2   = st.text_input("Confirm Password", type="password", key="reg_p2")
            if st.button("Register", use_container_width=True, key="btn_reg"):
                if _rp != _rp2:
                    st.error("❌ Passwords do not match")
                else:
                    _users = _load_users()
                    err = _register_user(_users, _ru, _rp, _remail, _rname)
                    if err:
                        st.error(f"❌ {err}")
                    else:
                        st.success(f"✅ Account created! Welcome, {_rname}. Please login.")

    st.stop()




name = st.session_state.auth_user

if st.session_state.authenticated:

    # ─── Session State ─────────────────────────────────────────────────────────────
    if "domain" not in st.session_state: st.session_state.domain = "General"
    if "chat_history" not in st.session_state: st.session_state.chat_history = rag.load_json("history.json", [])
    if "active_page" not in st.session_state: st.session_state.active_page = "Dashboard"
    if "engine_ready" not in st.session_state: st.session_state.engine_ready = False
    if "query_log" not in st.session_state: st.session_state.query_log = rag.load_json("stats.json", [])
    if "current_doc" not in st.session_state: st.session_state.current_doc = None
    if "persona" not in st.session_state: st.session_state.persona = "Professional"
    if "interests" not in st.session_state: st.session_state.interests = "General Knowledge"
    if "domain" not in st.session_state: st.session_state.domain = "General"

    # ─── Engine ─────────────────────────────────────────────────────────────────────
    def _init_engine():
        if st.session_state.engine_ready: return
        bar = st.progress(0, text="🧠 Initialising local AI engine...")
        def _pcb(f, m): bar.progress(min(f, 1.0), text=m)
        rag.initialise(progress_cb=_pcb)
        st.session_state.engine_ready = True; bar.empty()

    def _save_chat(): rag.save_json("history.json", st.session_state.chat_history)
    def _log_query():
        day = datetime.now().strftime("%a")
        if st.session_state.query_log and st.session_state.query_log[-1]["day"] == day: st.session_state.query_log[-1]["count"] += 1
        else: st.session_state.query_log.append({"day": day, "count": 1})
        rag.save_json("stats.json", st.session_state.query_log)

    def render_confidence(score):
        color = "#10b981" if score >= 85 else "#f59e0b"
        st.markdown(f"<div style='font-size:0.8rem; color:{color}; font-weight:600;'>🎯 Confidence: {score}%</div>", unsafe_allow_html=True)

    # ─── Sidebar ────────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 🧠 DocuMind AI")
        st.markdown(f"👤 **{name}**")
        st.markdown("<div style='background:#EDE9FE; color:#4C1D95; padding:4px 10px; border-radius:8px; font-size:0.75rem; font-weight:700; display:inline-block; margin-bottom:0.5rem;'>🏠 Running Locally · No API Key</div>", unsafe_allow_html=True)
        if st.button("🚪 Logout"):
            st.session_state.authenticated = False
            st.session_state.auth_user = ""
            st.rerun()
        st.markdown("---")
        
        nav = { 
            "🏠 Dashboard": "Dashboard", 
            "🎯 Executive Reports": "Executive Reports",
            "📅 Timeline Builder": "Timeline Builder",
            "🎓 Study Mode": "Study Mode",
            "💬 Chat / Q&A": "Chat / Q&A", 
            "📋 Summaries": "Summaries", 
            "📚 Library": "Document Library", 
            "⚙️ Settings": "Settings" 
        }
        if st.session_state.auth_user == "admin":
            nav["🛡️ Admin Panel"] = "Admin Panel"
            
        curr = next((k for k,v in nav.items() if v == st.session_state.active_page), "🏠 Dashboard")
        sel = st.radio("NAV", list(nav.keys()), index=list(nav.keys()).index(curr), label_visibility="collapsed")
        st.session_state.active_page = nav[sel]
        st.markdown("---")
        up = st.file_uploader("Upload", type=["pdf", "txt", "png", "jpg", "jpeg"])
        if up:
            _init_engine()
            save_dir = Path("uploads"); save_dir.mkdir(exist_ok=True)
            save_path = save_dir / up.name; save_path.write_bytes(up.getvalue())
            with st.spinner("Indexing..."): res = rag.index_document(str(save_path))
            if not res.get("error"):
                st.session_state.current_doc = up.name; st.success("Indexed!"); st.rerun()

    _init_engine()
    page = st.session_state.active_page
    docs = rag.list_indexed_docs()

    # ─── Pages ──────────────────────────────────────────────────────────────────────
    if page == "Dashboard":
        st.markdown("<div class='page-title'>📊 Dashboard</div>", unsafe_allow_html=True)

        total_queries = sum(q['count'] for q in st.session_state.query_log)
        total_chunks  = sum(d['chunks'] for d in docs)
        total_pages   = sum(d.get('pages', 0) for d in docs)
        # Estimate: each manual search through docs takes ~3 minutes vs ~5 seconds with AI
        time_saved_sec = total_queries * (3 * 60 - 5)
        if time_saved_sec >= 3600:
            time_saved_str = f"{time_saved_sec // 3600}h {(time_saved_sec % 3600) // 60}m"
        elif time_saved_sec >= 60:
            time_saved_str = f"{time_saved_sec // 60}m {time_saved_sec % 60}s"
        else:
            time_saved_str = f"{time_saved_sec}s"

        # ── Row 1: Key metrics ──
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='metric-card'><div class='metric-value'>{len(docs)}</div><div class='metric-label'>📄 Documents</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='metric-card'><div class='metric-value'>{total_queries}</div><div class='metric-label'>🔍 Queries</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='metric-card'><div class='metric-value'>{total_chunks}</div><div class='metric-label'>🧩 Chunks</div></div>", unsafe_allow_html=True)
        c4.markdown(f"<div class='metric-card'><div class='metric-value'>{total_pages}</div><div class='metric-label'>📑 Pages Indexed</div></div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Row 2: Predictive Intelligence (Trends & Risks) ──
        st.markdown("<br>", unsafe_allow_html=True)
        with st.spinner("Analyzing Intelligence patterns..."):
            trends_data = rag.predict_trends(st.session_state.gemini_key)
        
        col_pi, col_gap = st.columns([2, 1])
        with col_pi:
            t_data = trends_data.get('trends', [])
            t_html = "".join([f"<p style='margin:0 0 0.5rem 0;'>• {t}</p>" for t in t_data]) if isinstance(t_data, list) else f"<p style='margin:0 0 0.5rem 0;'>• {t_data}</p>"
            r_data = trends_data.get('risks', [])
            r_html = "".join([f"<p style='margin:0 0 0.5rem 0;'>• {r}</p>" for r in r_data]) if isinstance(r_data, list) else f"<p style='margin:0 0 0.5rem 0;'>• {r_data}</p>"
            
            # Note: No indentation in the HTML string below to prevent Streamlit from wrapping it in a `<pre><code>` block.
            st.markdown(f"""
<div class='dm-card' style='border-left: 5px solid var(--accent);'>
<h3 style='margin-top:0;'>🔮 Predictive Intelligence</h3>
<p style='color:var(--text-s); font-size:1.05rem; margin-bottom:1.5rem;'>{trends_data.get('summary', 'Analyzing dataset for long-term indicators...')}</p>
<h4 style='color:var(--success); margin-bottom:0.5rem;'>📈 Emerging Trends</h4>
{t_html}
<br>
<h4 style='color:var(--warning); margin-bottom:0.5rem;'>⚠️ Future Risks</h4>
{r_html}
</div>
            """, unsafe_allow_html=True)
            
        with col_gap:
            st.markdown("<div class='dm-card'>", unsafe_allow_html=True)
            st.subheader("🧩 Knowledge Gaps")
            st.markdown("<p style='font-size:0.85rem; color:var(--text-secondary);'>Topics mentioned but not fully explored in your files:</p>", unsafe_allow_html=True)
            for g in rag.detect_knowledge_gaps():
                st.markdown(f"<span class='badge badge-warning' style='display:inline-block; margin-bottom:0.4rem;'>Gap: {g}</span>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # ── Row 3: Document Analytics (Sentiment) ──
        st.markdown("<br>#### 📑 Document Health & Sentiment", unsafe_allow_html=True)
        if docs:
            # Create a nice sentiment grid
            cols = st.columns(min(len(docs), 3))
            for i, d in enumerate(docs[:6]): # Show top 6
                sentiment = rag.analyze_sentiment(d['name'])
                s_color = "#059669" if sentiment == "Positive" else ("#DC2626" if sentiment == "Negative" else "#64748B")
                with cols[i % 3]:
                    st.markdown(f"""
                    <div class='metric-card' style='padding:1rem; margin-bottom:1rem;'>
                        <div style='font-size:0.9rem; font-weight:600; color:var(--text-primary); margin-bottom:0.4rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;' title='{d['name']}'>{d['name']}</div>
                        <div style='display:flex; justify-content:space-between; align-items:center;'>
                            <span style='font-size:0.75rem; color:var(--text-muted);'>{d['chunks']} Chunks</span>
                            <span style='color:{s_color}; font-size:0.7rem; font-weight:700; background:{s_color}1a; padding:2px 8px; border-radius:12px;'>{sentiment.upper()}</span>
                        </div>
                    </div>""", unsafe_allow_html=True)
        else:
            st.info("Upload documents to see advanced analytics.")
            
        # ── Row 4: Top Discussed Concepts & Query Trends ──
        c_left, c_right = st.columns([1, 2])
        with c_left:
            st.markdown("<div class='dm-card'>", unsafe_allow_html=True)
            st.subheader("🔝 Top Discussed Concepts")
            top_concepts = rag.get_top_concepts()
            if top_concepts:
                for concept, count in top_concepts:
                    st.markdown(f"<div style='display:flex; justify-content:space-between; font-size:0.9rem; margin-bottom:0.4rem;'><span>{concept}</span><span style='color:var(--accent); font-weight:700;'>{count} refs</span></div>", unsafe_allow_html=True)
            else:
                st.write("No concepts extracted yet.")
            st.markdown("</div>", unsafe_allow_html=True)
            
        with c_right:
            st.markdown("<div class='dm-card'>", unsafe_allow_html=True)
            st.subheader("📈 Query Activity")
            if st.session_state.query_log:
                df_log = pd.DataFrame(st.session_state.query_log)
                chart = alt.Chart(df_log).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#581C87").encode(
                    x=alt.X("day:N", title="Day", sort=None),
                    y=alt.Y("count:Q", title="Queries"),
                    tooltip=["day", "count"]
                ).properties(height=160).configure_axis(
                    labelColor="#374151", titleColor="#374151", gridColor="#F3F4F6"
                ).configure_view(strokeWidth=0).configure(background="white")
                st.altair_chart(chart, use_container_width=True)
            else:
                st.write("Start asking questions to see trends!")
            st.markdown("</div>", unsafe_allow_html=True)

        # ── Insight Banner ──
        if total_queries == 0:
            st.info("👋 Welcome to DocuMind! Upload a document and ask your first question to get started.")

    elif page == "Executive Reports":
        st.markdown("<div class='page-title'>🎯 1-Click Executive Reports</div>", unsafe_allow_html=True)
        st.write("Generate highly engineered, comprehensive intelligence reports without typing a single prompt.")
        
        col1, col2, col3 = st.columns(3)
        report_types = {
            "🚨 Comprehensive Risk Assessment": "Analyze all documents and generate a highly detailed Risk Assessment report. Identify potential legal, financial, or technical risks mentioned in the text. Format the output with clear headers, bullet lists, and a severity rating (High, Medium, Low) for each item.",
            "🛠️ Action Items & Next Steps": "Extract a complete, bulleted list of all Action Items, Next Steps, To-Dos, and Pending Tasks mentioned across all documents. For each item, specify who is responsible (if mentioned) and the deadline.",
            "🤝 Executive Board Summary": "Write a high-level executive summary summarizing the core themes, major decisions, and pivotal conclusions from the entire knowledge base. Write it in a professional, authoritative tone suitable for a Board of Directors."
        }
        
        if "report_output" not in st.session_state:
            st.session_state.report_output = ""
            
        with col1:
            if st.button("🚨 Generate Risk Assessment", use_container_width=True):
                with st.spinner("Analyzing cross-document risks..."):
                    _init_engine()
                    res = rag.answer_question(report_types["🚨 Comprehensive Risk Assessment"], top_k=6, doc_filter="all", persona="Analyst")
                    st.session_state.report_output = f"### 🚨 Comprehensive Risk Assessment\n\n{res['answer']}"
        with col2:
            if st.button("🛠️ Extract Action Items", use_container_width=True):
                with st.spinner("Compiling global action items..."):
                    _init_engine()
                    res = rag.answer_question(report_types["🛠️ Action Items & Next Steps"], top_k=6, doc_filter="all", persona="Assistant")
                    st.session_state.report_output = f"### 🛠️ Global Action Items\n\n{res['answer']}"
        with col3:
            if st.button("🤝 Executive Summary", use_container_width=True):
                with st.spinner("Drafting board-level summary..."):
                    _init_engine()
                    res = rag.answer_question(report_types["🤝 Executive Board Summary"], top_k=6, doc_filter="all", persona="Professional")
                    st.session_state.report_output = f"### 🤝 Executive Board Summary\n\n{res['answer']}"
                    
        if st.session_state.report_output:
            st.markdown("---")
            st.markdown(st.session_state.report_output)
            st.download_button("💾 Download Report as Markdown", st.session_state.report_output, "executive_report.md", "text/markdown")

    elif page == "Timeline Builder":
        st.markdown("<div class='page-title'>📅 Chronological Timeline Builder</div>", unsafe_allow_html=True)
        st.write("Automatically extracts explicitly dated events from your documents and plots them on a timeline.")
        
        if "timeline_data" not in st.session_state:
            st.session_state.timeline_data = None
            
        if st.button("🔍 Sweep Documents & Build Timeline"):
            with st.spinner("Sweeping vector database for dates and chronological events (this may take a moment)..."):
                _init_engine()
                prompt = """Analyze the document context and extract ALL events with specific dates or timeframes (years, months, specific days). 
                
                FORMAT REQUIREMENTS:
                - Return a Markdown list.
                - Each item MUST contain a date in brackets [YYYY-MM-DD] or [Year].
                - Separate the date and description with a pipe '|' or colon ':'.
                - Example: [2023-10-15] | Project Kickoff | Planning.pdf
                
                If no specific dates are found, respond with "No dated events found."
                """
                res = rag.answer_question(prompt, top_k=10, doc_filter="all", persona="Assistant")
                
                # Robust Parsing with Regex
                raw_lines = res['answer'].split('\n')
                parsed_events = []
                date_regex = r"\[(\d{4}[-\d]*?)\]" # Matches [YYYY] or [YYYY-MM-DD]
                
                for line in raw_lines:
                    line = line.strip()
                    if not line: continue
                    
                    # Try to find date in brackets
                    match = re.search(date_regex, line)
                    if match:
                        date_val = match.group(1)
                        # Remove the date part to get description
                        desc = re.sub(date_regex, "", line).strip("- ").strip("| ").strip(": ").strip()
                        if desc:
                            # Try to split by pipe or colon if present
                            parts = re.split(r"[|:]", desc)
                            event = parts[0].strip()
                            source = parts[1].strip() if len(parts) > 1 else "Document Context"
                            parsed_events.append(f"[{date_val}] | {event} | {source}")

                if not parsed_events:
                    st.session_state.timeline_data = "No explicit dated events could be extracted. The document may not contain specific dates."
                else:
                    st.session_state.timeline_data = parsed_events
                    
        if st.session_state.timeline_data:
            st.markdown("---")
            if isinstance(st.session_state.timeline_data, str):
                st.warning(st.session_state.timeline_data)
            else:
                st.markdown("### ⏳ Chronological Map")
                # Visual timeline layout
                for line in st.session_state.timeline_data:
                    try:
                        date_part = line.split('|')[0].strip().replace('[', '').replace(']', '').replace('-', '')
                        event_part = line.split('|')[1].strip()
                        source_part = line.split('|')[2].strip() if len(line.split('|')) > 2 else "Extracted Context"
                        
                        st.markdown(f"""
                        <div style='display:flex; margin-bottom: 20px; border-left: 3px solid var(--accent); padding-left: 20px; position:relative;'>
                            <div style='position:absolute; left:-9px; top:0px; width:15px; height:15px; border-radius:50%; background:var(--accent);'></div>
                            <div style='min-width: 120px; font-weight:700; color:#4C1D95; font-family:"Outfit",sans-serif;'>{date_part}</div>
                            <div style='flex-grow:1;'>
                                <div style='font-size:1.1rem; color:#111827;'>{event_part}</div>
                                <div style='font-size:0.8rem; color:#6B7280; margin-top:4px;'>📌 Source: {source_part}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    except Exception:
                        st.write(f"- {line}")
                        
        else:
            st.info("Click the sweep button to instruct the AI to build your interactive timeline.")

    elif page == "Study Mode":
        st.markdown("<div class='page-title'>🎓 Study Mode</div>", unsafe_allow_html=True)
        st.write("Turn your documents into interactive quizzes and flashcards instantly.")
        
        if not st.session_state.current_doc:
            st.info("ℹ️ Select or upload a document in Chat / Q&A first.")
        else:
            st.markdown(f"**📄 Document:** `{st.session_state.current_doc}`")
            study_mode = st.radio("Style", ["Quiz", "Flashcards"], horizontal=True)
            
            if "study_materials" not in st.session_state:
                st.session_state.study_materials = {}
            if "quiz_results" not in st.session_state:
                st.session_state.quiz_results = {}
                
            doc_study_key = f"{st.session_state.current_doc}_{study_mode}"
            
            if st.button("⚡ Generate Study Material", use_container_width=True):
                with st.spinner(f"Generating {study_mode}..."):
                    res = rag.generate_study_materials(st.session_state.current_doc, mode=study_mode, api_key=st.session_state.gemini_key)
                    if res:
                        if len(res) > 0 and res[0].get("type") == "error":
                            st.error(res[0].get("question", "Failed to generate study materials."))
                        else:
                            st.session_state.study_materials[doc_study_key] = res
                            st.session_state.quiz_results[doc_study_key] = [None] * len(res)
                            st.success(f"✅ Generated {len(res)} {study_mode} items!")
                    else:
                        st.error("Could not generate study materials. Ensure the document is indexed and contains enough text.")
            
            materials = st.session_state.study_materials.get(doc_study_key, [])
            if materials:
                # Ensure results dict is initialized for this key
                if doc_study_key not in st.session_state.quiz_results:
                    st.session_state.quiz_results[doc_study_key] = [None] * len(materials)
                
                st.markdown("---")
                if study_mode == "Flashcards":
                    st.markdown("### 🗂️ Flashcards")
                    for i, card in enumerate(materials):
                        with st.expander(f"Card {i+1}: **{card.get('front', 'Unknown')}**"):
                            st.write(card.get('back', 'Unknown'))
                else:
                    st.markdown("### 📝 Multiple Choice Quiz")
                    score = 0
                    completed = 0
                    for i, q in enumerate(materials):
                        st.markdown(f"**Q{i+1}: {q.get('question', 'Unknown')}**")
                        opts = q.get("options", [])
                        
                        # Use a more interactive approach
                        ans = st.radio(f"Select answer for Q{i+1}:", opts, key=f"quiz_{doc_study_key}_{i}", index=None, label_visibility="collapsed")
                        
                        if ans:
                            st.session_state.quiz_results[doc_study_key][i] = (ans == q.get("answer"))
                            if ans == q.get("answer"):
                                st.markdown("<span style='color:#059669; font-weight:600;'>✅ Correct!</span>", unsafe_allow_html=True)
                                score += 1
                            else:
                                st.markdown(f"<span style='color:#DC2626; font-weight:600;'>❌ Incorrect. Correct: {q.get('answer')}</span>", unsafe_allow_html=True)
                            
                            with st.expander("Why?"):
                                st.write(q.get('explanation', 'No explanation provided.'))
                            completed += 1
                        st.markdown("---")
                    
                    if completed == len(materials) and len(materials) > 0:
                        st.markdown(f"""
                        <div class='dm-card' style='text-align:center; background:var(--accent-light); border: 2px solid var(--accent);'>
                            <h2 style='margin:0;'>🏆 Quiz Complete!</h2>
                            <div style='font-size:3rem; font-weight:800; color:var(--accent);'>{score} / {len(materials)}</div>
                            <p style='color:var(--text-s);'>Your accuracy: {int(score/len(materials)*100)}%</p>
                        </div>
                        """, unsafe_allow_html=True)
                        if st.button("🔄 Retake Quiz"):
                            st.session_state.study_materials[doc_study_key] = []
                            st.rerun()

    elif page == "Chat / Q&A":
        st.markdown("<div class='page-title'>💬 Chat / Q&A</div>", unsafe_allow_html=True)
        mode = st.radio("Search Mode", ["Single Doc", "Global Search"], horizontal=True)
        ctx = st.session_state.current_doc if mode == "Single Doc" else "all"
        
        tab1, tab2 = st.tabs(["💬 Ask", "📜 History"])
        with tab1:
            # ── Document selector always visible in Single Doc mode ──
            if mode == "Single Doc":
                st.markdown("**📄 Select or Upload a Document**")
                col_sel, col_up = st.columns([3, 2])
                with col_sel:
                    doc_names = [d["name"] for d in docs]
                    if doc_names:
                        chosen = st.selectbox(
                            "Choose from existing",
                            ["— select —"] + doc_names,
                            index=(["— select —"] + doc_names).index(st.session_state.current_doc)
                                  if st.session_state.current_doc in doc_names else 0,
                            key="doc_selector"
                        )
                        if chosen != "— select —":
                            st.session_state.current_doc = chosen
                            ctx = chosen
                    else:
                        st.info("No documents indexed yet. Upload one →")
                with col_up:
                    new_file = st.file_uploader("Upload new file", type=["pdf", "txt", "png", "jpg", "jpeg"], key="chat_upload", label_visibility="collapsed")
                    if new_file:
                        _init_engine()
                        save_dir = Path("uploads"); save_dir.mkdir(exist_ok=True)
                        save_path = save_dir / new_file.name
                        save_path.write_bytes(new_file.getvalue())
                        with st.spinner("Indexing..."):
                            res = rag.index_document(str(save_path))
                        if res.get("error"):
                            st.error(f"Indexing failed: {res['error']}")
                        elif not res.get("skipped"):
                            st.session_state.current_doc = new_file.name
                            st.success(f"✅ '{new_file.name}' indexed!")
                            st.rerun()
                        else:
                            st.session_state.current_doc = new_file.name
                            ctx = new_file.name
                
                st.markdown("---")
                st.session_state.domain = st.selectbox("⚖️ Intelligence Domain", ["General", "Legal", "Medical", "Research"], index=["General", "Legal", "Medical", "Research"].index(st.session_state.domain))
                ctx = st.session_state.current_doc if st.session_state.current_doc else "all"
                st.markdown("---")

            # ── Question input: always show, just warn if no doc in Single Doc mode ──
            if mode == "Single Doc" and not st.session_state.current_doc:
                st.warning("⬆️ Please select or upload a document above to search within it.")
            col1, col_vx, col2 = st.columns([3, 1, 1])
            with col1: q = st.text_input("Your question", placeholder="Type your question here...", label_visibility="collapsed")
            with col_vx:
                if st.button("🎤 Voice Search", key="voice_btn"):
                    st.info("🎤 Listening...")
                    st.components.v1.html("""<script>
                    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
                    if (SR) { const r = new SR(); r.onresult = (e) => { alert("Heard: " + e.results[0][0].transcript); }; r.start(); }
                    else { alert("Speech not supported."); }
                    </script>""", height=0)
            with col2:
                complexity_level = st.selectbox("Complexity", ["Explain Like I'm 10 (ELI5)", "Beginner", "Intermediate", "Expert"], index=3, label_visibility="collapsed")

            col_btn, col_mh = st.columns([3, 1])
            use_multihop = col_mh.toggle("🚀 Multi-Hop", key="mh_toggle", help="Connects multiple pieces of info.")
            
            if col_btn.button("🔍 Search", use_container_width=True):
                if q:
                    st.session_state.chat_history.append({"role": "user", "content": q})
                    with st.spinner("Analyzing with Multi-Hop Engine..." if use_multihop else "Thinking..."):
                        if use_multihop:
                            res = rag.multi_hop_answer_question(q, doc_filter=ctx, api_key=st.session_state.gemini_key, persona=st.session_state.persona, domain=st.session_state.domain)
                        else:
                            res = rag.answer_question(q, doc_filter=ctx, api_key=st.session_state.gemini_key, persona=st.session_state.persona, domain=st.session_state.domain, complexity=complexity_level)
                        
                        st.session_state.chat_history.append({
                            "role": "assistant", 
                            "content": res.get("answer", "No answer returned."), 
                            "source": res.get("source_text", "N/A"), 
                            "confidence": res.get("confidence", 0),
                            "reason": res.get("confidence_reason") or res.get("reasoning", ""),
                            "followups": res.get("followups", []),
                            "highlight": res.get("relevant_sentence", ""),
                            "hops": res.get("hops", []),
                            "graph": res.get("graph_info", False),
                            "query_intent": res.get("query_intent", "Fact-seeking"),
                            "rewritten_q": res.get("rewritten_q") or res.get("rewritten_question", q),
                            "missed_info": res.get("missed_info", "")
                        })
                    _log_query(); _save_chat(); st.rerun()

            if st.session_state.chat_history:
                st.markdown("---")
                # Loop through the last few messages for the active display
                display_msgs = st.session_state.chat_history[-2:]
                for idx_local, m in enumerate(display_msgs):
                    global_idx = len(st.session_state.chat_history) - len(display_msgs) + idx_local
                    cls = "chat-user-bubble" if m["role"] == "user" else "chat-ai-bubble"
                    
                    # Enhanced Cognitive Display for Assistant
                    if m["role"] == "assistant":
                        c_col1, c_col2 = st.columns([3, 1])
                        with c_col1:
                            if m.get("rewritten_q") and m["rewritten_q"] != st.session_state.chat_history[st.session_state.chat_history.index(m)-1]["content"]:
                                st.markdown(f"<div style='font-size:0.8rem; color:var(--text-m); margin-bottom:0.2rem;'><span class='material-icons' style='font-size:0.9rem; vertical-align:middle;'>auto_fix_high</span> <i>Rewritten query: {m['rewritten_q']}</i></div>", unsafe_allow_html=True)
                        with c_col2:
                            if m.get("query_intent"):
                                st.markdown(f"<div style='text-align:right;'><span class='badge' style='background-color:#E0E7FF; color:#3730A3; font-size:0.65rem;'>Intent: {m['query_intent']}</span></div>", unsafe_allow_html=True)

                        # Hallucination Guard
                        if "Answer not found in document" in m["content"] or "I found no relevant info" in m["content"]:
                            st.markdown(f"""
                            <div class='{cls}' style='border: 2px solid #EF4444; background-color:#FEF2F2; position:relative;'>
                                <div style='position:absolute; top:-12px; left:12px; background:#EF4444; color:white; padding:2px 8px; border-radius:4px; font-size:0.7rem; font-weight:800; display:flex; align-items:center;'>
                                    <span class='material-icons' style='font-size:0.9rem; margin-right:4px;'>warning</span> HALLUCINATION GUARD
                                </div>
                                {m['content']}
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div class='{cls}'>{m['content']}</div>", unsafe_allow_html=True)

                        # ELI5 Quick Action Button
                        e1, e2 = st.columns([1, 4])
                        if e1.button("👶 ELI5", key=f"eli5_{global_idx}", help="Simplify this answer"):
                            with st.spinner("Simplifying..."):
                                # Find the user question corresponding to this assistant answer
                                user_q = st.session_state.chat_history[global_idx-1]["content"]
                                eli5_res = rag.answer_question(user_q, doc_filter=ctx, api_key=st.session_state.gemini_key, complexity="Explain Like I'm 10 (ELI5)")
                                st.session_state.chat_history[global_idx]["content"] = eli5_res["answer"]
                                _save_chat()
                                st.rerun()

                        if m.get("missed_info") and "Answer not found" not in m["content"]:
                            st.markdown(f"<div style='background-color:#F0FDF4; border-left: 4px solid #22C55E; padding: 0.75rem; border-radius: 4px; margin-top: 0.5rem;'><b style='color:#166534; font-size: 0.85rem;'>💡 What did I miss?</b><br><span style='font-size:0.9rem; color:#15803D;'>{m['missed_info']}</span></div>", unsafe_allow_html=True)

                        # Hops / Topics
                        if m.get("hops"):
                            st.markdown("<div style='display:flex; gap:0.4rem; flex-wrap:wrap; margin-bottom:0.6rem;'> " + 
                                        "".join([f"<span style='background:rgba(99,102,241,0.1); color:#818cf8; border:1px solid rgba(99,102,241,0.2); border-radius:12px; padding:2px 10px; font-size:0.7rem; font-weight:600;'>🔍 {h['topic']}</span>" for h in m['hops']]) + 
                                        "</div>", unsafe_allow_html=True)

                        # Confidence + Reason
                        c_col1, c_col2 = st.columns([1, 4])
                        color = "#059669" if m["confidence"] >= 85 else "#D97706"
                        c_col1.markdown(f"<div style='font-size:0.85rem; color:{color}; font-weight:700;'>🎯 {m['confidence']}% Match</div>", unsafe_allow_html=True)
                        
                        if m.get("graph"):
                            c_col2.markdown("<span style='background:#EEF2FF; color:#4F46E5; padding:2px 8px; border-radius:6px; font-size:0.75rem; font-weight:700; border:1px solid #C7D2FE;'>🧩 GRAPH-AUGMENTED</span>", unsafe_allow_html=True)
                        
                        if m.get("reason"):
                            st.markdown(f"""
                            <div style='background:#F1F5F9; border-left:4px solid #64748B; padding:0.75rem; margin:0.5rem 0; font-size:0.95rem; border-radius:0 8px 8px 0;'>
                                <div style='font-weight:700; color:#1E293B; font-size:0.75rem; text-transform:uppercase; margin-bottom:0.2rem;'>🧠 Reasoning Chain</div>
                                {m['reason']}
                            </div>
                            """, unsafe_allow_html=True)
                        


                        # Follow-up questions
                        if m.get("followups"):
                            st.markdown("<div style='font-size:0.8rem; color:#94a3b8; margin-top:0.5rem;'>💡 Suggested:</div>", unsafe_allow_html=True)
                            f_cols = st.columns(len(m["followups"]))
                            for i, fq in enumerate(m["followups"]):
                                col = f_cols[i] # type: ignore
                                if col.button(fq, key=f"fu_{i}_{len(st.session_state.chat_history)}", use_container_width=True): # type: ignore
                                    st.session_state.chat_history.append({"role": "user", "content": fq})
                                    with st.spinner("Thinking..."):
                                        res = rag.answer_question(fq, doc_filter=ctx, api_key=st.session_state.gemini_key, persona=st.session_state.persona, domain=st.session_state.domain)
                                        st.session_state.chat_history.append({
                                            "role": "assistant", 
                                            "content": res.get("answer", "No answer returned."), 
                                            "source": res.get("source_text", "N/A"), 
                                            "confidence": res.get("confidence", 0), 
                                            "reason": res.get("confidence_reason") or res.get("reasoning", ""),
                                            "followups": res.get("followups", []), 
                                            "highlight": res.get("relevant_sentence", ""),
                                            "graph": res.get("graph_info", False)
                                        })
                                    _log_query(); _save_chat(); st.rerun()
                        
                        # Auto-Evaluation Feedback Loop with Persistence
                        st.markdown("<div style='display:flex; align-items:center; gap:0.5rem; margin-top:0.8rem; border-top:1px dashed var(--border); padding-top:0.5rem;'> "
                                    "<span style='font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; font-weight:600;'>Quality Check:</span> "
                                    "</div>", unsafe_allow_html=True)
                        fb1, fb2, _ = st.columns([1, 1, 8])
                        if fb1.button("👍", key=f"pos_{len(st.session_state.chat_history)}", help="Helpful answer"):
                            rag.save_feedback(m.get('q_source', 'Follow-up'), m['content'], "Positive") # type: ignore
                            st.toast("Thank you! Feedback helps me improve.")
                        if fb2.button("👎", key=f"neg_{len(st.session_state.chat_history)}", help="Not helpful"):
                            rag.save_feedback(m.get('q_source', 'Follow-up'), m['content'], "Negative") # type: ignore
                            st.toast("Noted. I'll work on being more precise.")

        with tab2:
            for m in reversed(st.session_state.chat_history):
                cls = "chat-user-bubble" if m["role"] == "user" else "chat-ai-bubble"
                st.markdown(f"<div class='{cls}'>{m['content']}</div>", unsafe_allow_html=True)
            if st.button("🗑️ Clear History"): st.session_state.chat_history = []; _save_chat(); st.rerun()

    elif page == "Summaries":
        st.markdown("<div class='page-title'>📋 Summaries</div>", unsafe_allow_html=True)
        if not st.session_state.current_doc:
            st.info("ℹ️ No document selected. Go to Chat / Q&A to select or upload a document first.")
        else:
            st.markdown(f"**📄 Document:** `{st.session_state.current_doc}`")
            st.markdown("---")

            mode_map = {
                "📝 Short Summary": "short",
                "🔑 Key Points": "keypoints",
                "• Bullet Points": "bullets",
            }
            chosen_label = st.radio(
                "Choose generation mode:",
                list(mode_map.keys()),
                horizontal=True,
                key="summary_mode"
            )
            summary_mode = mode_map[chosen_label]

            if st.button("⚡ Generate", use_container_width=True):
                with st.spinner(f"Generating {chosen_label}..."):
                    res = rag.summarise_document(
                        st.session_state.current_doc,
                        mode=summary_mode,
                        api_key=st.session_state.gemini_key
                    )
                confidence = res.get("confidence", 0)
                color = "#10b981" if confidence >= 85 else "#f59e0b"
                st.markdown(
                    f"<div style='font-size:0.8rem;color:{color};font-weight:600;margin-bottom:0.5rem;'>"
                    f"🎯 Confidence: {confidence}%</div>",
                    unsafe_allow_html=True
                )
                st.markdown(f"<div class='dm-card'><h3>{st.session_state.current_doc}</h3>{res['summary']}</div>", unsafe_allow_html=True)

    elif page == "Admin Panel":
        st.markdown("<div class='page-title'>🛡️ Admin Panel</div>", unsafe_allow_html=True)
        
        # User Management
        st.subheader("👤 User Management")
        users_dict = rag.load_json("users.json", {})
        
        for uname, u_info in users_dict.items():
            c1, c2, c3, c4 = st.columns([2, 3, 2, 2])
            name_val = u_info.get('name', 'User')
            email_val = u_info.get('email', 'No email')
            
            c1.write(f"**{name_val}**")
            c2.write(f"({uname})")
            
            if uname != "admin":
                if c3.button("🔄 Reset", key=f"reset_adm_{uname}", use_container_width=True, help="Reset password to 'password123'"):
                    u_info['password'] = bcrypt.hashpw("password123".encode(), bcrypt.gensalt()).decode()
                    rag.save_json("users.json", users_dict)
                    st.success(f"✅ Reset {uname} to 'password123'")
                
                if c4.button("🗑️ Remove", key=f"del_adm_{uname}", use_container_width=True):
                    del users_dict[uname]
                    rag.save_json("users.json", users_dict)
                    st.toast(f"Removed {uname}")
                    st.rerun()
            else:
                c3.markdown("🛡️ **System Admin**")
            st.markdown("<div style='border-bottom: 1px solid var(--border); margin: 0.5rem 0;'></div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        
        # System Health
        st.subheader("🩺 System Health")
        h1, h2, h3 = st.columns(3)
        h1.markdown(f"<div class='metric-card'><div class='metric-value'>{len(docs)}</div><div class='metric-label'>Total Documents</div></div>", unsafe_allow_html=True)
        h2.markdown(f"<div class='metric-card'><div class='metric-value'>{sum(d['chunks'] for d in docs)}</div><div class='metric-label'>Indexed Chunks</div></div>", unsafe_allow_html=True)
        
        try:
            _init_engine()
            h3.markdown("<div class='metric-card'><div class='metric-value' style='color:#10b981;'>ONLINE</div><div class='metric-label'>Gemini API Status</div></div>", unsafe_allow_html=True)
        except:
            h3.markdown("<div class='metric-card'><div class='metric-value' style='color:#ef4444;'>ERROR</div><div class='metric-label'>Gemini API Status</div></div>", unsafe_allow_html=True)

    elif page == "Document Library":
        st.markdown("<div class='page-title'>📚 Library</div>", unsafe_allow_html=True)
        tab_list, tab_graph = st.tabs(["📄 Document List", "🧩 Knowledge Map"])
        
        with tab_list:
            for d in docs:
                col1, col2, col3 = st.columns([3, 1, 1])
                sentiment = rag.analyze_sentiment(d['name'])
                s_color = "#059669" if sentiment == "Positive" else ("#DC2626" if sentiment == "Negative" else "#64748B")
                col1.markdown(f"📄 **{d['name']}** <span style='color:{s_color}; font-size:0.65rem; font-weight:700; background:{s_color}1a; padding:1px 6px; border-radius:10px; margin-left:10px;'>{sentiment}</span>", unsafe_allow_html=True)
                col2.write(f"🧩 {d['chunks']} Chunks")
                if col3.button("Select", key=f"sel_{d['name']}", use_container_width=True):
                    st.session_state.current_doc = d["name"]; st.session_state.active_page = "Chat / Q&A"; st.rerun()
        
        with tab_graph:
            st.markdown("### 🕸️ Cross-Document Knowledge Map")
            st.markdown("Discover connections between entities found in your documents.")
            graph_data = rag.get_graph_data()
            if not graph_data:
                st.info("No connections found yet. Try indexing more documents!")
            else:
                from pyvis.network import Network
                import streamlit.components.v1 as components
                
                net = Network(height='400px', width='100%', bgcolor='#ffffff', font_color='#581C87', directed=True, notebook=True, cdn_resources='remote')
                net.set_options('{"physics": {"forceAtlas2Based": {"gravitationalConstant": -50, "springLength": 100, "springConstant": 0.08}, "minVelocity": 0.75, "solver": "forceAtlas2Based"}}')

                nodes = set()
                for s, r, o in graph_data[:20]: # Limit to 20 for performance
                    if s not in nodes:
                        net.add_node(s, label=s, color='#F5F3FF', shape='box', font={'color': '#581C87', 'face': 'Inter, Arial, sans-serif'})
                        nodes.add(s)
                    if o not in nodes:
                        net.add_node(o, label=o, color='#F5F3FF', shape='box', font={'color': '#581C87', 'face': 'Inter, Arial, sans-serif'})
                        nodes.add(o)
                    net.add_edge(s, o, title=r, label=r, color='#C4B5FD')
                
                html_data = net.generate_html()
                components.html(html_data, height=415)

    elif page == "Settings":
        st.markdown("<div class='page-title'>⚙️ Settings</div>", unsafe_allow_html=True)
        st.markdown("### 👤 User Preferences")
        
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.persona = st.selectbox("AI Style Persona", ["Professional", "Student", "Manager", "Expert"], index=["Professional", "Student", "Manager", "Expert"].index(st.session_state.persona))
        with col2:
            st.session_state.interests = st.text_input("My Specific Focus Areas", value=st.session_state.interests)
            
        if st.session_state.auth_user == "admin":
            st.markdown("---")
            st.markdown("### 🛡️ Admin: User Management")
            users_dict = rag.load_json("users.json", {})
            for uname, u_info in users_dict.items():
                c1, c2, c3 = st.columns([2, 3, 1])
                c1.write(f"👤 **{uname}**")
                c2.write(f"📧 {u_info.get('email')}")
                if uname != "admin":
                    if c3.button("Reset", key=f"set_res_{uname}", use_container_width=True):
                        u_info['password'] = bcrypt.hashpw("password123".encode(), bcrypt.gensalt()).decode()
                        rag.save_json("users.json", users_dict)
                        st.success("Set to 'password123'")
            
            st.markdown("---")
            st.markdown("### 🧹 System")
            if st.button("Re-Index All Documents"):
                st.session_state.engine_ready = False
                st.toast("System will refresh on next action.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("🔑 API Configuration")
        key = st.text_input("Gemini API Key", value=st.session_state.gemini_key, type="password")
        if st.button("Save Configuration", use_container_width=True):
            st.session_state.gemini_key = key
            Path(".env").write_text(f"GEMINI_API_KEY={key}\n")
            st.success("✅ Settings Saved!")
