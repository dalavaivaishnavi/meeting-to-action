"""Accounts + saved meetings. SQLite locally; any Postgres (Supabase, Neon) via DATABASE_URL."""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text,
                        create_engine, delete, insert, select, update)
from sqlalchemy.exc import IntegrityError

md = MetaData()
users = Table("users", md,
              Column("id", Integer, primary_key=True),
              Column("email", String(255), unique=True, nullable=False),
              Column("salt", String(64), nullable=False),
              Column("pw_hash", String(128), nullable=False),
              Column("created", DateTime(timezone=True)))
meetings = Table("meetings", md,
                 Column("id", Integer, primary_key=True),
                 Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
                 Column("title", String(200)),
                 Column("transcript", Text),
                 Column("meeting_date", String(10)),
                 Column("result", Text),
                 Column("updated", DateTime(timezone=True)))

_engine = None


def _url():
    url = os.getenv("DATABASE_URL")
    try:
        import streamlit as st
        url = st.secrets.get("DATABASE_URL", url)
    except Exception:
        pass
    url = url or "sqlite:///meetings.db"
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url


def init():
    global _engine
    if _engine is None:
        url = _url()
        args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, connect_args=args)
        md.create_all(_engine)


def _now():
    return datetime.now(timezone.utc)


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def signup(email, password):
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return None, "Please enter a valid email address."
    if len(password or "") < 6:
        return None, "Password must be at least 6 characters."
    salt = secrets.token_hex(16)
    try:
        with _engine.begin() as c:
            if c.execute(select(users.c.id).where(users.c.email == email)).first():
                return None, "An account with this email already exists. Please log in instead."
            uid = c.execute(insert(users).values(email=email, salt=salt, pw_hash=_hash(password, salt),
                                                 created=_now())).inserted_primary_key[0]
        return {"id": uid, "email": email}, ""
    except IntegrityError:
        return None, "An account with this email already exists. Please log in instead."


def login(email, password):
    email = (email or "").strip().lower()
    with _engine.connect() as c:
        row = c.execute(select(users).where(users.c.email == email)).mappings().first()
    if not row:
        return None, "No account found with this email. Please sign up first."
    if not hmac.compare_digest(row["pw_hash"], _hash(password or "", row["salt"])):
        return None, "Incorrect password."
    return {"id": row["id"], "email": row["email"]}, ""


def list_meetings(uid):
    with _engine.connect() as c:
        rows = c.execute(select(meetings.c.id, meetings.c.title, meetings.c.meeting_date)
                         .where(meetings.c.user_id == uid).order_by(meetings.c.updated.desc())).mappings().all()
    return [dict(r) for r in rows]


def get_meeting(uid, mid):
    with _engine.connect() as c:
        r = c.execute(select(meetings).where(meetings.c.id == mid, meetings.c.user_id == uid)).mappings().first()
    if not r:
        return None
    d = dict(r)
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d


def save_meeting(uid, mid, title, transcript, meeting_date, result):
    vals = dict(title=title, transcript=transcript, meeting_date=meeting_date,
                result=json.dumps(result) if result else None, updated=_now())
    with _engine.begin() as c:
        if mid:
            c.execute(update(meetings).where(meetings.c.id == mid, meetings.c.user_id == uid).values(**vals))
            return mid
        return c.execute(insert(meetings).values(user_id=uid, **vals)).inserted_primary_key[0]


def delete_meeting(uid, mid):
    with _engine.begin() as c:
        c.execute(delete(meetings).where(meetings.c.id == mid, meetings.c.user_id == uid))
