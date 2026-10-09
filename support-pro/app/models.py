from datetime import datetime, timezone
from sqlalchemy import String, Text, BigInteger, DateTime, ForeignKey, Boolean, Integer, UniqueConstraint, JSON, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for Support Pro persistence models."""


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    calendar: Mapped[dict] = mapped_column(JSON, default=dict)


class Operator(Base):
    __tablename__ = 'operators'
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey('teams.id'))
    login: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default='operator')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    capacity: Mapped[int] = mapped_column(Integer, default=20)
    auth_version: Mapped[int] = mapped_column(Integer, default=1)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    last_totp_step: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Category(Base):
    __tablename__ = 'categories'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Macro(Base):
    __tablename__ = 'macros'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Client(Base):
    __tablename__ = 'clients'
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(255), default='')
    username: Mapped[str] = mapped_column(String(255), default='')
    tags: Mapped[str] = mapped_column(String(500), default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    current_ticket_id: Mapped[int | None] = mapped_column(Integer)


class Ticket(Base):
    __tablename__ = 'tickets'
    shop_import_until_id: Mapped[int | None] = mapped_column(Integer)
    shop_import_complete: Mapped[bool] = mapped_column(Boolean,default=False)
    shop_user_id: Mapped[int | None] = mapped_column(Integer)
    shop_merged_into_id: Mapped[int | None] = mapped_column(Integer)
    shop_history_version: Mapped[str] = mapped_column(String(80),default='')
    shop_scan_version: Mapped[str] = mapped_column(String(80),default='')
    shop_scan_after_id: Mapped[int] = mapped_column(Integer,default=0)
    shop_ticket_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    shop_last_message_id: Mapped[int] = mapped_column(Integer, default=0)
    shop_initial_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str] = mapped_column(String(255), default='')
    full_name: Mapped[str] = mapped_column(String(255), default='')
    team_id: Mapped[int | None] = mapped_column(ForeignKey('teams.id'), index=True)
    channel: Mapped[str] = mapped_column(String(20), default='telegram')
    tags: Mapped[str] = mapped_column(String(500), default='')
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String(255), default='')
    status: Mapped[str] = mapped_column(String(30), default='new', index=True)
    priority: Mapped[str] = mapped_column(String(30), default='normal')
    category_id: Mapped[int | None] = mapped_column(ForeignKey('categories.id'))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey('operators.id'))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_customer_message_id: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[int | None] = mapped_column(Integer)
    rating_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = 'messages'
    __table_args__=(Index('uq_message_shop_identity','shop_message_id',unique=True),)
    shop_message_id: Mapped[int | None] = mapped_column(Integer)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'), index=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey('operators.id'))
    sender: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text, default='')
    delivery_state: Mapped[str] = mapped_column(String(30), default='received', index=True)
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default='')
    text_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Attachment(Base):
    __tablename__ = 'attachments'
    shop_attachment_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey('messages.id'))
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1000), default='')
    content_type: Mapped[str] = mapped_column(String(255), default='application/octet-stream')
    size: Mapped[int] = mapped_column(Integer, default=0)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(30), default='ready')
    error: Mapped[str] = mapped_column(Text, default='')


class TicketRead(Base):
    __tablename__ = 'ticket_reads'
    __table_args__ = (UniqueConstraint('ticket_id', 'operator_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
    operator_id: Mapped[int] = mapped_column(ForeignKey('operators.id'))
    last_message_id: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey('operators.id'), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
    text: Mapped[str] = mapped_column(String(500))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey('operators.id'))
    action: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Settings(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)

class KnowledgeArticle(Base):
    __tablename__ = 'knowledge_articles'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(220))
    slug: Mapped[str] = mapped_column(String(240), unique=True)
    body: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('categories.id'))
    status: Mapped[str] = mapped_column(String(20), default='draft')
    visibility: Mapped[str] = mapped_column(String(20), default='internal')
    views: Mapped[int] = mapped_column(Integer, default=0)
    helpful_yes: Mapped[int] = mapped_column(Integer, default=0)
    helpful_no: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey('operators.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Holiday(Base):
    __tablename__ = 'holidays'
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    is_working: Mapped[bool] = mapped_column(Boolean, default=False)


class AutomationRule(Base):
    __tablename__ = 'automation_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    event: Mapped[str] = mapped_column(String(50))
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    actions: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WebhookEndpoint(Base):
    __tablename__ = 'webhook_endpoints'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str] = mapped_column(String(1000))
    secret: Mapped[str] = mapped_column(String(255))
    events: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str] = mapped_column(Text, default='')
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallRequest(Base):
    __tablename__ = 'call_requests'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    phone: Mapped[str] = mapped_column(String(64), default='')
    preferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey('operators.id'))
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChannelIdentity(Base):
    __tablename__ = 'channel_identities'
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(255), default='')
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkItem(Base):
    __tablename__ = 'work_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(250), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    event: Mapped[str] = mapped_column(String(50))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey('tickets.id'))
    target_id: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SavedView(Base):
    __tablename__ = 'saved_views'
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey('operators.id'))
    name: Mapped[str] = mapped_column(String(100))
    query: Mapped[str] = mapped_column(String(2000))

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey('operators.id'))
    device: Mapped[str] = mapped_column(String(300))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class PortalAccess(Base):
    __tablename__ = 'portal_access'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

class Incident(Base):
    __tablename__ = 'incidents'
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey('teams.id'))
    title: Mapped[str] = mapped_column(String(255))
    draft: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='open')
    revision: Mapped[int] = mapped_column(Integer, default=0)

class IncidentTicket(Base):
    __tablename__ = 'incident_tickets'
    __table_args__ = (UniqueConstraint('incident_id','ticket_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))

class ShopSyncState(Base):
    __tablename__ = 'shop_sync_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(1000))
    instance: Mapped[str] = mapped_column(String(40))
    after_id: Mapped[int] = mapped_column(Integer,default=0)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(String(500),default='')
