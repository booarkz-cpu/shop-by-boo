#!/usr/bin/env python3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
checks={
'payment_platform_adapter':root/'backend/app/payment_platform.py',
'payment_models':root/'backend/app/models.py',
'payment_migration':root/'backend/alembic/versions/0040_v20_payment_platform.py',
'payment_env':root/'.env.example',
'payment_release_notes':root/'docs/archive/root/V20_PAYMENT_PLATFORM_RU.md',
}
required={
'payment_platform_adapter':['class StripePlatform','class PayPalPlatform','class AppleStorePlatform','class GooglePlayPlatform','class CryptoGatewayPlatform','PROVIDER_CAPABILITIES'],
'payment_models':['class PaymentTaxProfile','class PaymentInvoice','class PaymentChargeback','class PaymentRiskAssessment','class PaymentProviderMetric','class GiftCard','class CorporateAccount','class PaymentPriceExperiment'],
'payment_migration':['revision="0040_v20_payment_platform"'],
'payment_env':['STRIPE_SECRET_KEY=','PAYPAL_CLIENT_ID=','APPLE_BUNDLE_ID=','GOOGLE_PLAY_PACKAGE=','CRYPTO_GATEWAY_URL=','DEFAULT_TAX_RATE='],
'payment_release_notes':['Stripe','PayPal','Apple StoreKit 2','Google Play','Chargeback','Gift cards','Corporate accounts','Pricing experiments'],
}
failed=[]
for key,path in checks.items():
    text=path.read_text(errors='ignore') if path.exists() else ''
    for token in required[key]:
        if token not in text: failed.append(f'{key}: missing {token}')
if failed:
    print('\n'.join('FAIL: '+x for x in failed)); raise SystemExit(1)
print('v20 payment platform gate: 8/8')
