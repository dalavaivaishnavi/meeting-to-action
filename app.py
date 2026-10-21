from datetime import date

import pandas as pd
import streamlit as st

import core
import db
import ui

ui.setup()
db.init()
ss = st.session_state


def secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def to_date(s):
    try:
        return date.fromisoformat(s) if s and core.ISO_DATE.match(s) else None
    except ValueError:
        return None


# ---------- Log in / Sign up ----------
if "user" not in ss:
    ui.hero("📋 Meeting-to-Action Assistant", "Log in to save your meetings and continue where you left off.")
    _, mid_col, _ = st.columns([1, 2, 1])
    with mid_col:
        t_in, t_up = st.tabs(["Log in", "Sign up"])
        with t_in:
            with st.form("login"):
                email = st.text_input("Email")
                pw = st.text_input("Password", type="password")
                if st.form_submit_button("Log in", type="primary"):
                    user, msg = db.login(email, pw)
                    if user:
                        ss["user"] = user
                        st.rerun()
                    st.error(msg)
        with t_up:
            with st.form("signup"):
                email2 = st.text_input("Email", key="su_email")
                pw2 = st.text_input("Password (min 6 characters)", type="password", key="su_pw")
                pw3 = st.text_input("Confirm password", type="password", key="su_pw2")
                if st.form_submit_button("Create account", type="primary"):
                    if pw2 != pw3:
                        st.error("Passwords do not match.")
                    else:
                        user, msg = db.signup(email2, pw2)
                        if user:
                            ss["user"] = user
                            st.rerun()
                        st.error(msg)
    st.stop()

# ---------- State ----------
uid = ss["user"]["id"]
for k, v in dict(meeting_id=None, title="", transcript="", result=None, mdate=date.today(), rev=0).items():
    ss.setdefault(k, v)


def load(mid, title, transcript, result, mdate):
    ss.update(meeting_id=mid, title=title, transcript=transcript, result=result, mdate=mdate, rev=ss["rev"] + 1)


def new_meeting():
    load(None, "", "", None, date.today())


def open_meeting(mid):
    m = db.get_meeting(uid, mid)
    if m:
        load(m["id"], m["title"], m["transcript"], m["result"], date.fromisoformat(m["meeting_date"]))


def delete_current():
    db.delete_meeting(uid, ss["meeting_id"])
    new_meeting()


def persist(flash="Saved ✓"):
    title = ss["title"].strip() or f"Meeting {ss['mdate']}"
    ss["meeting_id"] = db.save_meeting(uid, ss["meeting_id"], title, ss["transcript"], str(ss["mdate"]), ss["result"])
    ss["rev"] += 1
    ss["flash"] = flash


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown(f"👤 **{ss['user']['email']}**")
    if st.button("Log out", use_container_width=True):
        ss.clear()
        st.rerun()
    st.divider()
    st.markdown("### 📚 Your meetings")
    st.button("➕ New meeting", on_click=new_meeting, use_container_width=True, type="primary")
    for m in db.list_meetings(uid):
        mark = "▶ " if m["id"] == ss["meeting_id"] else ""
        st.button(f"{mark}{m['title']}", key=f"m{m['id']}", on_click=open_meeting, args=(m["id"],),
                  use_container_width=True)
    st.divider()
    api_key = secret("GEMINI_API_KEY") or st.text_input("Gemini API key (free)", type="password",
                                                        help="Create one at aistudio.google.com/apikey")
    st.date_input("Meeting date", key="mdate", format="YYYY-MM-DD")
    st.caption("Click the box to pick from a calendar. Used to turn “by Friday” into exact dates.")

# ---------- Main ----------
ui.hero("📋 Meeting-to-Action Assistant",
        "Turn transcripts into summaries, decisions, owned tasks and deadlines, then save and edit them any time.")
if ss.get("flash"):
    st.toast(ss.pop("flash"))

st.markdown('<div class="sec">1 · Add your transcript</div>', unsafe_allow_html=True)
st.text_input("Meeting title", key="title", placeholder="e.g. Product launch sync")
uploaded = st.file_uploader("Upload a .txt transcript (optional)", type=["txt"])
if uploaded and ss.get("_loaded") != (uploaded.name, uploaded.size):
    ss["transcript"] = uploaded.read().decode("utf-8", errors="ignore")
    ss["_loaded"] = (uploaded.name, uploaded.size)
st.text_area("Transcript", key="transcript", height=220, placeholder="Paste the meeting transcript here...")

b1, b2, _ = st.columns([1, 1, 4])
if b1.button("Analyze meeting", type="primary"):
    try:
        client = core.get_client(api_key)
        with st.spinner("Analyzing the meeting..."):
            ss["result"] = core.extract(client, ss["transcript"], str(ss["mdate"]))
        persist("Analyzed and saved ✓")
        st.rerun()
    except Exception as e:
        st.error(str(e))
if b2.button("💾 Save"):
    persist()
    st.rerun()

result = ss["result"]
if result:
    issues = core.validate(result)
    flagged = {i["task_id"] for i in issues}
    p = f"{ss['meeting_id'] or 'new'}_{ss['rev']}"

    st.markdown('<div class="sec">2 · Results</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    ui.metric(cols[0], len(result["tasks"]), "Tasks")
    ui.metric(cols[1], len(result["decisions"]), "Decisions")
    ui.metric(cols[2], len(result["follow_ups"]), "Follow-ups")
    ui.metric(cols[3], len(flagged), "Need clarification", "warn" if flagged else "ok")
    st.write("")

    if issues:
        st.markdown(f'<div class="notice"><b>{len(flagged)} task(s) need your input.</b> '
                    'Fill in what you know. Blank fields are skipped.</div>', unsafe_allow_html=True)
        by_task = {}
        for iss in issues:
            by_task.setdefault(iss["task_id"], []).append(iss)
        desc = {t["id"]: t["description"] for t in result["tasks"]}
        labels = {"owner": "Owner (person's name)", "deadline": "Deadline (pick a date)",
                  "description": "Rewrite as a concrete action"}
        with st.form(f"clar_{p}"):
            answers = {}
            for tid, its in by_task.items():
                st.markdown(f"**{tid} · {desc.get(tid, '')}**")
                st.caption(" · ".join(dict.fromkeys(i["issue"] for i in its)))
                for col, iss in zip(st.columns(len(its)), its):
                    f, key = iss["field"], f"c{p}_{tid}_{iss['field']}"
                    if f == "deadline":
                        v = col.date_input(labels[f], value=None, format="YYYY-MM-DD", key=key)
                        v = v.isoformat() if v else ""
                    else:
                        v = col.text_input(labels[f], key=key)
                    answers.setdefault(tid, {})[f] = v
            if st.form_submit_button("Apply answers", type="primary"):
                core.apply_clarifications(result, answers)
                persist("Answers applied and saved ✓")
                st.rerun()
    else:
        st.markdown('<div class="okbox">✅ All tasks have a clear owner, a concrete deadline and clear wording.</div>',
                    unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Tasks", "Edit tasks", "Follow-ups"])
    with tab1:
        st.markdown('<div class="sec">Summary</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card">{ui.esc(result["summary"])}</div>', unsafe_allow_html=True)
        if result["attendees"]:
            st.markdown('<div class="sec">Attendees</div>', unsafe_allow_html=True)
            st.markdown('<div class="card">' + "".join(f'<span class="badge b-owner">{ui.esc(a)}</span>'
                        for a in result["attendees"]) + "</div>", unsafe_allow_html=True)
        st.markdown('<div class="sec">Decisions</div>', unsafe_allow_html=True)
        if not result["decisions"]:
            st.info("No decisions were recorded.")
        for d in result["decisions"]:
            st.markdown(f'<div class="card"><b>{ui.esc(d.get("decision"))}</b><br>'
                        f'<span style="color:#5B6B82">{ui.esc(d.get("context"))}</span></div>', unsafe_allow_html=True)
    with tab2:
        if not result["tasks"]:
            st.info("No tasks were found.")
        for t in result["tasks"]:
            st.markdown(ui.task_card(t, t["id"] in flagged), unsafe_allow_html=True)
        if result["tasks"]:
            with st.expander("View as table"):
                st.dataframe(pd.DataFrame(result["tasks"]).drop(columns=["needs_clarification"], errors="ignore"),
                             use_container_width=True, hide_index=True)
    with tab3:
        prios = ["high", "medium", "low"]
        with st.form(f"edit_{p}"):
            edits = {}
            for t in result["tasks"]:
                k = f"e{p}_{t['id']}"
                with st.expander(f"{t['id']} · {t['description'][:70]}"):
                    c1, c2, c3 = st.columns(3)
                    o = c1.text_input("Owner", t.get("owner") or "", key=k + "o")
                    d = c2.date_input("Deadline", to_date(t.get("deadline")), format="YYYY-MM-DD", key=k + "d")
                    pr = c3.selectbox("Priority", prios, index=prios.index(t["priority"]) if t["priority"] in prios else 1,
                                      key=k + "p")
                    de = st.text_area("Description", t["description"], height=70, key=k + "t")
                    rm = st.checkbox("Remove this task", key=k + "r")
                    edits[t["id"]] = (o, d, pr, de, rm)
            with st.expander("➕ Add a task"):
                n1, n2 = st.columns(2)
                new_desc = st.text_input("New task description", key=f"n{p}d")
                new_owner = n1.text_input("Owner", key=f"n{p}o")
                new_dl = n2.date_input("Deadline", value=None, format="YYYY-MM-DD", key=f"n{p}l")
            if st.form_submit_button("Save changes", type="primary"):
                kept = []
                for t in result["tasks"]:
                    o, d, pr, de, rm = edits[t["id"]]
                    if rm:
                        continue
                    t.update(owner=o.strip() or None, deadline=d.isoformat() if d else None, priority=pr,
                             description=de.strip() or t["description"], needs_clarification=None)
                    kept.append(t)
                if new_desc.strip():
                    nums = [int(x["id"][1:]) for x in result["tasks"] if x["id"][1:].isdigit()]
                    kept.append(dict(id=f"T{max(nums, default=0) + 1}", description=new_desc.strip(),
                                     owner=new_owner.strip() or None, deadline=new_dl.isoformat() if new_dl else None,
                                     priority="medium", source_quote=None, needs_clarification=None))
                result["tasks"] = kept
                persist("Changes saved ✓")
                st.rerun()
    with tab4:
        if not result["follow_ups"]:
            st.info("No follow-ups were found.")
        for f in result["follow_ups"]:
            st.markdown(f'<div class="card"><b>{ui.esc(f.get("item"))}</b><br>'
                        f'<span class="badge b-owner">👤 {ui.esc(f.get("owner")) or "Unassigned"}</span>'
                        f'<span class="badge b-date">🕒 {ui.esc(f.get("when")) or "No date"}</span></div>',
                        unsafe_allow_html=True)

    st.download_button("⬇️ Download tasks as CSV", core.tasks_to_csv(result), "tasks.csv", "text/csv")

if ss["meeting_id"]:
    with st.expander("Delete this meeting"):
        st.button("Delete permanently", on_click=delete_current)

st.markdown('<div class="foot">Meeting-to-Action Assistant · Powered by Google Gemini</div>', unsafe_allow_html=True)
