import html

import streamlit as st

import core

CSS = """<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.4rem; max-width: 1150px;}
.hero {background: linear-gradient(120deg, #14284B 0%, #1F3A5F 60%, #2C5282 100%);
  padding: 28px 34px; border-radius: 14px; margin-bottom: 22px;}
.hero h1 {color: #FFFFFF; font-size: 1.9rem; margin: 0 0 6px 0; padding: 0;}
.hero p {color: #D6E0F0; margin: 0; font-size: 1rem;}
.card {background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 12px; padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(20,40,75,.06); margin-bottom: 12px; color: #1B2430; line-height: 1.55;}
.metric {background: #FFFFFF; border: 1px solid #E3E8F0; border-top: 4px solid #1F3A5F;
  border-radius: 10px; padding: 14px 16px;}
.metric .n {font-size: 1.8rem; font-weight: 700; color: #14284B; line-height: 1.1;}
.metric .l {font-size: .75rem; color: #5B6B82; text-transform: uppercase; letter-spacing: .07em;}
.metric.warn {border-top-color: #B7791F;}
.metric.ok {border-top-color: #2F855A;}
.task {border-left: 5px solid #1F3A5F;}
.task.flag {border-left-color: #B7791F;}
.task .t {font-weight: 600; color: #14284B; font-size: 1.02rem; margin-bottom: 8px;}
.task .id {color: #5B6B82; font-weight: 500; margin-right: 6px;}
.quote {color: #5B6B82; font-style: italic; font-size: .88rem; margin-top: 8px;}
.badge {display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .76rem;
  font-weight: 600; margin: 0 6px 4px 0;}
.b-high {background: #FDECEC; color: #9B2C2C;}
.b-med {background: #FFF4DC; color: #8A5A00;}
.b-low {background: #E6F4EC; color: #1E6B4A;}
.b-owner {background: #E8EEF7; color: #1F3A5F;}
.b-date {background: #EEF2F7; color: #334155;}
.b-need {background: #FFF4DC; color: #8A5A00; border: 1px dashed #D9A441;}
.notice {background: #FFF8E6; border: 1px solid #F0D58A; border-radius: 10px; padding: 12px 16px;
  color: #6B4A00; margin-bottom: 10px;}
.okbox {background: #E9F6EF; border: 1px solid #9AD0B3; border-radius: 10px; padding: 12px 16px;
  color: #1E6B4A; margin-bottom: 10px;}
.sec {color: #14284B; font-weight: 700; font-size: 1.1rem; margin: 6px 0 10px 0;}
.foot {text-align: center; color: #7A8799; font-size: .8rem; margin-top: 30px;}
</style>"""


def setup():
    st.set_page_config(page_title="Meeting-to-Action Assistant", page_icon="📋", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title, sub):
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{sub}</p></div>', unsafe_allow_html=True)


def esc(x):
    return html.escape(str(x)) if x not in (None, "") else ""


def metric(col, number, label, cls=""):
    col.markdown(f'<div class="metric {cls}"><div class="n">{number}</div><div class="l">{label}</div></div>',
                 unsafe_allow_html=True)


def task_card(t, flagged):
    prio = (t.get("priority") or "medium").lower()
    pcls = {"high": "b-high", "medium": "b-med", "low": "b-low"}.get(prio, "b-med")
    owner = (t.get("owner") or "").strip()
    if owner and owner.lower() not in core.GENERIC_OWNERS:
        owner_b = f'<span class="badge b-owner">👤 {esc(owner)}</span>'
    else:
        owner_b = '<span class="badge b-need">👤 Owner needed</span>'
    dl = (t.get("deadline") or "").strip()
    if core.ISO_DATE.match(dl):
        date_b = f'<span class="badge b-date">📅 {esc(dl)}</span>'
    elif dl:
        date_b = f'<span class="badge b-need">📅 {esc(dl)} (confirm date)</span>'
    else:
        date_b = '<span class="badge b-need">📅 Deadline needed</span>'
    quote = f'<div class="quote">“{esc(t.get("source_quote"))}”</div>' if t.get("source_quote") else ""
    cls = "task flag" if flagged else "task"
    return (f'<div class="card {cls}"><div class="t"><span class="id">{esc(t["id"])}</span>{esc(t["description"])}</div>'
            f'{owner_b}{date_b}<span class="badge {pcls}">{esc(prio.title())} priority</span>{quote}</div>')
