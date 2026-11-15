"""Preview first, then resume an explicit legacy-ticket migration with stable keys."""
import argparse
import asyncio
from sqlalchemy import select,func
from .db import Session
from .models import Ticket,Message,Attachment,now
from .shop_bridge import ClientAPI,BridgeError,binding,validate_file,send_files,MAX_BYTES
from .storage import checked_path
from .sla import utc

async def migrate_ticket(session_factory,api,ticket_id,apply=False):
    async with session_factory() as s:
        if apply:await binding(s,api)
        t=await s.scalar(select(Ticket).where(Ticket.id==ticket_id).with_for_update())
        if not t or t.telegram_user_id<=0:raise BridgeError('Нужен существующий Telegram-клиент для переноса')
        if t.shop_import_complete:return {'ticket_id':t.id,'shop_ticket_id':t.shop_ticket_id,'completed':True}
        until=t.shop_import_until_id or await s.scalar(select(func.coalesce(func.max(Message.id),0)).where(Message.ticket_id==t.id))
        rows=(await s.scalars(select(Message).where(Message.ticket_id==t.id,Message.id<=until).order_by(Message.id))).all()
        public=[m for m in rows if m.sender in ('user','operator','system') and not (m.source_key or '').startswith('shop:')]
        if not public:raise BridgeError('Нет клиентской истории для переноса')
        if any(m.sender in ('operator','system') and m.delivery_state not in ('sent','legacy') for m in public):
            raise BridgeError('Сначала сверяйте все неотправленные или неопределённые ответы')
        count=0
        for m in public:
            attachments=(await s.scalars(select(Attachment).where(Attachment.message_id==m.id))).all()
            if len(attachments)>3:raise BridgeError('В сообщении более трёх вложений')
            for item in attachments:
                if item.state!='ready':raise BridgeError('Сначала скачайте все вложения')
                path=checked_path(item.path)
                if path.stat().st_size>MAX_BYTES:raise BridgeError('Старое вложение превышает лимит магазина 2 МБ; перенос остановлен без пропуска файла')
                validate_file(item.filename,path.read_bytes());count+=1
        if count>20:raise BridgeError('В обращении более двадцати клиентских файлов; перенос остановлен')
        payload={'telegram_id':t.telegram_user_id,'subject':t.subject or f'Обращение #{t.id}',
            'created_at':utc(t.created_at).isoformat(),'dry_run':not apply}
        result=await api.request('POST',f'/imports/{t.id}',payload)
        report={'ticket_id':t.id,'shop_ticket_id':result['id'],'messages':len(public),'attachments':count,
            'internal_notes_retained':len(rows)-len(public),'dry_run':not apply}
        if not apply:return report
        s.info['shop_pull']=True
        t.shop_ticket_id=result['id'];t.shop_import_until_id=until;t.channel='shop'
        if result.get('completed'):
            t.shop_import_complete=True;await s.commit();report['completed']=True;return report
        await s.commit()
        last_id=0
        for m in public:
            ids=await send_files(api,s,t,m,import_source_id=t.id)
            data={'body':m.text or 'Вложение','attachment_ids':ids,'role':'customer' if m.sender=='user' else 'admin',
                'created_at':utc(m.created_at).isoformat()}
            sent=await api.request('POST',f'/imports/{t.id}/messages',data,f'sp:{api.instance}:import:{m.id}')
            last_id=max(last_id,sent['id'])
        await api.request('POST',f'/imports/{t.id}/complete',{'status':'resolved' if t.status=='closed' else 'open','expected_message_id':last_id})
        t.shop_import_complete=True;await s.commit();report['completed']=True
        return report

async def run(args):
    async with ClientAPI() as api:
        for tid in args.ticket_id:
            report=await migrate_ticket(Session,api,tid,args.apply)
            # Identifiers and counts only; no customer names, text or secrets in the report.
            print(__import__('json').dumps(report,ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description='Preview legacy support migration; --apply transfers explicit tickets')
    parser.add_argument('--ticket-id',type=int,action='append',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:asyncio.run(run(args))
    except BridgeError as exc:parser.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
