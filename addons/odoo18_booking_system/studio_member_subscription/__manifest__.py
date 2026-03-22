# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

{
    "name": "Studio Member Subscription",
    "version": "18.0.2.0.0",
    "category": "Services",
    "summary": "Extended membership: time-based & session-based plans with credit system",
    "description": """
        Extends Studio Booking membership with:
        - Plan types: time-based (unlimited) and session-based (credit quota)
        - Session credit tracking (available, used, pending)
        - Single drop-in pass support
        - Pricing and validity configuration
        - Class categories for templates (penalty rules foundation)
    """,
    "author": "Studio",
    "website": "",
    "license": "LGPL-3",
    "depends": ["studio_booking"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/membership_plan_views.xml",
        "views/membership_subscription_views.xml",
        "views/class_category_views.xml",
        "views/class_template_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
