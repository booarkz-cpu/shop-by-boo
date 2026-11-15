"""One survey engine for cabinet, Mini App and operator tools."""
import hashlib,json
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException,Request,Response,Query
from pydantic import BaseModel,Field,ConfigDict,field_validator,model_validator
from sqlalchemy import select,update
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import User,Subscription,Survey,SurveyResponse,FinancialLedger
from .security import require_permission
router=APIRouter()

class QuestionIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=1000)
    kind:str=Field(default='single',pattern='^(single|multiple|text)$')
    options:list[str]=Field(default_factory=list,max_length=20)
    @field_validator('text')
    @classmethod
    def title(cls,value):
        value=value.strip()
        if not value:raise ValueError('Вопрос не может быть пустым')
        return value
    @model_validator(mode='after')
    def validate_options(self):
        self.options=[o.strip() for o in self.options]
        if any(not o or len(o)>500 for o in self.options):raise ValueError('Вариант ответа: от 1 до 500 символов')
        if len({o.casefold() for o in self.options})!=len(self.options):raise ValueError('Варианты не должны повторяться')
        if self.kind=='text' and self.options:raise ValueError('Текстовый вопрос не использует варианты')
        if self.kind!='text' and len(self.options)<2:raise ValueError('Нужно минимум два варианта')
        return self

class SurveyIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=255)
    description:str=Field(default='',max_length=4000)
    questions:list[QuestionIn]=Field(min_length=1,max_length=20)
    starts_at:datetime
    ends_at:datetime
    max_responses:int=Field(default=1000,ge=1,le=10000)
    reward_amount:Decimal=Field(default=Decimal(0),ge=0,le=10000,max_digits=12,decimal_places=2)
    require_verified_email:bool=False
    require_subscription:bool=False
    results_mode:str=Field(default='after_vote',pattern='^(after_vote|closed|hidden)$')
    @field_validator('title')
    @classmethod
    def title_clean(cls,value):
        value=value.strip()
        if not value:raise ValueError('Название не может быть пустым')
        return value
    @field_validator('starts_at','ends_at')
    @classmethod
    def utc(cls,value):
        if value.tzinfo is None:raise ValueError('Укажите часовой пояс даты')
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    @model_validator(mode='after')
    def rules(self):
        if self.ends_at<=self.starts_at or self.ends_at-self.starts_at>timedelta(days=366):raise ValueError('Неверный срок опроса')
        if self.reward_amount>0 and not self.require_verified_email:raise ValueError('Для награды требуется подтверждённый email')
        if self.reward_amount*self.max_responses>Decimal('1000000'):raise ValueError('Бюджет опроса превышает 1 000 000')
        return self

class AnswerIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    choices:list[int]=Field(default_factory=list,max_length=20)
    text:str=Field(default='',max_length=1000)
    @field_validator('choices',mode='before')
    @classmethod
    def choices_int(cls,value):
        if not isinstance(value,list) or any(type(x) is not int for x in value):raise ValueError('Некорректные варианты')
        return value
class SubmitIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    answers:list[AnswerIn]=Field(min_length=1,max_length=20)

def canonical(questions,answers):
    if len(questions)!=len(answers):raise HTTPException(400,'Ответьте на каждый вопрос')
    clean=[]
    for question,answer in zip(questions,answers):
        if question['kind']=='text':
            value=answer.text.strip()
            if not value or answer.choices:raise HTTPException(400,'Введите текст ответа')
            clean.append({'text':value,'choices':[]})
        else:
            choices=sorted(answer.choices)
            if answer.text or not choices or len(set(choices))!=len(choices) or any(x<0 or x>=len(question['options']) for x in choices):
                raise HTTPException(400,'Некорректные варианты ответа')
            if question['kind']=='single' and len(choices)!=1:raise HTTPException(400,'Выберите один вариант')
            clean.append({'text':'','choices':choices})
    digest=hashlib.sha256(json.dumps(clean,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return clean,digest

def phase(row,now=None):
    now=now or datetime.utcnow()
    if row.state!='published':return row.state
    if now>=row.ends_at or row.response_count>=row.max_responses:return 'closed'
    if now<row.starts_at:return 'scheduled'
    return 'open'

def public(row,own=None,admin=False):
    state=phase(row)
    visible=admin or row.results_mode=='after_vote' and own is not None or row.results_mode=='closed' and state=='closed'
    return {'id':row.id,'title':row.title,'description':row.description,'questions':row.questions,'state':row.state,'phase':state,
        'starts_at':row.starts_at.replace(tzinfo=timezone.utc),'ends_at':row.ends_at.replace(tzinfo=timezone.utc),'max_responses':row.max_responses,'response_count':row.response_count,
        'reward_amount':str(row.reward_amount),'currency':row.currency,'require_verified_email':row.require_verified_email,
        'require_subscription':row.require_subscription,'results_mode':row.results_mode,'statistics':row.statistics if visible else None,
        'submitted':own is not None,'my_answers':own.answers if own else None,'my_reward':str(own.reward_amount) if own else None,
        **({'budget_limit':str(row.reward_amount*row.max_responses),'budget_credited':str(row.reward_amount*row.response_count)} if admin else {})}

async def locked(db,survey_id):
    row=await db.scalar(select(Survey).where(Survey.id==survey_id).execution_options(populate_existing=True).with_for_update())
    if not row:raise HTTPException(404,'Опрос не найден')
    return row

@router.get('/api/admin/surveys')
async def admin_list(before:int=Query(default=0,ge=0),db:AsyncSession=Depends(get_db),admin=Depends(require_permission('marketing.read'))):
    return [public(row,admin=True) for row in (await db.scalars(select(Survey).where(Survey.id<before if before else Survey.id>0).order_by(Survey.id.desc()).limit(200))).all()]

@router.post('/api/admin/surveys')
async def create(payload:SurveyIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    data=payload.model_dump();data['questions']=[q.model_dump() for q in payload.questions]
    row=Survey(**data,currency=settings.default_currency);db.add(row);await db.flush()
    await audit(db,'survey.created',admin.email,str(row.id));await db.commit()
    return public(row,admin=True)

@router.put('/api/admin/surveys/{survey_id}')
async def edit(survey_id:int,payload:SurveyIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row=await locked(db,survey_id)
    if row.state!='draft' or row.response_count:raise HTTPException(409,'Опубликованные условия неизменяемы; создайте новый опрос')
    for key,value in payload.model_dump().items():setattr(row,key,value)
    row.updated_at=datetime.utcnow();await audit(db,'survey.edited',admin.email,str(row.id));await db.commit()
    return public(row,admin=True)

@router.post('/api/admin/surveys/{survey_id}/publish')
async def publish(survey_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row=await locked(db,survey_id)
    if row.state=='published':return public(row,admin=True)
    if row.state!='draft' or row.ends_at<=datetime.utcnow():raise HTTPException(409,'Этот опрос нельзя опубликовать')
    if row.currency!=settings.default_currency:raise HTTPException(409,'Валюта магазина изменилась; создайте новый опрос')
    row.state='published';row.updated_at=datetime.utcnow()
    await audit(db,'survey.published',admin.email,str(row.id),{'budget_limit':str(row.reward_amount*row.max_responses),'currency':row.currency})
    await db.commit();return public(row,admin=True)

@router.post('/api/admin/surveys/{survey_id}/close')
async def close(survey_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row=await locked(db,survey_id)
    if row.state!='closed':
        row.state='closed';row.updated_at=datetime.utcnow();await audit(db,'survey.closed',admin.email,str(row.id));await db.commit()
    return public(row,admin=True)

@router.delete('/api/admin/surveys/{survey_id}')
async def delete_draft(survey_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row=await locked(db,survey_id)
    if row.state!='draft' or row.response_count:raise HTTPException(409,'Удаляется только черновик без ответов')
    await db.delete(row);await audit(db,'survey.deleted',admin.email,str(survey_id));await db.commit();return {'ok':True}

@router.get('/api/admin/surveys/{survey_id}/responses')
async def responses(survey_id:int,after:int=Query(default=0,ge=0),db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    if not await db.get(Survey,survey_id):raise HTTPException(404,'Опрос не найден')
    rows=(await db.scalars(select(SurveyResponse).where(SurveyResponse.survey_id==survey_id,SurveyResponse.id>after)
        .order_by(SurveyResponse.id).limit(101))).all()
    return {'items':[{'id':r.id,'user_id':r.user_id,'answers':r.answers,'reward_amount':str(r.reward_amount),'currency':r.currency,'created_at':r.created_at} for r in rows[:100]],
        'next_after':rows[99].id if len(rows)>100 else None}

@router.get('/api/me/surveys')
async def customer_list(request:Request,response:Response,after:int=Query(default=0,ge=0),db:AsyncSession=Depends(get_db)):
    from .main import user_from_token
    user=await user_from_token(request,db);response.headers['Cache-Control']='private, no-store'
    rows=(await db.scalars(select(Survey).where(Survey.state!='draft',Survey.id>after).order_by(Survey.id).limit(51))).all()
    own=(await db.scalars(select(SurveyResponse).where(SurveyResponse.user_id==user.id,SurveyResponse.survey_id.in_([r.id for r in rows])))).all()
    by_id={r.survey_id:r for r in own}
    return {'items':[public(row,by_id.get(row.id)) for row in rows[:50]],'next_after':rows[49].id if len(rows)>50 else None}

@router.get('/api/me/surveys/{survey_id}')
async def customer_detail(survey_id:int,request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    from .main import user_from_token
    user=await user_from_token(request,db);row=await db.get(Survey,survey_id)
    if not row or row.state=='draft':raise HTTPException(404,'Опрос не найден')
    own=await db.scalar(select(SurveyResponse).where(SurveyResponse.survey_id==row.id,SurveyResponse.user_id==user.id))
    response.headers['Cache-Control']='private, no-store';return public(row,own)

@router.post('/api/me/surveys/{survey_id}/submit')
async def submit(survey_id:int,payload:SubmitIn,request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    from .main import user_from_token,audit,record_financial_event,enqueue_notification,maintenance_enabled
    from .platform_api import reject_restricted
    user=await user_from_token(request,db);reject_restricted(user)
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(401,'Аккаунт недоступен')
    reject_restricted(user)
    row=await locked(db,survey_id)
    if row.state=='draft':raise HTTPException(404,'Опрос не найден')
    answers,digest=canonical(row.questions,payload.answers)
    own=await db.scalar(select(SurveyResponse).where(SurveyResponse.survey_id==row.id,SurveyResponse.user_id==user.id))
    if own:
        if own.fingerprint!=digest:raise HTTPException(409,'Вы уже ответили на этот опрос')
        response.headers['Cache-Control']='private, no-store';return public(row,own)
    if await maintenance_enabled(db):raise HTTPException(503,'Магазин на обслуживании')
    if phase(row)!='open':raise HTTPException(409,'Опрос ещё не начался, завершён или достиг лимита')
    if row.require_verified_email and (not user.email or not user.email_verified_at):raise HTTPException(403,'Сначала подтвердите email')
    if row.require_subscription:
        active=await db.scalar(select(Subscription.id).where(Subscription.user_id==user.id,Subscription.lifecycle_status.in_(('active','cancel_scheduled')),
            Subscription.expires_at>datetime.utcnow()).limit(1))
        if not active:raise HTTPException(403,'Для участия нужна действующая подписка')
    if row.reward_amount>0 and row.currency!=settings.default_currency:raise HTTPException(409,'Валюта награды недоступна')
    if row.reward_amount>0 and await db.scalar(select(FinancialLedger.id).where(FinancialLedger.operation_key==f'survey:{row.id}:user:{user.id}:reward')):
        raise HTTPException(409,'Награда уже зафиксирована; требуется сверка истории')
    own=SurveyResponse(survey_id=row.id,user_id=user.id,answers=answers,fingerprint=digest,reward_amount=row.reward_amount,currency=row.currency)
    db.add(own);await db.flush()
    stats=dict(row.statistics or {})
    for i,answer in enumerate(answers):
        counts=dict(stats.get(str(i),{}))
        for choice in answer['choices']:counts[str(choice)]=int(counts.get(str(choice),0))+1
        counts['answered']=int(counts.get('answered',0))+1;stats[str(i)]=counts
    row.statistics=stats;row.response_count+=1;row.updated_at=datetime.utcnow()
    if row.reward_amount>0:
        user.wallet_balance=(Decimal(user.wallet_balance or 0)+row.reward_amount).quantize(Decimal('.01'))
        await record_financial_event(db,operation_key=f'survey:{row.id}:user:{user.id}:reward',user_id=user.id,payment_id=None,
            kind='survey_reward',direction='credit',amount=row.reward_amount,currency=row.currency,metadata={'survey_id':row.id,'response_id':own.id})
        await enqueue_notification(db,user_id=user.id,channel='in_app',kind='survey_reward',title='Награда за опрос',
            body=f'Начислено {row.reward_amount} {row.currency} на баланс магазина.',dedupe_key=f'survey:{row.id}:reward')
    await audit(db,'survey.submitted',f'user:{user.id}',str(row.id),{'response_id':own.id,'reward':str(row.reward_amount)})
    await db.commit();response.headers['Cache-Control']='private, no-store'
    return public(row,own)

async def anonymize(db,user_id):
    # Aggregate counters and financial evidence stay; private answers and identity do not.
    await db.execute(update(SurveyResponse).where(SurveyResponse.user_id==user_id).values(user_id=None,answers=[],fingerprint='ANONYMIZED'))
