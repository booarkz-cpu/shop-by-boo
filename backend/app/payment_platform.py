from __future__ import annotations
import base64, hashlib, hmac, json, time, uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import httpx, jwt
from cryptography.hazmat.primitives import serialization
from app.config import settings

class PlatformProviderError(Exception):
    """A platform payment provider returned an invalid or failed response."""

def _client():
    from .main import _pinned_public_http_client
    return _pinned_public_http_client(20)

def _money(v): return f"{Decimal(str(v)).quantize(Decimal('0.01')):.2f}"

class StripePlatform:
    name='stripe'
    async def create(self, amount, currency, description, metadata):
        if not settings.stripe_secret_key: raise PlatformProviderError('Stripe is not configured')
        async with _client() as c:
            data={'mode':'payment','success_url':metadata.get('return_url',settings.public_base_url),'cancel_url':metadata.get('cancel_url',settings.public_base_url),'line_items[0][price_data][currency]':currency.lower(),'line_items[0][price_data][product_data][name]':description,'line_items[0][price_data][unit_amount]':int(Decimal(str(amount))*100),'line_items[0][quantity]':1,'metadata[order_id]':metadata.get('order_id',''),'metadata[user_id]':str(metadata.get('user_id','')),'payment_intent_data[metadata][order_id]':metadata.get('order_id','')}
            r=await c.post(f'{settings.stripe_api_url}/v1/checkout/sessions',data=data,headers={'Authorization':f'Bearer {settings.stripe_secret_key}'})
            r.raise_for_status(); x=r.json()
            return {'id':x['id'],'url':x.get('url'),'status':x.get('status')}
    async def create_recurring(self, amount, order_id, description, token):
        raise PlatformProviderError('Stripe recurring token requires a Stripe PaymentMethod/customer mapping; use SetupIntent/Customer flow')
    async def status(self,payment_id):
        async with _client() as c:
            r=await c.get(f'{settings.stripe_api_url}/v1/payment_intents/{payment_id}',headers={'Authorization':f'Bearer {settings.stripe_secret_key}'})
            r.raise_for_status(); return r.json()
    async def refund(self,payment_id,amount,currency,order_id=None):
        if not settings.stripe_secret_key: raise PlatformProviderError('Stripe is not configured')
        async with _client() as c:
            intent=payment_id
            if str(payment_id).startswith('cs_'):
                session=await c.get(f'{settings.stripe_api_url}/v1/checkout/sessions/{payment_id}',headers={'Authorization':f'Bearer {settings.stripe_secret_key}'})
                session.raise_for_status()
                details=session.json()
                if details.get('payment_status')!='paid': raise PlatformProviderError('Stripe checkout is not paid')
                intent=details.get('payment_intent')
            if not isinstance(intent,str) or not intent.startswith('pi_'):
                raise PlatformProviderError('Stripe payment intent is not available for refund')
            data={'payment_intent':intent,'amount':int(Decimal(str(amount)).quantize(Decimal('0.01'))*100)}
            refund_key='refund-'+hashlib.sha256(f'{payment_id}:{_money(amount)}:{currency}'.encode()).hexdigest()
            r=await c.post(f'{settings.stripe_api_url}/v1/refunds',data=data,headers={'Authorization':f'Bearer {settings.stripe_secret_key}','Idempotency-Key':refund_key})
            r.raise_for_status(); return r.json()
    async def get_refund_status(self,refund_id):
        async with _client() as c:
            r=await c.get(f'{settings.stripe_api_url}/v1/refunds/{refund_id}',headers={'Authorization':f'Bearer {settings.stripe_secret_key}'})
            r.raise_for_status(); return str(r.json().get('status') or '').lower()
    def verify_webhook(self, body:bytes, signature:str):
        if not settings.stripe_webhook_secret: raise PlatformProviderError('Stripe webhook secret is not configured')
        parts=dict(x.split('=',1) for x in signature.split(',') if '=' in x); ts=parts.get('t'); sig=parts.get('v1')
        if not ts or not sig or abs(time.time()-int(ts))>300: raise PlatformProviderError('Invalid Stripe webhook timestamp')
        expected=hmac.new(settings.stripe_webhook_secret.encode(),ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,sig): raise PlatformProviderError('Invalid Stripe webhook signature')
        return json.loads(body)
    def confirmed_amount(self, event: dict):
        """Money Stripe has actually collected. Unpaid checkout sessions are not paid."""
        typ=str(event.get('type') or '')
        obj=(event.get('data') or {}).get('object') or {}
        if typ in {'checkout.session.completed','checkout.session.async_payment_succeeded'}:
            if obj.get('payment_status')!='paid': return None
            raw=obj.get('amount_total'); currency=str(obj.get('currency') or '').upper()
        elif typ=='payment_intent.succeeded':
            raw=obj.get('amount_received')
            if raw is None: raw=obj.get('amount')
            currency=str(obj.get('currency') or '').upper()
        else:
            return None
        if raw is None or not currency: return None
        return (Decimal(str(raw))/Decimal('100')).quantize(Decimal('0.01')), currency
    async def verify_succeeded(self, payment_id, expected_amount, currency, expected_order_id=None) -> bool:
        """Stripe has collected this checkout only when the API shows the same money."""
        if not payment_id or not settings.stripe_secret_key: return False
        pid=str(payment_id)
        path='payment_intents' if pid.startswith('pi_') else 'checkout/sessions'
        try:
            async with _client() as c:
                r=await c.get(f'{settings.stripe_api_url}/v1/{path}/{pid}',headers={'Authorization':f'Bearer {settings.stripe_secret_key}'})
            if r.status_code>=400: return False
            data=r.json()
        except Exception:
            return False
        if pid.startswith('pi_'):
            if data.get('status')!='succeeded': return False
            raw=data.get('amount_received')
            if raw is None: raw=data.get('amount')
        else:
            if data.get('payment_status')!='paid': return False
            raw=data.get('amount_total')
        if raw is None: return False
        got=((Decimal(str(raw))/Decimal('100')).quantize(Decimal('0.01')), str(data.get('currency') or '').upper())
        order=str((data.get('metadata') or {}).get('order_id') or '')
        if expected_order_id and order!=str(expected_order_id): return False
        return got==(Decimal(str(expected_amount)).quantize(Decimal('0.01')), str(currency or '').upper())

class PayPalPlatform:
    name='paypal'
    async def _token(self):
        if not settings.paypal_client_id or not settings.paypal_client_secret: raise PlatformProviderError('PayPal is not configured')
        async with _client() as c:
            r=await c.post(f'{settings.paypal_api_url}/v1/oauth2/token',data={'grant_type':'client_credentials'},auth=(settings.paypal_client_id,settings.paypal_client_secret),headers={'Accept':'application/json'})
            r.raise_for_status(); return r.json()['access_token']
    async def create(self,amount,currency,description,metadata):
        token=await self._token()
        async with _client() as c:
            payload={'intent':'CAPTURE','purchase_units':[{'reference_id':metadata.get('order_id'),'description':description,'amount':{'currency_code':currency,'value':_money(amount)}}],'application_context':{'return_url':metadata.get('return_url',settings.public_base_url),'cancel_url':metadata.get('cancel_url',settings.public_base_url)}}
            r=await c.post(f'{settings.paypal_api_url}/v2/checkout/orders',json=payload,headers={'Authorization':f'Bearer {token}','Content-Type':'application/json','PayPal-Request-Id':metadata.get('order_id',str(uuid.uuid4()))}); r.raise_for_status(); x=r.json()
            url=next((l['href'] for l in x.get('links',[]) if l.get('rel')=='approve'),None)
            return {'id':x['id'],'url':url,'status':x.get('status')}
    async def capture(self,order_id):
        token=await self._token()
        async with _client() as c:
            request_id='capture-'+hashlib.sha256(str(order_id).encode()).hexdigest()
            r=await c.post(f'{settings.paypal_api_url}/v2/checkout/orders/{order_id}/capture',headers={'Authorization':f'Bearer {token}','Content-Type':'application/json','PayPal-Request-Id':request_id}); r.raise_for_status(); return r.json()
    async def refund(self,order_id,amount,currency,order_ref=None):
        token=await self._token()
        async with _client() as c:
            r=await c.get(f'{settings.paypal_api_url}/v2/checkout/orders/{order_id}',headers={'Authorization':f'Bearer {token}'})
            r.raise_for_status(); order=r.json()
            capture=((order.get('purchase_units') or [{}])[0].get('payments') or {}).get('captures') or []
            if not capture: raise PlatformProviderError('PayPal capture is not available for refund')
            capture_id=capture[0].get('id')
            request_id='refund-'+hashlib.sha256(f'{capture_id}:{_money(amount)}:{currency}'.encode()).hexdigest()
            r=await c.post(f'{settings.paypal_api_url}/v2/payments/captures/{capture_id}/refund',json={'amount':{'value':_money(amount),'currency_code':currency}},headers={'Authorization':f'Bearer {token}','PayPal-Request-Id':request_id})
            r.raise_for_status(); return r.json()
    async def get_refund_status(self,refund_id):
        token=await self._token()
        async with _client() as c:
            r=await c.get(f'{settings.paypal_api_url}/v2/payments/refunds/{refund_id}',headers={'Authorization':f'Bearer {token}'})
            r.raise_for_status(); return str(r.json().get('status') or '').lower()
    async def verify_webhook(self,headers,body):
        # PayPal's verification endpoint is used rather than trusting a header locally.
        token=await self._token()
        async with _client() as c:
            payload={'auth_algo':headers.get('paypal-auth-algo'),'cert_url':headers.get('paypal-cert-url'),'transmission_id':headers.get('paypal-transmission-id'),'transmission_sig':headers.get('paypal-transmission-sig'),'transmission_time':headers.get('paypal-transmission-time'),'webhook_id':settings.paypal_webhook_id,'webhook_event':json.loads(body)}
            r=await c.post(f'{settings.paypal_api_url}/v1/notifications/verify-webhook-signature',json=payload,headers={'Authorization':f'Bearer {token}'})
            r.raise_for_status(); x=r.json()
            if x.get('verification_status')!='SUCCESS': raise PlatformProviderError('Invalid PayPal webhook signature')
            return payload['webhook_event']
    def captured_amount(self, event: dict):
        """Amount on a verified PayPal capture or completed order. Missing money is not paid."""
        resource=event.get('resource') or {}
        amount=resource.get('amount') if isinstance(resource.get('amount'), dict) else None
        if not amount:
            units=resource.get('purchase_units') or []
            amount=(units[0].get('amount') if units and isinstance(units[0], dict) else None)
        if not isinstance(amount, dict) or amount.get('value') in (None,''): return None
        currency=str(amount.get('currency_code') or amount.get('currency') or '').upper()
        if not currency: return None
        return Decimal(str(amount['value'])).quantize(Decimal('0.01')), currency
    async def verify_succeeded(self, payment_id, expected_amount, currency, expected_order_id=None) -> bool:
        """PayPal order is paid only when the capture is completed and the money matches."""
        if not payment_id: return False
        try:
            token=await self._token()
            async with _client() as c:
                r=await c.get(f'{settings.paypal_api_url}/v2/checkout/orders/{payment_id}',headers={'Authorization':f'Bearer {token}'})
            if r.status_code>=400: return False
            order=r.json()
        except Exception:
            return False
        if str(order.get('status') or '').upper()!='COMPLETED': return False
        units=order.get('purchase_units') or []
        unit=units[0] if units and isinstance(units[0], dict) else {}
        amount=unit.get('amount') if isinstance(unit.get('amount'), dict) else {}
        if amount.get('value') in (None,''): return False
        got=(Decimal(str(amount.get('value'))).quantize(Decimal('0.01')), str(amount.get('currency_code') or '').upper())
        captures=((unit.get('payments') or {}).get('captures') or [])
        captured=any(str(item.get('status') or '').upper()=='COMPLETED' for item in captures if isinstance(item, dict))
        if not captured: return False
        ref=str(unit.get('reference_id') or '')
        if expected_order_id and ref!=str(expected_order_id): return False
        return got==(Decimal(str(expected_amount)).quantize(Decimal('0.01')), str(currency or '').upper())

class CryptoGatewayPlatform:
    name='crypto'
    async def create(self,amount,currency,description,metadata):
        if not settings.crypto_gateway_url or not settings.crypto_gateway_key: raise PlatformProviderError('Crypto gateway is not configured')
        async with _client() as c:
            r=await c.post(settings.crypto_gateway_url.rstrip('/')+'/payments',json={'amount':_money(amount),'currency':currency,'description':description,'order_id':metadata.get('order_id'),'return_url':metadata.get('return_url')},headers={'Authorization':f'Bearer {settings.crypto_gateway_key}'})
            r.raise_for_status(); return r.json()
    async def verify_succeeded(self, payment_id, expected_amount, currency, expected_order_id=None) -> bool:
        """The gateway ledger, not the webhook body, decides that crypto was paid."""
        if not payment_id or not settings.crypto_gateway_url or not settings.crypto_gateway_key: return False
        try:
            async with _client() as c:
                r=await c.get(settings.crypto_gateway_url.rstrip('/')+f'/payments/{payment_id}',headers={'Authorization':f'Bearer {settings.crypto_gateway_key}'})
            if r.status_code>=400: return False
            data=r.json()
        except Exception:
            return False
        if str(data.get('status') or '').lower() not in {'paid','succeeded','success','confirmed'}: return False
        if data.get('amount') in (None,''): return False
        got=(Decimal(str(data.get('amount'))).quantize(Decimal('0.01')), str(data.get('currency') or '').upper())
        order=str(data.get('order_id') or '')
        if expected_order_id and order!=str(expected_order_id): return False
        return got==(Decimal(str(expected_amount)).quantize(Decimal('0.01')), str(currency or '').upper())
    def verify_webhook(self, body: bytes, timestamp: str, signature: str) -> dict:
        if not settings.crypto_gateway_key or not timestamp or not signature:
            raise PlatformProviderError('Crypto webhook is not configured')
        try:
            ts=int(timestamp)
        except (TypeError, ValueError):
            raise PlatformProviderError('Invalid crypto webhook timestamp')
        if abs(time.time()-ts)>300: raise PlatformProviderError('Invalid crypto webhook timestamp')
        expected=hmac.new(settings.crypto_gateway_key.encode(), timestamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature): raise PlatformProviderError('Invalid crypto webhook signature')
        return json.loads(body)

class AppleStorePlatform:
    name='apple_iap'
    async def verify_transaction(self,signed_transaction:str):
        if not settings.apple_bundle_id: raise PlatformProviderError('Apple bundle id is not configured')
        if not (settings.apple_issuer_id and settings.apple_key_id and settings.apple_private_key):
            raise PlatformProviderError('Apple App Store Server API credentials are not configured')
        # The client JWS is only a hint for the transaction id. Entitlement comes
        # from the signed payload returned by the App Store Server API.
        try:
            hinted=jwt.decode(signed_transaction,options={'verify_signature':False,'verify_exp':False},algorithms=['ES256','RS256'])
        except Exception as e: raise PlatformProviderError(f'Invalid Apple transaction JWS: {e}')
        transaction_id=str(hinted.get('transactionId') or '')
        if not transaction_id: raise PlatformProviderError('Apple transaction id is required')
        data=await self.get_transaction(transaction_id)
        signed=None
        if isinstance(data, dict):
            signed=data.get('signedTransactionInfo') or ((data.get('signedTransactions') or [None])[0])
        if not signed: raise PlatformProviderError('Apple App Store Server API did not return a signed transaction')
        verified_payload=jwt.decode(signed,options={'verify_signature':False,'verify_exp':False},algorithms=['ES256','RS256'])
        if verified_payload.get('bundleId') != settings.apple_bundle_id: raise PlatformProviderError('Apple bundle id mismatch')
        if str(verified_payload.get('transactionId') or '') != transaction_id: raise PlatformProviderError('Apple transaction id mismatch')
        if verified_payload.get('revocationDate'): raise PlatformProviderError('Apple transaction is revoked')
        expiry=verified_payload.get('expiresDate')
        try:
            # App Store signed transaction dates are Unix milliseconds.
            if expiry is None or int(expiry) <= int(time.time() * 1000):
                raise PlatformProviderError('Apple subscription is expired or has no expiry')
        except (TypeError, ValueError) as exc:
            raise PlatformProviderError('Invalid Apple subscription expiry') from exc
        return verified_payload
    async def get_transaction(self,transaction_id):
        # Signed API token is generated only when App Store API credentials exist.
        if not (settings.apple_issuer_id and settings.apple_key_id and settings.apple_private_key): raise PlatformProviderError('Apple App Store Server API credentials are not configured')
        now=int(time.time()); key=settings.apple_private_key.replace('\\n','\n')
        token=jwt.encode({'iss':settings.apple_issuer_id,'iat':now,'exp':now+300,'aud':'appstoreconnect-v1'},key,algorithm='ES256',headers={'kid':settings.apple_key_id})
        async with _client() as c:
            r=await c.get(f'{settings.apple_appstore_api_url}/inApps/v1/transactions/{transaction_id}',headers={'Authorization':f'Bearer {token}'})
            r.raise_for_status(); return r.json()

class GooglePlayPlatform:
    name='google_play'
    async def _access_token(self):
        if not settings.google_service_account_json: raise PlatformProviderError('Google service account is not configured')
        info=json.loads(settings.google_service_account_json); now=int(time.time())
        key=info['private_key'].replace('\\n','\n'); assertion=jwt.encode({'iss':info['client_email'],'scope':'https://www.googleapis.com/auth/androidpublisher','aud':'https://oauth2.googleapis.com/token','iat':now,'exp':now+3600},key,algorithm='RS256')
        async with _client() as c:
            r=await c.post('https://oauth2.googleapis.com/token',data={'grant_type':'urn:ietf:params:oauth:grant-type:jwt-bearer','assertion':assertion}); r.raise_for_status(); return r.json()['access_token']
    async def verify_subscription(self,purchase_token):
        token=await self._access_token()
        async with _client() as c:
            r=await c.get(f'{settings.google_play_api_url}/androidpublisher/v3/applications/{settings.google_play_package}/purchases/subscriptionsv2/tokens/{purchase_token}',headers={'Authorization':f'Bearer {token}'}); r.raise_for_status(); data=r.json()
        if data.get('subscriptionState')!='SUBSCRIPTION_STATE_ACTIVE': raise PlatformProviderError('Google Play purchase is not active')
        items=data.get('lineItems') or []
        product=str((items[0] or {}).get('productId') or '') if items else ''
        if not product: raise PlatformProviderError('Google Play product id is missing')
        try:
            expiry=datetime.fromisoformat(str(items[0]['expiryTime']).replace('Z', '+00:00'))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise PlatformProviderError('Google Play subscription is expired')
        except (KeyError, TypeError, ValueError) as exc:
            raise PlatformProviderError('Invalid Google Play subscription expiry') from exc
        data['productId']=product
        return data

def store_product_plan_id(product_id: str) -> int:
    """Map a store product id to a shop plan. An empty map refuses the purchase."""
    raw=(settings.mobile_store_products or '').strip()
    if not raw: raise PlatformProviderError('Mobile store products are not configured')
    try:
        mapping=json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlatformProviderError('MOBILE_STORE_PRODUCTS is not valid JSON') from exc
    if not isinstance(mapping, dict) or not product_id or product_id not in mapping:
        raise PlatformProviderError('Store product is not mapped to a plan')
    try:
        return int(mapping[product_id])
    except (TypeError, ValueError) as exc:
        raise PlatformProviderError('Store product is not mapped to a plan') from exc

# Compatibility import for older modules. The canonical catalog is payment_policy.
from .payment_policy import PROVIDER_CAPABILITIES
