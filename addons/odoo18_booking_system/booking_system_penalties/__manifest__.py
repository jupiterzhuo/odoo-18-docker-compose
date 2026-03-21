# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

{
    "name": "Booking System Penalties",
    "version": "18.0.1.0.0",
    "category": "Services",
    "summary": "Bootstrap addon for late-cancel / no-show penalties (extends Studio Booking)",
    "description": """
        Starter module for **booking penalties** (e.g. late cancellation fees, no-show strikes).

        - Depends on **Studio Booking** (`studio_booking`).
        - Provides model `studio.booking_penalty` and basic menus/security.
        - Extend with your business rules, API, and accounting integration.
    """,
    "author": "Studio",
    "website": "",
    "license": "LGPL-3",
    "depends": ["studio_booking"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/studio_booking_penalty_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
