"""Request-local team scoping, also covering related records and bulk SQL."""
from contextvars import ContextVar
from sqlalchemy import event, select, or_
from sqlalchemy.orm import Session, with_loader_criteria
from .models import Ticket, Message, Attachment, Client, CallRequest, Notification, Incident, IncidentTicket, TicketRead, Operator, AuditLog

scope = ContextVar('team_scope', default=None)
ROLES = {'admin', 'manager', 'senior_operator', 'operator', 'viewer', 'auditor'}

def can_read(op, ticket):
    return op.role == 'admin' or op.team_id == ticket.team_id

@event.listens_for(Session, 'do_orm_execute')
def team_scope(state):
    context = scope.get()
    if context is None or state.execution_options.get('unscoped'):
        return
    team = context[0]
    condition = Ticket.team_id.is_(None) if team is None else Ticket.team_id == team
    ids = select(Ticket.id).where(condition)
    clients = select(Ticket.telegram_user_id).where(condition)
    operator_condition=Operator.team_id.is_(None) if team is None else Operator.team_id==team
    options = [with_loader_criteria(Operator,operator_condition,include_aliases=True),
               with_loader_criteria(AuditLog,AuditLog.operator_id.in_(select(Operator.id).where(operator_condition)),include_aliases=True),
               with_loader_criteria(Ticket, condition, include_aliases=True),
               with_loader_criteria(Client, Client.telegram_user_id.in_(clients), include_aliases=True),
               with_loader_criteria(Incident, Incident.team_id.is_(None) if team is None else Incident.team_id == team, include_aliases=True)]
    for model in (Message, Attachment, CallRequest, Notification, IncidentTicket, TicketRead):
        options.append(with_loader_criteria(model, model.ticket_id.in_(ids), include_aliases=True))
    state.statement = state.statement.options(*options)
