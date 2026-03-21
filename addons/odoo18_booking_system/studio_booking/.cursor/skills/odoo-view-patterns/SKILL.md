---
name: odoo-view-patterns
description: Premium Odoo backend view patterns for studio_booking. Use when building or modifying form, list, search, calendar views, session/booking UI, or SCSS.
---

# Studio Booking: Odoo View Patterns

## 1. Premium Backend UX Principles

- **Clarity:** Group related fields; clear section titles
- **Efficiency:** Operators complete tasks quickly; minimal clicks
- **Consistency:** Same patterns across session, booking, template views
- **Restraint:** No clutter; hide irrelevant fields by state/role

---

## 2. List + Form + Search Structure

**Master data (tenant, branch, room, instructor, class_template):**
- List: key columns, decoration for inactive
- Form: grouped sections
- Search: filters by tenant, active, name

**Session template:**
- List: template_id, branch, room, instructor, day_of_week, start_time, is_recurring, active
- Form: General | Assignment | Schedule | Recurring groups; notebook for Generated Sessions

**Class session:**
- List + Calendar (session_start, session_end)
- Form: header with Detail + Cancel Session; statusbar; notebook for Bookings

**Booking:**
- List: session_id, member_profile_id, booking_status, attendance_status, waitlist_sequence, audit fields
- Form: booking_status readonly; Cancel button when cancellable

---

## 3. When to Use What

| Element | Use When |
|---------|----------|
| **Notebook** | Related operational details (Bookings, Generated Sessions) |
| **Header buttons** | Important state transitions (Cancel Session, Detail) |
| **Smart buttons** | Quick navigation to related count (e.g. booking count) |
| **Statusbar** | Lifecycle models (scheduled → cancelled | completed) |
| **Decorations** | Muted for inactive; avoid excessive badges |

---

## 4. Session Operations UI

**Class session form:**
```xml
<form>
  <header>
    <button name="action_booking_detail" string="Detail" type="object" class="btn-secondary"/>
    <button name="action_cancel_session" string="Cancel Session" type="object" class="btn-danger"
            invisible="state == 'cancelled'"/>
    <field name="state" widget="statusbar" statusbar_visible="scheduled,cancelled,completed"/>
  </header>
  <sheet>
    <group>
      <group>
        <field name="branch_id"/>
        <field name="room_id"/>
        <field name="instructor_id"/>
        <field name="session_start"/>
        <field name="session_end"/>
      </group>
      <group>
        <field name="capacity"/>
        <field name="booked_count"/>
        <field name="waitlist_count"/>
      </group>
    </group>
    <notebook>
      <page string="Bookings" name="bookings">
        <field name="booking_ids" nolabel="1">
          <list default_group_by="booking_status">
            <field name="member_profile_id"/>
            <field name="booking_status"/>
            <field name="attendance_status"/>
            <field name="waitlist_sequence"/>
          </list>
        </field>
      </page>
    </notebook>
  </sheet>
</form>
```

---

## 5. Booking / Waitlist Management UI

**Booking form:**
- `booking_status` readonly (model resolves it)
- `member_profile_id` domain: `[('active_subscription_id','!=',False), ('tenant_id','=',tenant_id), ('id','not in',existing_booking_member_ids)]`
- Cancel button: `invisible="not id or booking_status in ('cancelled','late_cancel','completed')"`

**Session booking detail (pop-up):**
- Transient `studio.session_booking_detail` with booked_ids, waitlist_ids
- Opened via `action_booking_detail` from session form

---

## 6. Role-Aware Visibility

```xml
<!-- Tenant visible only to manager -->
<field name="tenant_id" groups="studio_booking.group_studio_booking_manager"/>

<!-- Tenant hidden but used in domain for tenant user -->
<field name="tenant_id" invisible="1" groups="studio_booking.group_studio_booking_user"/>

<!-- Recurring fields only when is_recurring -->
<field name="day_of_week" invisible="not is_recurring or recurring_range != 'week'"
       required="is_recurring and recurring_range == 'week'"/>
```

---

## 7. Search / Filter / Group-By

- Filters: By state, tenant (manager), branch, date range
- Group-by: booking_status, attendance_status, tenant_id (manager)

---

## 8. SCSS Usage

**Pattern:** Target specific list/form with module class; avoid global overrides.

```scss
/* branch_list.scss: column widths for branch list */
.o_list_view.o_studio_branch_list .o_list_table th[data-name="name"],
.o_studio_branch_list .o_list_table th[data-name="name"] {
  width: 64% !important;
}
```

- Add class via `list` element: `class="o_studio_branch_list"`
- Keep changes minimal; only when default Odoo layout is insufficient

---

## 9. Good vs Bad View Structure

**Bad:**
```xml
<!-- All fields in one flat group; no sections -->
<group>
  <field name="tenant_id"/>
  <field name="branch_id"/>
  <field name="room_id"/>
  <field name="instructor_id"/>
  <field name="capacity"/>
  <field name="day_of_week"/>
  ...
</group>
```

**Good:**
```xml
<group string="General">
  <group>
    <field name="tenant_id" groups="..."/>
    <field name="template_id" domain="[('tenant_id','=',tenant_id)]"/>
    <field name="active"/>
  </group>
</group>
<group string="Assignment">
  <group>
    <field name="branch_id" domain="[('tenant_id','=',tenant_id)]"/>
    <field name="instructor_id" domain="[('tenant_id','=',tenant_id)]"/>
    <field name="room_id" domain="[('branch_id','=',branch_id)]"/>
  </group>
</group>
```
