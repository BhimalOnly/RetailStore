"""Customer messages (WhatsApp / SMS): order confirmation and order ready.

    events.py     doc_events: a storefront order / its delivery -> engine.queue()
    engine.py     rules, consent, the Retail Message Log outbox, background send, retry
    providers.py  Dry run (default), Meta WhatsApp Cloud API, generic HTTP SMS gateway
    consent.py    per-customer, per-channel opt-in (stamped), storefront checkout box
    phone.py      numbers -> +E.164

Credentials live in Retail Store Settings > Messages (Password fields, System Manager / Store Owner only).
Nothing here ever raises into a sale: a failed message is a log row, never a failed order.
See the README, section "Customer messages".
"""
