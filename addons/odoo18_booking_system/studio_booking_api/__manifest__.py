# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

{
    "name": "Studio Booking API",
    "version": "18.0.1.0.1",
    "category": "Services",
    "summary": "REST/JSON HTTP API for the member app (depends on Studio Booking core)",
    "description": """
        HTTP layer for Studio Booking:
        - Member auth (login, JWT, profile, sessions, bookings, push subscribe)
        - Public tenant lookup
        - Class booking/cancel JSON endpoints

        Install **Studio Booking** first; this module adds routes only (no business logic change).
    """,
    "author": "Studio",
    "website": "",
    "license": "LGPL-3",
    "depends": ["studio_booking"],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": ["studio_booking"],
}
