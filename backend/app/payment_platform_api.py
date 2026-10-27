"""Corgi Payment Platform v20: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .models import Payment
from .models import User
from .security import require_permission
from decimal import Decimal
from fastapi import Depends
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ============================================================
# Corgi Payment Platform v20 — unified payment operations
# ============================================================

def _payment_platform_provider(name: str):
    return {"stripe": shop.StripePlatform(), "paypal": shop.PayPalPlatform(), "crypto": shop.CryptoGatewayPlatform()} .get(name)

async def _risk_score(db, user: User, amount: Decimal, request: Request|None=None):
    signals={}; score=0
    since=shop.datetime.utcnow()-shop.timedelta(hours=24)
    attempts=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.created_at>=since))).scalar() or 0)
    if attempts>=8: score+=35; signals["velocity_24h"]=attempts
    if amount>shop.Decimal("1000"): score+=20; signals["high_amount"]=str(amount)
    if user.deleted_at: score=100; signals["deleted_account"]=True
    if request:
        ip=shop._client_ip(request)
        prior=int((await db.execute(shop.select(shop.func.count()).select_from(shop.FraudSignal).where(shop.FraudSignal.ip==ip,shop.FraudSignal.created_at>=since))).scalar() or 0)
        if prior>=10: score+=40; signals["ip_velocity"]=prior
    decision="block" if score>=shop.settings.payment_risk_block_score else "review" if score>=shop.settings.payment_risk_review_score else "allow"
    return min(score,100),decision,signals

async def _record_provider_metric(db, provider, *, attempt=0, success=0, failed=0, refunded=0, gross=Decimal("0"), fee=Decimal("0")):
    day=shop.datetime.utcnow().date().isoformat()
    row=(await db.execute(shop.select(shop.PaymentProviderMetric).where(shop.PaymentProviderMetric.provider==provider,shop.PaymentProviderMetric.day==day).with_for_update())).scalar_one_or_none()
    if not row:
        row=shop.PaymentProviderMetric(provider=provider,day=day,attempts=0,succeeded=0,failed=0,refunded=0,gross_amount=shop.Decimal("0"),fees_amount=shop.Decimal("0"),net_amount=shop.Decimal("0")); db.add(row)
    row.attempts += attempt; row.succeeded += success; row.failed += failed; row.refunded += refunded; row.gross_amount += gross; row.fees_amount += fee; row.net_amount += gross-fee

async def _issue_invoice(db, payment: Payment):
    existing=(await db.execute(shop.select(shop.PaymentInvoice).where(shop.PaymentInvoice.payment_id==payment.id))).scalar_one_or_none()
    if existing: return existing
    profile=(await db.execute(shop.select(shop.PaymentTaxProfile).where(shop.PaymentTaxProfile.user_id==payment.user_id))).scalar_one_or_none()
    country=(profile.country if profile else "DE").upper()
    reverse=bool(profile and profile.reverse_charge)
    rate=shop.Decimal("0") if reverse or (profile and profile.tax_exempt) else shop.Decimal(str(shop.settings.default_tax_rate))
    total=shop.Decimal(str(payment.amount)).quantize(shop.Decimal("0.01"))
    subtotal=(total/(shop.Decimal("1")+rate/shop.Decimal("100"))).quantize(shop.Decimal("0.01")) if rate else total
    tax=(total-subtotal).quantize(shop.Decimal("0.01")) if rate else shop.Decimal("0")
    invoice=shop.PaymentInvoice(payment_id=payment.id,invoice_number=f"CGL-{shop.datetime.utcnow():%Y%m%d}-{payment.id:08d}",subtotal=subtotal,tax_amount=tax,total=total,tax_rate=rate,currency=payment.currency,country=country)
    db.add(invoice); await db.flush(); return invoice

@shop.app.get("/api/payments/providers")
async def payment_providers(db:AsyncSession=Depends(get_db)):
    enabled=await shop._payment_provider_order(db,None)
    return {"providers":[{"name":k,"enabled":k in enabled,"capabilities":shop.PROVIDER_CAPABILITIES.get(k,{})} for k in shop.PAYMENT_AGENTS]}

@shop.app.get("/api/admin/payments/platform/capabilities")
async def admin_payment_platform_capabilities(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    enabled=await shop._payment_provider_order(db,None)
    rows=(await db.execute(shop.select(shop.PaymentProviderHealth).order_by(shop.PaymentProviderHealth.priority))).scalars().all()
    return {"version":shop.APP_VERSION,"providers":[{"provider":x.provider,"enabled":x.enabled,"routable":x.provider in enabled,"priority":x.priority,"failures":x.failure_count,"successes":x.success_count,"circuit_open_until":x.circuit_open_until,"capabilities":shop.PROVIDER_CAPABILITIES.get(x.provider,{})} for x in rows if x.provider in shop.PAYMENT_AGENTS],"features":{"router":True,"failover":True,"auto_renew":True,"tax":True,"invoices":True,"risk":True,"chargebacks":True,"gift_cards":True,"corporate":True,"dynamic_pricing":True}}

class TaxProfileIn(BaseModel):
    country:str=Field(default="DE",min_length=2,max_length=2)
    vat_id:str|None=None
    business_name:str|None=None
    tax_exempt:bool=False
    reverse_charge:bool=False

@shop.app.put("/api/me/payment/tax-profile")
async def set_tax_profile(payload:TaxProfileIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db); row=(await db.execute(shop.select(shop.PaymentTaxProfile).where(shop.PaymentTaxProfile.user_id==user.id).with_for_update())).scalar_one_or_none()
    if not row: row=shop.PaymentTaxProfile(user_id=user.id); db.add(row)
    # A buyer cannot declare themselves tax exempt or reverse-charge. Those flags stay off.
    row.country=payload.country.upper(); row.vat_id=payload.vat_id; row.business_name=payload.business_name; row.tax_exempt=False; row.reverse_charge=False; row.updated_at=shop.datetime.utcnow(); await db.commit()
    return {"ok":True,"country":row.country,"vat_id":row.vat_id,"tax_exempt":row.tax_exempt,"reverse_charge":row.reverse_charge}

@shop.app.get("/api/me/payments/{payment_id}/invoice")
async def payment_invoice(payment_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db); payment=await db.get(shop.Payment,payment_id)
    if not payment or payment.user_id!=user.id: raise shop.HTTPException(404,"Payment not found")
    if payment.status not in {"paid","fulfilled","refunded"}: raise shop.HTTPException(409,"Invoice is available after payment confirmation")
    invoice=await shop._issue_invoice(db,payment); await db.commit()
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    buf=shop.BytesIO(); c=canvas.Canvas(buf,pagesize=A4); c.setTitle(invoice.invoice_number)
    c.drawString(50,800,"Corgi Lusi")
    c.drawString(50,780,f"Invoice: {invoice.invoice_number}")
    c.drawString(50,760,f"Payment: {payment.order_id}")
    c.drawString(50,740,f"Country: {invoice.country}")
    c.drawString(50,720,f"Subtotal: {invoice.subtotal} {invoice.currency}")
    c.drawString(50,700,f"VAT: {invoice.tax_amount} {invoice.currency} ({invoice.tax_rate}%)")
    c.drawString(50,680,f"Total: {invoice.total} {invoice.currency}")
    c.save(); buf.seek(0)
    return shop.Response(content=buf.getvalue(),media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{invoice.invoice_number}.pdf"'})

@shop.app.get("/api/admin/payments/analytics")
async def payment_analytics(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.PaymentProviderMetric).order_by(shop.PaymentProviderMetric.day.desc(),shop.PaymentProviderMetric.provider))).scalars().all()
    total=shop.Decimal("0"); succeeded=0; failed=0
    for r in rows: total+=r.gross_amount; succeeded+=r.succeeded; failed+=r.failed
    return {"total_gross":str(total),"succeeded":succeeded,"failed":failed,"conversion_rate":round(succeeded/max(1,succeeded+failed),4),"providers":[{"provider":r.provider,"day":r.day,"attempts":r.attempts,"succeeded":r.succeeded,"failed":r.failed,"refunded":r.refunded,"gross":str(r.gross_amount),"fees":str(r.fees_amount),"net":str(r.net_amount)} for r in rows]}

@shop.app.post("/api/admin/payments/{payment_id}/risk/recheck")
async def payment_risk_recheck(payment_id:int,request:Request,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.reconcile"))):
    payment=await db.get(shop.Payment,payment_id)
    if not payment: raise shop.HTTPException(404,"Payment not found")
    user=await db.get(shop.User,payment.user_id); score,decision,signals=await shop._risk_score(db,user,shop.Decimal(str(payment.amount)),request)
    row=(await db.execute(shop.select(shop.PaymentRiskAssessment).where(shop.PaymentRiskAssessment.payment_id==payment.id).with_for_update())).scalar_one_or_none()
    if not row: row=shop.PaymentRiskAssessment(payment_id=payment.id); db.add(row)
    row.score=score; row.decision=decision; row.signals=signals; await db.commit(); return {"score":score,"decision":decision,"signals":signals}

@shop.app.post("/api/webhooks/crypto")
async def crypto_webhook(request:Request,db:AsyncSession=Depends(get_db)):
    raw=await request.body()
    try:
        d=shop.CryptoGatewayPlatform().verify_webhook(raw,request.headers.get("X-Timestamp",""),request.headers.get("X-Signature",""))
    except Exception as exc:
        raise shop.HTTPException(403,"Invalid crypto webhook") from exc
    pid=str(d.get("id") or d.get("payment_id") or "")
    order_id=str(d.get("order_id") or "")
    event_id=str(d.get("event_id") or shop.hashlib.sha256(raw).hexdigest())
    if str(d.get("status") or "").lower() not in {"paid","succeeded","success","confirmed"} or not pid:
        return {"ok":True}
    p=await shop.payment_by_provider_or_order(db,"crypto",pid,order_id or None)
    if not p:
        return {"ok":True}
    if order_id and order_id != p.order_id:
        raise shop.HTTPException(403,"Order mismatch")
    if p.status in {"refunded","refunded_pending_revoke"}:
        return {"ok":True,"ignored":True,"reason":"payment_already_refunded"}
    if not await shop.CryptoGatewayPlatform().verify_succeeded(p.provider_payment_id or pid,shop.Decimal(str(p.amount)),p.currency,p.order_id):
        raise shop.HTTPException(503,"Payment verification unavailable")
    if not p.provider_payment_id:
        await shop.bind_provider_payment_id(db,p,pid)
    if not await shop.register_provider_event(db,"crypto",event_id,p.id):
        await db.rollback(); return {"ok":True,"duplicate":True}
    await db.commit()
    try:
        result=await shop._confirm_and_fulfill_payment(p.id,db)
        if result.get("ignored"):
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
                await shop.finish_provider_event(edb,"crypto",event_id,ok=True); await edb.commit()
            return {"ok":True,"ignored":True,"reason":"payment_already_refunded"}
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb,"crypto",event_id,ok=True); await edb.commit()
    except Exception as exc:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb,"crypto",event_id,ok=False,error=str(exc)); await edb.commit()
        raise
    return {"ok":True}

@shop.app.post("/api/payments/webhooks/stripe")
async def stripe_webhook(request:Request,db:AsyncSession=Depends(get_db)):
    body=await request.body()
    try: event=shop.StripePlatform().verify_webhook(body,request.headers.get("stripe-signature","") )
    except Exception as exc: raise shop.HTTPException(400,"Invalid Stripe webhook") from exc
    event_id = str(event.get("id") or "")
    if not event_id:
        raise shop.HTTPException(400, "Provider event ID is required")
    if not await shop.register_provider_event(db,"stripe",event_id,None):
        await db.rollback()
        return {"received":True,"duplicate":True}
    await db.commit()
    try:
        typ=event.get("type",""); obj=(event.get("data") or {}).get("object") or {}; order_id=(obj.get("metadata") or {}).get("order_id")
        if typ in {"checkout.session.completed","checkout.session.async_payment_succeeded","payment_intent.succeeded"} and order_id:
            confirmed=shop.StripePlatform().confirmed_amount(event)
            p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.order_id==order_id,shop.Payment.provider=="stripe"))).scalar_one_or_none()
            if p and confirmed:
                amount,currency=confirmed
                if currency==str(p.currency or "").upper() and amount==shop.Decimal(str(p.amount)).quantize(shop.Decimal("0.01")):
                    remote_id=p.provider_payment_id or str(obj.get("id") or "")
                    if not remote_id or not await shop.StripePlatform().verify_succeeded(remote_id,shop.Decimal(str(p.amount)),p.currency,p.order_id):
                        raise shop.HTTPException(503,"Payment status verification unavailable")
                    was_paid=p.status=="paid"
                    result=await shop._confirm_and_fulfill_payment(p.id,db)
                    if not result.get("ignored") and not was_paid:
                        p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True))).scalar_one()
                        if p.status=="paid":
                            await shop._record_provider_metric(db,"stripe",success=1,gross=shop.Decimal(str(p.amount)))
                            await shop._issue_invoice(db,p)
                            await db.commit()
        if typ in {"charge.dispute.created","charge.dispute.updated","charge.dispute.closed"}:
            did=obj.get("id") or event.get("id"); amount=shop.Decimal(str((obj.get("amount") or 0)))/100; currency=(obj.get("currency") or "usd").upper();
            p=None
            pi=obj.get("payment_intent")
            if pi: p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.provider_payment_id==pi))).scalar_one_or_none()
            if p and did:
                cb=(await db.execute(shop.select(shop.PaymentChargeback).where(shop.PaymentChargeback.external_id==did))).scalar_one_or_none()
                if not cb: db.add(shop.PaymentChargeback(payment_id=p.id,provider="stripe",external_id=did,amount=amount,currency=currency,status="open",reason=obj.get("reason"),evidence={"event_type":typ}))
                await db.commit()
        await shop.finish_provider_event(db,"stripe",event_id,ok=True)
        await db.commit()
    except Exception:
        await db.rollback()
        await shop.finish_provider_event(db,"stripe",event_id,ok=False,error="Webhook processing failed")
        await db.commit()
        raise
    return {"received":True}

@shop.app.post("/api/payments/webhooks/paypal")
async def paypal_webhook(request:Request,db:AsyncSession=Depends(get_db)):
    body=await request.body()
    try: event=await shop.PayPalPlatform().verify_webhook(dict(request.headers),body)
    except Exception as exc: raise shop.HTTPException(400,"Invalid PayPal webhook") from exc
    event_id = str(event.get("id") or "")
    if not event_id:
        raise shop.HTTPException(400, "Provider event ID is required")
    if not await shop.register_provider_event(db,"paypal",event_id,None):
        await db.rollback()
        return {"received":True,"duplicate":True}
    await db.commit()
    try:
        typ=event.get("event_type",""); resource=event.get("resource") or {}
        order_id=(resource.get("supplementary_data") or {}).get("related_ids",{}).get("order_id") or resource.get("custom_id")
        if typ=="CHECKOUT.ORDER.APPROVED" and resource.get("id"):
            # Capture only a locally created, still-pending order. PayPal can redeliver
            # this webhook after fulfillment or refund.
            pending=(await db.execute(shop.select(shop.Payment).where(shop.Payment.provider=="paypal",shop.Payment.provider_payment_id==str(resource["id"]),shop.Payment.status=="pending"))).scalar_one_or_none()
            if pending:
                await shop.PayPalPlatform().capture(resource["id"])
        if typ in {"PAYMENT.CAPTURE.COMPLETED","CHECKOUT.ORDER.COMPLETED"}:
            if not order_id:
                pu=(resource.get("purchase_units") or [{}])[0]; order_id=pu.get("reference_id")
            confirmed=shop.PayPalPlatform().captured_amount(event)
            p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.provider=="paypal",shop.or_(shop.Payment.order_id==order_id,shop.Payment.provider_payment_id==order_id)))).scalar_one_or_none() if order_id else None
            if p and confirmed:
                amount,currency=confirmed
                if currency==str(p.currency or "").upper() and amount==shop.Decimal(str(p.amount)).quantize(shop.Decimal("0.01")):
                    if not p.provider_payment_id or not await shop.PayPalPlatform().verify_succeeded(p.provider_payment_id,shop.Decimal(str(p.amount)),p.currency,p.order_id):
                        raise shop.HTTPException(503,"Payment status verification unavailable")
                    was_paid=p.status=="paid"
                    result=await shop._confirm_and_fulfill_payment(p.id,db)
                    if not result.get("ignored") and not was_paid:
                        p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True))).scalar_one()
                        if p.status=="paid":
                            await shop._record_provider_metric(db,"paypal",success=1,gross=shop.Decimal(str(p.amount)))
                            await shop._issue_invoice(db,p)
                            await db.commit()
        if typ in {"PAYMENT.CAPTURE.DENIED","CHECKOUT.PAYMENT-APPROVAL.REVERSED"} and order_id:
            p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.provider=="paypal",shop.or_(shop.Payment.order_id==order_id,shop.Payment.provider_payment_id==order_id)).with_for_update())).scalar_one_or_none()
            if p and p.status in {"creating","pending"}: p.status="failed"; await db.commit()
        await shop.finish_provider_event(db,"paypal",event_id,ok=True)
        await db.commit()
    except Exception:
        await db.rollback()
        await shop.finish_provider_event(db,"paypal",event_id,ok=False,error="Webhook processing failed")
        await db.commit()
        raise
    return {"received":True}

class MobilePurchaseIn(BaseModel):
    provider:str
    plan_id:int
    purchase_token:str|None=None
    signed_transaction:str|None=None
    product_id:str|None=None

@shop.app.post("/api/payments/mobile/verify")
async def verify_mobile_purchase(payload:MobilePurchaseIn,request:Request,db:AsyncSession=Depends(get_db)):
    raise shop.HTTPException(410,"Покупки через магазины приложений отключены. Используйте YooKassa, RollyPay или Platega в кабинете.")
    from .payment_platform import store_product_plan_id
    user=await shop.user_from_token(request,db); plan=await db.get(shop.Plan,payload.plan_id)
    if not plan or not plan.enabled: raise shop.HTTPException(404,"Plan not found")
    try:
        if payload.provider=="google_play":
            if not payload.purchase_token: raise shop.HTTPException(400,"purchase_token is required")
            data=await shop.GooglePlayPlatform().verify_subscription(payload.purchase_token)
            product_id=str(data.get("productId") or "")
            expiry=((data.get("lineItems") or [{}])[0]).get("expiryTime")
            external_id=str(payload.purchase_token)
        elif payload.provider=="apple_iap":
            if not payload.signed_transaction: raise shop.HTTPException(400,"signed_transaction is required")
            data=await shop.AppleStorePlatform().verify_transaction(payload.signed_transaction)
            product_id=str(data.get("productId") or "")
            expiry=data.get("expiresDate") or data.get("expiresDateMs")
            external_id=str(data.get("transactionId") or "")
            if not external_id: raise shop.HTTPException(402,"Apple transaction id is required")
        else: raise shop.HTTPException(400,"Unsupported mobile provider")
        mapped=store_product_plan_id(product_id)
    except shop.PlatformProviderError as exc:
        raise shop.HTTPException(402,str(exc)) from exc
    if mapped!=plan.id: raise shop.HTTPException(403,"Store product does not match the selected plan")
    # One external store transaction grants one shop payment. A missing id must not
    # mint a fresh paid order.
    existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.provider==payload.provider,shop.Payment.provider_payment_id==external_id))).scalar_one_or_none()
    if existing:
        if existing.user_id != user.id:
            raise shop.HTTPException(409,"Store transaction belongs to another account")
        return {"ok":True,"payment_id":existing.id,"status":existing.status,"expires_at":expiry}
    order=f"{payload.provider}-{external_id}"
    p=shop.Payment(user_id=user.id,plan_id=plan.id,provider=payload.provider,provider_payment_id=external_id,order_id=order,amount=plan.price,original_amount=plan.price,discount_amount=0,duration_days_snapshot=plan.duration_days,traffic_limit_gb_snapshot=plan.traffic_limit_gb,device_limit_snapshot=plan.device_limit,remnawave_profile_id_snapshot=plan.remnawave_profile_id,currency=shop.settings.default_currency,status="paid",fulfillment_status="pending",idempotency_key=shop.hashlib.sha256(order.encode()).hexdigest(),purpose="subscription")
    db.add(p); await db.flush(); await shop._issue_invoice(db,p); await db.commit(); await shop._confirm_and_fulfill_payment(p.id,db)
    return {"ok":True,"payment_id":p.id,"provider":payload.provider,"expires_at":expiry}

@shop.app.get("/api/admin/payments/chargebacks")
async def admin_chargebacks(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.PaymentChargeback).order_by(shop.PaymentChargeback.id.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"payment_id":x.payment_id,"provider":x.provider,"external_id":x.external_id,"amount":str(x.amount),"currency":x.currency,"status":x.status,"reason":x.reason,"created_at":x.created_at} for x in rows]

class ChargebackUpdateIn(BaseModel):
    status:str=Field(pattern="^(open|under_review|won|lost|closed)$")
    evidence:dict|None=None

@shop.app.patch("/api/admin/payments/chargebacks/{chargeback_id}")
async def update_chargeback(chargeback_id:int,payload:ChargebackUpdateIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.reconcile"))):
    row=await db.get(shop.PaymentChargeback,chargeback_id)
    if not row: raise shop.HTTPException(404,"Chargeback not found")
    row.status=payload.status; row.evidence=payload.evidence or row.evidence; row.updated_at=shop.datetime.utcnow(); await shop.audit(db,"payment.chargeback.updated",admin.email,str(row.id),{"status":row.status}); await db.commit(); return {"ok":True}

class GiftCardCreateIn(BaseModel):
    value:Decimal=Field(gt=0); currency:str="EUR"; expires_days:int|None=Field(default=365,ge=1,le=3650)

@shop.app.post("/api/admin/payment/gift-cards")
async def create_gift_card(payload:GiftCardCreateIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.reconcile"))):
    raw=shop.secrets.token_urlsafe(18).upper().replace("-","")[:24]; card=shop.GiftCard(code_hash=shop.hashlib.sha256(raw.encode()).hexdigest(),code_prefix=raw[:8],value=payload.value,balance=payload.value,currency=payload.currency.upper(),expires_at=shop.datetime.utcnow()+shop.timedelta(days=payload.expires_days) if payload.expires_days else None)
    db.add(card); await db.commit(); return {"code":raw,"value":str(card.value),"currency":card.currency,"expires_at":card.expires_at}

class GiftCardRedeemIn(BaseModel): code:str

@shop.app.post("/api/me/payment/gift-card/redeem")
async def redeem_gift_card(payload:GiftCardRedeemIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db); raw=payload.code.strip().upper()
    user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).with_for_update())).scalar_one()
    card=(await db.execute(shop.select(shop.GiftCard).where(shop.GiftCard.code_hash==shop.hashlib.sha256(raw.encode()).hexdigest()).with_for_update())).scalar_one_or_none()
    if not card or not card.enabled or (card.expires_at and card.expires_at<=shop.datetime.utcnow()) or card.balance<=0: raise shop.HTTPException(400,"Invalid or expired gift card")
    if str(card.currency or "").upper()!=str(shop.settings.default_currency or "").upper(): raise shop.HTTPException(400,"Gift card currency does not match the shop currency")
    user.wallet_balance += card.balance; credited=card.balance; card.balance=shop.Decimal("0"); card.enabled=False
    await shop.record_financial_event(db,operation_key=f"gift-card:{card.id}",user_id=user.id,payment_id=None,kind="gift_card",direction="credit",amount=credited,currency=card.currency,metadata={"code_prefix":card.code_prefix}); await db.commit()
    return {"ok":True,"credited":str(credited),"currency":card.currency,"wallet_balance":str(user.wallet_balance)}

@shop.app.get("/api/admin/payments/gift-cards")
async def list_gift_cards(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.GiftCard).order_by(shop.GiftCard.id.desc()).limit(200))).scalars().all(); return [{"id":x.id,"prefix":x.code_prefix,"value":str(x.value),"balance":str(x.balance),"currency":x.currency,"enabled":x.enabled,"expires_at":x.expires_at} for x in rows]

class CorporateIn(BaseModel):
    name:str=Field(min_length=2,max_length=255); country:str="DE"; vat_id:str|None=None; payment_terms_days:int=14; credit_limit:Decimal=Decimal("0")

@shop.app.post("/api/admin/corporate-accounts")
async def create_corporate(payload:CorporateIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.reconcile"))):
    row=shop.CorporateAccount(owner_user_id=admin.id,name=payload.name,country=payload.country.upper(),vat_id=payload.vat_id,payment_terms_days=payload.payment_terms_days,credit_limit=payload.credit_limit); db.add(row); await db.commit(); await db.refresh(row); return {"id":row.id,"name":row.name,"vat_id":row.vat_id}

@shop.app.get("/api/admin/corporate-accounts")
async def list_corporate(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.CorporateAccount).order_by(shop.CorporateAccount.id.desc()))).scalars().all(); return [{"id":x.id,"owner_user_id":x.owner_user_id,"name":x.name,"country":x.country,"vat_id":x.vat_id,"terms_days":x.payment_terms_days,"credit_limit":str(x.credit_limit),"enabled":x.enabled} for x in rows]

class PriceExperimentIn(BaseModel):
    key:str=Field(min_length=2,max_length=64); rules:dict; enabled:bool=False

@shop.app.put("/api/admin/payments/pricing/experiments/{key}")
async def upsert_price_experiment(key:str,payload:PriceExperimentIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.reconcile"))):
    row=(await db.execute(shop.select(shop.PaymentPriceExperiment).where(shop.PaymentPriceExperiment.key==key).with_for_update())).scalar_one_or_none()
    if not row: row=shop.PaymentPriceExperiment(key=key); db.add(row)
    row.rules=payload.rules; row.enabled=payload.enabled; await db.commit(); return {"ok":True,"key":key,"enabled":row.enabled}

@shop.app.get("/api/admin/payments/pricing/experiments")
async def list_price_experiments(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.PaymentPriceExperiment).order_by(shop.PaymentPriceExperiment.id))).scalars().all(); return [{"key":x.key,"rules":x.rules,"enabled":x.enabled} for x in rows]


__all__ = ['ChargebackUpdateIn', 'CorporateIn', 'GiftCardCreateIn', 'GiftCardRedeemIn', 'MobilePurchaseIn', 'PriceExperimentIn', 'TaxProfileIn', '_issue_invoice', '_payment_platform_provider', '_record_provider_metric', '_risk_score', 'admin_chargebacks', 'admin_payment_platform_capabilities', 'create_corporate', 'create_gift_card', 'crypto_webhook', 'list_corporate', 'list_gift_cards', 'list_price_experiments', 'payment_analytics', 'payment_invoice', 'payment_providers', 'payment_risk_recheck', 'paypal_webhook', 'redeem_gift_card', 'set_tax_profile', 'stripe_webhook', 'update_chargeback', 'upsert_price_experiment', 'verify_mobile_purchase']
# Imported before main finished (``from app import payment_platform_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
