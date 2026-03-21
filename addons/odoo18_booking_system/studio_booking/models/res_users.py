# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    studio_tenant_ids = fields.Many2many(
        "studio.tenant",
        "studio_tenant_user_rel",
        "user_id",
        "tenant_id",
        string="Studio Tenants",
        help="Tenants this user can access (for tenant staff). Empty = no tenant access.",
    )

    def is_studio_manager(self):
        self.ensure_one()
        return (
            self.has_group("studio_booking.group_studio_booking_manager")
            or self.has_group("base.group_system")  # ✅ Treat Odoo Settings admin as manager
        )

    def ensure_studio_tenant_allowed(self, tenant):
        """Raise AccessError when non-manager user uses a tenant not assigned."""
        self.ensure_one()
        if self.id == self.env.ref("base.user_root").id:  # ✅ Superuser bypass
            return
        if self.is_studio_manager():
            return
        # Portal users (members) are validated via member.tenant_id in the API layer
        if self.has_group("base.group_portal") and not self.has_group(
            "studio_booking.group_studio_booking_user"
        ):
            return
        if not tenant or tenant.id in self.studio_tenant_ids.ids:
            return
        raise AccessError(
            _(
                "You can only manage data for assigned tenants. "
                "Please ask admin to assign this tenant to your user."
            )
        )

    @api.onchange("groups_id", "studio_tenant_ids")
    def _onchange_studio_tenant_ids_single_tenant(self):
        tenant_group = self.env.ref(
            "studio_booking.group_studio_booking_user",
            raise_if_not_found=False,
        )
        manager_group = self.env.ref(
            "studio_booking.group_studio_booking_manager",
            raise_if_not_found=False,
        )
        if not tenant_group:
            return
        for rec in self:
            is_admin_tenant = tenant_group in rec.groups_id
            is_admin_saas = manager_group in rec.groups_id if manager_group else False
            if is_admin_tenant and not is_admin_saas and len(rec.studio_tenant_ids) > 1:
                rec.studio_tenant_ids = rec.studio_tenant_ids[:1]
                return {
                    "warning": {
                        "title": _("Single Tenant Only"),
                        "message": _(
                            "Admin Tenant users can only be assigned to one Studio Tenant."
                        ),
                    }
                }

    @api.constrains("groups_id", "studio_tenant_ids")
    def _check_admin_tenant_single_tenant(self):
        tenant_group = self.env.ref(
            "studio_booking.group_studio_booking_user",
            raise_if_not_found=False,
        )
        manager_group = self.env.ref(
            "studio_booking.group_studio_booking_manager",
            raise_if_not_found=False,
        )
        if not tenant_group:
            return
        for rec in self:
            is_admin_tenant = tenant_group in rec.groups_id
            is_admin_saas = manager_group in rec.groups_id if manager_group else False
            if is_admin_tenant and not is_admin_saas and len(rec.studio_tenant_ids) != 1:
                raise ValidationError(
                    _("Admin Tenant users must be assigned to exactly one Studio Tenant.")
                )

    def _notify_security_setting_update(self, subject, content, mail_values=None, **kwargs):
        """Override to skip default Odoo security email when password/login change comes from studio_booking.

        When we set app_password via member API (forgot password, change password, welcome email),
        we send our own custom email. Skip the default "Your account login has been updated" email.
        """
        if self.env.context.get("studio_booking_skip_security_notification"):
            return
        return super()._notify_security_setting_update(
            subject, content, mail_values=mail_values, **kwargs
        )
