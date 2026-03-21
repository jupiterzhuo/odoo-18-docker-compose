# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

{
    "name": "Studio Booking",
    "version": "18.0.1.0.1",
    "category": "Services",
    "summary": "Yoga studio booking system with multi-tenant support (core)",
    "description": """
        Core booking system (models, security, UI, mail, cron, services):
        - Multi-tenant by studio.tenant (single Odoo company)
        - Branches, rooms, members, membership plans and subscriptions
        - Class sessions, bookings, waitlist (FIFO), check-in

        HTTP/JSON routes for the member app are in **Studio Booking API**
        (studio_booking_api), which auto-installs with this module when present on the addons path.
    """,
    "author": "Studio",
    "website": "",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "external_dependencies": {"python": ["jwt", "pytz", "pywebpush"]},
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/ir_cron.xml",
        "data/ir_cron_session_30min.xml",
        "data/fix_cancelled_waitlist_sequence.xml",
        "data/fix_session_names_gmt7.xml",
        "data/date_format.xml",
        "data/mail_template_member_welcome.xml",
        "data/mail_template_password_changed.xml",
        "data/mail_template_waitlist_promotion.xml",
        "views/tenant_views.xml",
        "views/branch_views.xml",
        "views/room_views.xml",
        "views/member_profile_views.xml",
        "views/membership_views.xml",
        "views/instructor_views.xml",
        "views/class_template_views.xml",
        "views/session_template_views.xml",  # ✅ Weekly recurring schedule UI
        "views/class_session_views.xml",
        "views/session_booking_detail_views.xml",
        "views/booking_views.xml",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "studio_booking/static/src/scss/branch_list.scss",
        ],
    },
    "installable": True,
    "application": True,
}
