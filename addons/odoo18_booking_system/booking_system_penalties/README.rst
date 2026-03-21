Booking System Penalties (bootstrap)
====================================

**Technical name:** ``booking_system_penalties``

**Depends on:** ``studio_booking``

Starter Odoo 18 addon for **booking penalties** (late cancel, no-show, etc.).

Model
-----

* ``studio.booking_penalty`` — links to ``studio.tenant`` and optionally ``studio.booking``.

Next steps
----------

* Add automation from ``studio.booking`` state changes (late cancel / no-show).
* Expose JSON API in ``studio_booking_api`` if needed.
* Integrate invoicing or membership credits.

Install **Apps** → search *Booking System Penalties* → Install (after Studio Booking).
