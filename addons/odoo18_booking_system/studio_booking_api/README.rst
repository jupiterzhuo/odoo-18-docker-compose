Studio Booking API
====================

**Depends on:** ``studio_booking`` (core)

This addon registers HTTP/JSON controllers only. Business logic stays in
``studio_booking`` (models, ``services/booking_service.py``, ``utils/``).

Install order
-------------

**Studio Booking API** has ``auto_install`` on ``studio_booking``: it is installed
automatically when **Studio Booking** is installed. You can still install core only
by not having ``studio_booking_api`` on the addons path, or by uninstalling the API
addon from Apps.

Routes include ``/api/member/*``, ``/api/tenant``, ``/studio/api/v1/*``, etc.

Uninstalling this module removes API routes; data and core behaviour are unchanged.
