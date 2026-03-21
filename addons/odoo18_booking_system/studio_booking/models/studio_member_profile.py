# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
import secrets
import string

from odoo import _, api, fields, models

from ..utils import timezone as tz_utils
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StudioMemberProfile(models.Model):
    _name = "studio.member_profile"
    _description = "Studio Member Profile (one per tenant per email)"
    _order = "tenant_id, last_name, first_name"

    @api.model
    def _default_tenant_id(self):
        user = self.env.user
        if user.studio_tenant_ids:
            return user.studio_tenant_ids[:1].id
        return False

    tenant_id = fields.Many2one(
        "studio.tenant",
        required=True,
        ondelete="restrict",
        index=True,
        default=_default_tenant_id,
    )
    first_name = fields.Char()
    last_name = fields.Char()
    name = fields.Char(
        compute="_compute_name",
        store=True,
        index=True,
    )
    email = fields.Char(required=True, index=True)
    phone = fields.Char()
    partner_id = fields.Many2one(
        "res.partner",
        ondelete="set null",
        index=True,
        string="Related Contact",
        help="Auto-created/linked contact for interoperability with standard Odoo apps.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="App User",
        ondelete="set null",
        readonly=True,
        copy=False,
    )
    app_password = fields.Char(
        string="Set App Password",
        copy=False,
        help="Set or update the member app password.",
    )
    temporary_password = fields.Char(
        string="Temporary Password",
        related="app_password",
        readonly=True,
    )
    password_generated = fields.Boolean(
        string="Password Generated",
        default=False,
        copy=False,
    )
    welcome_email_sent = fields.Boolean(
        string="Welcome Email Sent",
        default=False,
        copy=False,
    )
    last_password_generated_at = fields.Datetime(
        string="Last Password Generated At",
        copy=False,
    )
    last_welcome_email_sent_at = fields.Datetime(
        string="Last Welcome Email Sent At",
        copy=False,
    )
    subscription_ids = fields.One2many(
        "studio.membership_subscription",
        "member_profile_id",
        string="Membership Subscriptions",
        copy=False,
    )
    active_subscription_id = fields.Many2one(
        "studio.membership_subscription",
        compute="_compute_active_subscription",
        store=True,
        string="Active Subscription",
    )
    active_subscription_plan_id = fields.Many2one(
        "studio.membership_plan",
        related="active_subscription_id.plan_id",
        store=True,
        string="Active Subscription Plan",
    )

    @api.depends(
        "subscription_ids.state",
        "subscription_ids.date_start",
        "subscription_ids.date_end",
    )
    def _compute_active_subscription(self):
        today = tz_utils.studio_today()
        for rec in self:
            active = rec.subscription_ids.filtered(
                lambda s: s.state == "active"
                and s.date_start <= today
                and (not s.date_end or s.date_end >= today)
            ).sorted("date_start", reverse=True)
            rec.active_subscription_id = active[:1]

    @api.depends("first_name", "last_name")
    def _compute_name(self):
        for rec in self:
            rec.name = " ".join(
                [x for x in [rec.first_name, rec.last_name] if x]
            ).strip()

    @api.model
    def _prepare_partner_vals(self, vals):
        return {
            "name": " ".join(
                [x for x in [vals.get("first_name"), vals.get("last_name")] if x]
            ).strip(),
            "email": vals.get("email"),
            "phone": vals.get("phone"),
            "type": "contact",
            "is_company": False,
        }

    @staticmethod
    def _normalize_email(email):
        return (email or "").strip().lower()

    def _build_member_login(self, email, tenant_id):
        del tenant_id
        return self._normalize_email(email)

    def _get_internal_member_login(self):
        """Return the tenant-scoped Odoo login for this member."""
        self.ensure_one()
        return self._build_member_login(self.email, self.tenant_id.id)

    @api.model
    def _get_member_by_tenant_and_email(self, tenant, email):
        """Find active-by-subscription member profile for tenant + email pair."""
        email = self._normalize_email(email)
        if not tenant or not email:
            return self.browse()
        return self.search(
            [
                ("tenant_id", "=", tenant.id),
                ("email", "=ilike", email),
                ("active_subscription_id", "!=", False),
            ],
            limit=1,
        )

    def _serialize_for_api(self):
        """Return a dict safe for external API responses."""
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "tenant_id": self.tenant_id.id,
            "tenant_name": self.tenant_id.name,
        }

    def _get_eligible_branches(self):
        """
        Return branches the member is eligible to attend based on active subscription
        and membership plan. Prerequisite: member must have an active subscription
        and the plan must be active.

        - If plan.branch_ids is empty → all tenant branches are allowed.
        - If plan.branch_ids has values → only those branches are allowed.
        """
        self.ensure_one()
        sub = self.active_subscription_id
        if not sub or sub.state != "active":
            return self.env["studio.branch"]
        plan = sub.plan_id
        if not plan or not plan.active:
            return self.env["studio.branch"]
        today = tz_utils.studio_today()
        if sub.date_start and sub.date_start > today:
            return self.env["studio.branch"]
        if sub.date_end and sub.date_end < today:
            return self.env["studio.branch"]
        Branch = self.env["studio.branch"]
        domain = [("tenant_id", "=", self.tenant_id.id), ("active", "=", True)]
        if not plan.branch_ids:
            return Branch.search(domain)
        return plan.branch_ids.filtered(lambda b: b.active and b.tenant_id == self.tenant_id)

    def _serialize_profile_for_api(self):
        """Return full profile dict for member app profile view (after login)."""
        self.ensure_one()
        data = {
            "id": self.id,
            "first_name": self.first_name or "",
            "last_name": self.last_name or "",
            "name": self.name or "",
            "email": self.email or "",
            "phone": self.phone or "",
            "tenant": {
                "id": self.tenant_id.id,
                "name": self.tenant_id.name,
                "website_url": self.tenant_id.website_url or "",
                "login_url": self.tenant_id.login_url or "",
            },
            "active_subscription": None,
        }
        if self.active_subscription_id:
            sub = self.active_subscription_id
            data["active_subscription"] = {
                "id": sub.id,
                "plan_id": sub.plan_id.id,
                "plan_name": sub.plan_id.name,
                "date_start": str(sub.date_start) if sub.date_start else None,
                "date_end": str(sub.date_end) if sub.date_end else None,
                "state": sub.state,
            }
        return data

    def _create_or_update_app_user(self, password=None):
        portal_group = self.env.ref("base.group_portal")
        member_group = self.env.ref("studio_booking.group_studio_booking_member")
        user_model = self.env["res.users"].sudo()
        for rec in self:
            if not rec.email:
                continue
            login = rec._build_member_login(rec.email, rec.tenant_id.id)
            user = rec.user_id.sudo() if rec.user_id else user_model.browse()
            existing_user = user_model.search([("login", "=", login)], limit=1)

            if not user:
                if existing_user:
                    user = existing_user
                else:
                    user_vals = {
                        "name": rec.name,
                        "login": login,
                        "partner_id": rec.partner_id.id if rec.partner_id else False,
                        "groups_id": [(6, 0, [portal_group.id, member_group.id])],
                        "studio_tenant_ids": [(6, 0, [rec.tenant_id.id])],
                    }
                    user = user_model.create(user_vals)
                rec.user_id = user
            else:
                # If another user already owns this login, relink to keep login unique.
                if existing_user and existing_user != user:
                    user = existing_user
                    rec.user_id = user
                group_ids = set(user.groups_id.ids) | {portal_group.id, member_group.id}
                tenant_ids = set(user.studio_tenant_ids.ids) | {rec.tenant_id.id}
                user_vals = {
                    "name": rec.name,
                    "login": login,
                    "groups_id": [(6, 0, list(group_ids))],
                    "studio_tenant_ids": [(6, 0, list(tenant_ids))],
                }
                # Keep partner in sync when available.
                if rec.partner_id:
                    user_vals["partner_id"] = rec.partner_id.id
                user.with_context(
                    studio_booking_skip_security_notification=True
                ).write(user_vals)
            if password:
                rec.user_id.sudo().with_context(
                    studio_booking_skip_security_notification=True
                ).write({"password": password})

    # Password rules: min 8 chars, at least one uppercase, at least one number.
    PASSWORD_MIN_LENGTH = 8

    @staticmethod
    def _validate_password_rules(password):
        """
        Validate password against rules: min 8 chars, uppercase, number.
        Returns (True, None) if valid, else (False, error_message).
        """
        if not password or not isinstance(password, str):
            return False, _("Password is required.")
        pwd = password.strip()
        if len(pwd) < StudioMemberProfile.PASSWORD_MIN_LENGTH:
            return False, _("Password must be at least %(n)s characters.") % {
                "n": StudioMemberProfile.PASSWORD_MIN_LENGTH,
            }
        if not any(c.isupper() for c in pwd):
            return False, _("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in pwd):
            return False, _("Password must contain at least one number.")
        return True, None

    @staticmethod
    def _generate_temporary_password(length=14):
        alphabet = string.ascii_letters + string.digits
        while True:
            pwd = "".join(secrets.choice(alphabet) for _ in range(length))
            if (
                any(c.islower() for c in pwd)
                and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)
            ):
                return pwd

    def action_generate_password(self):
        self.ensure_one()
        self.write({
            "app_password": self._generate_temporary_password(),
            "password_generated": True,
            "last_password_generated_at": fields.Datetime.now(),
            # Keep email sending as a separate user action (resend / send button).
            "welcome_email_sent": False,
            "last_welcome_email_sent_at": False,
        })

    def _get_email_from_for_notification(self):
        """
        Return email_from for member notification emails.
        Never use OdooBot or admin - only tenant or company email.
        """
        self.ensure_one()
        return (
            self.tenant_id.email
            or (self.env.company.email if self.env.company else None)
            or False
        )

    def action_reset_password_email(self):
        """
        Forgot password flow: generate temporary password and send welcome email.
        Used by the forgot-password API.
        """
        self.ensure_one()
        if not self.email:
            raise ValidationError(_("Member email is missing."))
        if not self.user_id:
            raise ValidationError(_("Member has no app user. Please contact support."))
        new_password = self._generate_temporary_password()
        self.write({
            "app_password": new_password,
            "password_generated": True,
            "last_password_generated_at": fields.Datetime.now(),
            "welcome_email_sent": False,
            "last_welcome_email_sent_at": False,
        })
        template = self.env.ref(
            "studio_booking.mail_template_member_welcome_temporary_password",
            raise_if_not_found=False,
        )
        if not template:
            raise ValidationError(_("Welcome email template is not configured."))
        mail_id = template.sudo().send_mail(
            self.id,
            force_send=False,
            raise_exception=False,
            email_values={
                "email_to": self.email,
                "email_from": self._get_email_from_for_notification(),
            },
        )
        if mail_id:
            mail = self.env["mail.mail"].sudo().browse(mail_id)
            if mail.exists():
                plain_text = self._get_welcome_email_plain_text()
                if "body_plaintext" in mail._fields:
                    mail.write({"body_plaintext": plain_text})
                elif "body_alternative" in mail._fields:
                    mail.write({"body_alternative": plain_text})
                mail.send(raise_exception=False)

    def action_send_password_changed_email(self):
        """Send notification email after password was changed successfully."""
        self.ensure_one()
        if not self.email:
            raise ValidationError(_("Member email is missing."))
        template = self.env.ref(
            "studio_booking.mail_template_member_password_changed",
            raise_if_not_found=False,
        )
        if not template:
            raise ValidationError(_("Password changed email template is not configured."))
        mail_id = template.sudo().send_mail(
            self.id,
            force_send=False,
            raise_exception=False,
            email_values={
                "email_to": self.email,
                "email_from": self._get_email_from_for_notification(),
            },
        )
        if mail_id:
            mail = self.env["mail.mail"].sudo().browse(mail_id)
            if mail.exists():
                mail.send(raise_exception=False)

    def action_send_welcome_email(self):
        """Send the member app onboarding email with the generated password."""
        self.ensure_one()

        if not self.password_generated or not self.app_password:
            raise ValidationError(_("Generate password first before sending welcome email."))
        if not self.email:
            raise ValidationError(_("Member email is missing."))
        template = self.env.ref(
            "studio_booking.mail_template_member_welcome_temporary_password",
            raise_if_not_found=False,
        )
        if not template:
            raise ValidationError(_("Welcome email template is not configured."))

        mail_id = template.sudo().send_mail(
            self.id,
            force_send=False,
            raise_exception=False,
            email_values={
                "email_to": self.email,
                "email_from": self._get_email_from_for_notification(),
            },
        )
        mail = self.env["mail.mail"].sudo().browse(mail_id) if mail_id else self.env["mail.mail"]
        if mail and mail.exists():
            # Keep a plain-text alternative when the field exists in current Odoo build.
            plain_text = self._get_welcome_email_plain_text()
            if "body_plaintext" in mail._fields:
                mail.write({"body_plaintext": plain_text})
            elif "body_alternative" in mail._fields:
                mail.write({"body_alternative": plain_text})
            mail.send(raise_exception=False)

        mail_state = mail.state if mail and mail.exists() else False
        welcome_sent = bool(mail) and mail_state not in ("exception", "cancelled")
        self.sudo().write({
            "welcome_email_sent": welcome_sent,
            "last_welcome_email_sent_at": fields.Datetime.now() if mail else False,
        })

    def action_send_welcome_email_multi(self):
        """Send welcome email to multiple selected members. Skips those without generated password."""
        if not self:
            raise ValidationError(_("Please select at least one member."))
        eligible = self.filtered(
            lambda m: m.password_generated and m.app_password and m.email
        )
        skipped = len(self) - len(eligible)
        sent = 0
        failed = 0
        for rec in eligible:
            try:
                rec.action_send_welcome_email()
                if rec.welcome_email_sent:
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                _logger.warning(
                    "Send welcome email failed for member %s (%s): %s",
                    rec.id,
                    rec.email,
                    e,
                )
                failed += 1
        msg_parts = []
        if sent:
            msg_parts.append(_("%(n)s email(s) sent.") % {"n": sent})
        if failed:
            msg_parts.append(_("%(n)s failed.") % {"n": failed})
        if skipped:
            msg_parts.append(
                _("%(n)s skipped (generate password first).") % {"n": skipped}
            )
        if not msg_parts:
            msg_parts.append(_("No emails sent."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Send Welcome Email"),
                "message": " ".join(msg_parts),
                "type": "success" if sent else "warning",
                "sticky": False,
            },
        }

    def _get_welcome_email_plain_text(self):
        """Return concise plaintext fallback for welcome onboarding email."""
        self.ensure_one()
        tenant = self.tenant_id
        tenant_name = tenant.name or "our studio"
        tenant_code = tenant.code or "-"
        login_url = tenant.login_url or tenant.website_url or "-"
        support_email = tenant.email or "-"
        support_phone = tenant.phone or "-"
        member_name = self.name or self.email or "Member"
        temporary_password = self.temporary_password or self.app_password or "-"
        website = tenant.website_url or "-"

        return _(
            "Hi %(member_name)s,\n\n"
            "Welcome to %(tenant_name)s.\n\n"
            "Your login details:\n"
            "- Email: %(email)s\n"
            "- Tenant Code: %(tenant_code)s\n"
            "- Temporary Password: %(temporary_password)s\n"
            "- Login URL: %(login_url)s\n\n"
            "Please log in and change your password immediately.\n\n"
            "Support contact:\n"
            "- Email: %(support_email)s\n"
            "- Phone: %(support_phone)s\n"
            "- Website: %(website)s\n"
        ) % {
            "member_name": member_name,
            "tenant_name": tenant_name,
            "email": self.email or "-",
            "tenant_code": tenant_code,
            "temporary_password": temporary_password,
            "login_url": login_url,
            "support_email": support_email,
            "support_phone": support_phone,
            "website": website,
        }

    @api.model_create_multi
    def create(self, vals_list):
        Tenant = self.env["studio.tenant"]
        for vals in vals_list:
            tenant = Tenant.browse(vals.get("tenant_id"))
            self.env.user.ensure_studio_tenant_allowed(tenant)
        # Keep app_password in vals_list so it is persisted on the member profile,
        # while also syncing it to the linked app user account.
        passwords = [vals.get("app_password", False) for vals in vals_list]
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if not rec.partner_id:
                rec.partner_id = self.env["res.partner"].create(
                    rec._prepare_partner_vals(vals)
                )
            rec._create_or_update_app_user(password=passwords.pop(0))
        return records

    def write(self, vals):
        Tenant = self.env["studio.tenant"]
        user = self.env.user
        if user and vals.get("tenant_id"):
            tenant = Tenant.browse(vals.get("tenant_id"))
            user.ensure_studio_tenant_allowed(tenant)
        if user:
            for rec in self:
                user.ensure_studio_tenant_allowed(rec.tenant_id)
        # Preserve app_password on the profile; only mirror it to res.users password.
        password = vals.get("app_password", False) if "app_password" in vals else False
        res = super().write(vals)
        for rec in self:
            if rec.partner_id and any(
                k in vals for k in ["first_name", "last_name", "email", "phone"]
            ):
                rec.partner_id.write(
                    {
                        "name": rec.name,
                        "email": rec.email,
                        "phone": rec.phone,
                    }
                )
            elif not rec.partner_id and any(
                k in vals for k in ["first_name", "last_name", "email", "phone"]
            ):
                rec.partner_id = self.env["res.partner"].create(
                    {
                        "name": rec.name,
                        "email": rec.email,
                        "phone": rec.phone,
                        "type": "contact",
                        "is_company": False,
                    }
                )
            if any(k in vals for k in ["first_name", "last_name", "email", "partner_id"]):
                rec._create_or_update_app_user(password=password)
            elif password:
                rec._create_or_update_app_user(password=password)
        return res

    @api.constrains("app_password")
    def _check_app_password_rules(self):
        """Enforce password rules when app_password is set."""
        for rec in self:
            if not rec.app_password:
                continue
            valid, error = self._validate_password_rules(rec.app_password)
            if not valid:
                raise ValidationError(error)

    @api.constrains("tenant_id", "email")
    def _check_one_per_tenant_email(self):
        for rec in self:
            if not rec.email:
                continue
            other = self.search(
                [
                    ("id", "!=", rec.id),
                    ("tenant_id", "=", rec.tenant_id.id),
                    ("email", "=", rec.email),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    _("Only one member profile is allowed per tenant per email.")
                )
