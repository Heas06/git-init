import logging
import uuid
from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.intervals import Intervals

_logger = logging.getLogger(__name__)

LIVE_STATES = ("draft", "confirmed", "done")
DEAD_STATES = ("cancelled", "no_show")


class SalonAppointment(models.Model):
    """A single booking: one customer, one service, one staff member, one slot.

    This model owns the scheduling state machine and the double-booking guards.
    In later phases it also owns a ``calendar.event`` (Phase 3) and links to a
    ``sale.order`` / ``crm.lead`` (Phase 4).
    """

    _name = "salon.appointment"
    _description = "Salon Appointment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env._("New"),
    )
    active = fields.Boolean(default=True)

    partner_id = fields.Many2one(
        "res.partner", string="Customer", required=True, index=True, tracking=True
    )
    partner_phone = fields.Char(related="partner_id.phone", string="Phone", readonly=False)
    partner_email = fields.Char(related="partner_id.email", string="Email", readonly=False)

    appointment_type_id = fields.Many2one(
        "salon.appointment.type", string="Booking Page", ondelete="restrict"
    )
    service_id = fields.Many2one(
        "product.template",
        string="Service",
        required=True,
        domain=[("salon_service", "=", True)],
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Staff",
        required=True,
        domain=[("is_salon_staff", "=", True)],
        index=True,
        tracking=True,
    )

    start = fields.Datetime(string="Start", required=True, index=True, tracking=True)
    duration = fields.Float(
        string="Duration (hours)",
        compute="_compute_schedule_inputs",
        store=True,
        readonly=False,
    )
    buffer = fields.Float(
        string="Buffer (hours)",
        compute="_compute_schedule_inputs",
        store=True,
        readonly=False,
    )
    stop = fields.Datetime(
        string="End", compute="_compute_stop", store=True, index=True
    )
    stop_with_buffer = fields.Datetime(
        string="End (incl. buffer)", compute="_compute_stop", store=True
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
            ("no_show", "No Show"),
        ],
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )

    price = fields.Monetary(
        string="Price", compute="_compute_price", store=True, readonly=False
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    company_id = fields.Many2one(
        "res.company", required=True, index=True, default=lambda self: self.env.company
    )

    note = fields.Text(string="Internal Notes")

    start_display = fields.Char(
        string="When", compute="_compute_start_display",
        help="Start time formatted in the booking page's timezone, for emails and the public status page.",
    )

    # --- public booking funnel ---------------------------------------------------
    access_token = fields.Char(
        string="Access Token",
        copy=False,
        required=True,
        readonly=True,
        index=True,
        default=lambda self: str(uuid.uuid4()),
        help="Lets a customer view this appointment's public status page without logging in.",
    )
    source_ip = fields.Char(
        string="Source IP", copy=False, readonly=True,
        help="IP address that submitted this booking through the public page, if any.",
    )

    # --- wired up in later phases -------------------------------------------------
    calendar_event_id = fields.Many2one("calendar.event", copy=False, readonly=True)
    sale_order_id = fields.Many2one("sale.order", copy=False, readonly=True)
    lead_id = fields.Many2one("crm.lead", copy=False, readonly=True)

    # --- database-level guarantees ---------------------------------------------
    _duration_positive = models.Constraint(
        "CHECK(duration > 0)",
        "The appointment duration must be strictly positive.",
    )
    # Concurrency-safe double-booking guard: PostgreSQL refuses two live
    # appointments for the same employee whose [start, stop+buffer) ranges
    # overlap. Requires the btree_gist extension (see `init`).
    _no_overlap = models.Constraint(
        """
        EXCLUDE USING gist (
            employee_id WITH =,
            tsrange(start, COALESCE(stop_with_buffer, stop), '[)') WITH &&
        )
        WHERE (
            active
            AND state NOT IN ('cancelled', 'no_show')
            AND start IS NOT NULL
            AND stop IS NOT NULL
        )
        """,
        "This staff member is already booked for an overlapping time slot.",
    )

    def init(self):
        """Ensure the `btree_gist` extension exists for the `_no_overlap` constraint.

        A fresh install also gets it from the module's ``pre_init_hook`` (which
        runs *before* constraints are applied); doing it here as well covers
        module upgrades, where ``pre_init_hook`` does not run. If the database
        user lacks the privilege (some managed Postgres), we log a warning and
        fall back to the Python-level check in ``_check_no_overlap``.
        """
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Could not create the `btree_gist` PostgreSQL extension. The "
                "database-level double-booking guard will be inactive; the "
                "Python check still applies. Run `CREATE EXTENSION btree_gist;` "
                "as a superuser to enable it."
            )

    # --- computes ------------------------------------------------------------------
    @api.depends("service_id")
    def _compute_schedule_inputs(self):
        for appt in self:
            appt.duration = appt.service_id.salon_duration or appt.duration or 1.0
            appt.buffer = (
                appt.service_id.salon_buffer
                if appt.service_id
                else (appt.buffer or 0.0)
            )

    @api.depends("start", "duration", "buffer")
    def _compute_stop(self):
        for appt in self:
            if appt.start and appt.duration:
                appt.stop = appt.start + timedelta(hours=appt.duration)
                appt.stop_with_buffer = appt.stop + timedelta(hours=appt.buffer or 0.0)
            else:
                appt.stop = appt.stop_with_buffer = False

    @api.depends("service_id")
    def _compute_price(self):
        for appt in self:
            appt.price = appt.service_id.list_price if appt.service_id else 0.0

    @api.depends("start", "appointment_type_id.tz")
    def _compute_start_display(self):
        for appt in self:
            if not appt.start:
                appt.start_display = ""
                continue
            tz = pytz.timezone(
                appt.appointment_type_id.tz or self.env.user.tz or "UTC"
            )
            local = pytz.utc.localize(appt.start).astimezone(tz)
            appt.start_display = local.strftime("%A, %B %d at %I:%M %p (%Z)")

    # --- public booking funnel ----------------------------------------------------
    @api.model
    def _find_or_create_partner(self, name, email, phone):
        """Match an existing customer by email then phone, else create one."""
        Partner = self.env["res.partner"]
        partner = Partner.browse()
        if email:
            partner = Partner.search([("email", "=ilike", email)], limit=1)
        if not partner and phone:
            partner = Partner.search([("phone", "=", phone)], limit=1)
        if not partner:
            return Partner.create(
                {"name": name, "email": email or False, "phone": phone or False}
            )
        updates = {}
        if name and not partner.name:
            updates["name"] = name
        if email and not partner.email:
            updates["email"] = email
        if phone and not partner.phone:
            updates["phone"] = phone
        if updates:
            partner.write(updates)
        return partner

    @api.model
    def _public_book(self, appointment_type, service, employee, start, partner, source_ip=None):
        """Create a confirmed appointment from the public booking funnel.

        The caller (the website controller) is responsible for re-validating
        that ``start`` is still a genuinely free slot for ``employee`` right
        before calling this - this method itself relies on the model's usual
        guards (`_check_no_overlap` + the `_no_overlap` DB constraint) as the
        last line of defense against a race with another visitor.
        """
        return self.create(
            {
                "partner_id": partner.id,
                "appointment_type_id": appointment_type.id,
                "service_id": service.id,
                "employee_id": employee.id,
                "start": start,
                "state": "confirmed",
                "company_id": appointment_type.company_id.id,
                "source_ip": source_ip,
            }
        )

    def _send_public_confirmation(self):
        """Email the customer their confirmation + public status page link."""
        self.ensure_one()
        template = self.env.ref(
            "beauty_appointment.mail_template_salon_confirmation",
            raise_if_not_found=False,
        )
        if template and self.partner_id.email:
            template.sudo().send_mail(self.id, force_send=True)

    # --- overlap checks ----------------------------------------------------------
    @api.constrains("start", "stop", "stop_with_buffer", "employee_id", "state", "active")
    def _check_no_overlap(self):
        """Application-level double-booking guard.

        Backs up the `_no_overlap` PostgreSQL constraint with a friendlier
        message, and is the only guard if `btree_gist` could not be installed.
        """
        for appt in self:
            if (
                not appt.active
                or appt.state in DEAD_STATES
                or not appt.start
                or not appt.stop
            ):
                continue
            if appt._overlapping_appointments():
                raise ValidationError(
                    self.env._(
                        "%(employee)s is already booked during this time slot.",
                        employee=appt.employee_id.name,
                    )
                )

    def _overlapping_appointments(self):
        """Return other live appointments of the same employee overlapping self."""
        self.ensure_one()
        return self.search(
            [
                ("id", "!=", self._origin.id or 0),
                ("employee_id", "=", self.employee_id.id),
                ("state", "not in", DEAD_STATES),
                ("active", "=", True),
                ("start", "<", self.stop_with_buffer or self.stop),
                ("stop_with_buffer", ">", self.start),
            ]
        )

    @api.model
    def _busy_intervals(self, employee, start_dt, end_dt):
        """Intervals where ``employee`` is already booked (buffer included).

        :param start_dt/end_dt: timezone-aware datetimes bounding the search.
        :return: an ``Intervals`` of UTC-aware ``(from, to, appointments)`` triples.
        """
        lo = start_dt.astimezone(pytz.utc).replace(tzinfo=None)
        hi = end_dt.astimezone(pytz.utc).replace(tzinfo=None)
        appointments = self.search(
            [
                ("employee_id", "=", employee.id),
                ("state", "not in", DEAD_STATES),
                ("active", "=", True),
                ("start", "<", hi),
                ("stop_with_buffer", ">", lo),
            ]
        )
        items = []
        for appt in appointments:
            end = appt.stop_with_buffer or appt.stop
            if appt.start and end:
                items.append(
                    (pytz.utc.localize(appt.start), pytz.utc.localize(end), appt)
                )
        return Intervals(items)

    def _is_slot_free(self):
        """True when self fits inside the staff member's working hours *and* does
        not overlap another live appointment.

        The backend does not enforce this (a receptionist may deliberately book
        outside opening hours); the public booking flow does.
        """
        self.ensure_one()
        if not (self.start and self.stop and self.employee_id):
            return False
        calendar = self.employee_id.resource_calendar_id
        if not calendar:
            return False
        tz = pytz.timezone(self.appointment_type_id.tz or self.env.user.tz or "UTC")
        start_u = pytz.utc.localize(self.start)
        end_u = pytz.utc.localize(self.stop_with_buffer or self.stop)
        resource = self.employee_id.resource_id
        work = calendar._work_intervals_batch(
            start_u, end_u, resources=resource, tz=tz
        )[resource.id]
        within_hours = any(s <= start_u and end_u <= e for s, e, _ in work)
        if not within_hours:
            return False
        return not self._overlapping_appointments()

    @api.onchange("start", "duration", "buffer", "employee_id", "service_id")
    def _onchange_warn_unavailable(self):
        if (
            self.start
            and self.stop
            and self.employee_id
            and not self._is_slot_free()
        ):
            return {
                "warning": {
                    "title": self.env._("Slot may not be available"),
                    "message": self.env._(
                        "%(employee)s is outside working hours or already booked "
                        "at this time. You can still save to override.",
                        employee=self.employee_id.name,
                    ),
                }
            }

    # --- calendar sync (Phase 3) --------------------------------------------------
    # One-way sync: salon.appointment -> calendar.event. The appointment is
    # always the source of truth; the event is a mirror for the staff's
    # calendar, reminders and invites. We deliberately do not sync the other
    # direction (e.g. dragging the event) - that would need loop-prevention
    # and a decision about which side wins, for little benefit here.
    def _get_calendar_alarm_ids(self):
        alarms = self.env["calendar.alarm"]
        for xmlid in (
            "beauty_appointment.calendar_alarm_salon_email_24h",
            "beauty_appointment.calendar_alarm_salon_notif_2h",
        ):
            alarm = self.env.ref(xmlid, raise_if_not_found=False)
            if alarm:
                alarms |= alarm
        return alarms

    def _get_calendar_values(self):
        self.ensure_one()
        partners = self.partner_id
        staff_partner = self.employee_id.work_contact_id
        if staff_partner:
            partners |= staff_partner
        description = self.env._("Salon appointment %(ref)s", ref=self.name)
        if self.note:
            description = f"{description}\n{self.note}"
        return {
            "name": self.env._(
                "%(service)s with %(employee)s",
                service=self.service_id.name,
                employee=self.employee_id.name,
            ),
            "start": self.start,
            "stop": self.stop_with_buffer or self.stop,
            "allday": False,
            "partner_ids": [(6, 0, partners.ids)],
            "location": self.company_id.partner_id.contact_address or "",
            "description": description,
            "alarm_ids": [(6, 0, self._get_calendar_alarm_ids().ids)],
            "active": True,
        }

    def _sync_calendar_event(self):
        Event = self.env["calendar.event"].sudo()
        for appt in self:
            if appt.state in ("confirmed", "done"):
                vals = appt._get_calendar_values()
                if appt.calendar_event_id:
                    appt.calendar_event_id.write(vals)
                else:
                    appt.calendar_event_id = Event.create(vals)
            elif appt.calendar_event_id:
                # draft / cancelled / no_show: free up the staff's calendar
                appt.calendar_event_id.write({"active": False})

    # --- CRM + Sales + Invoicing (Phase 4) ----------------------------------------
    # Every appointment gets a CRM lead (one per *customer*, reused across their
    # visits - not one per appointment) and its own sale order (one per
    # *appointment* - keeping "book one service" simple to start with). The
    # appointment stays the source of truth: its state drives the order
    # forward, never the other way around.
    def _find_or_create_lead(self):
        self.ensure_one()
        Lead = self.env["crm.lead"].sudo()
        lead = Lead.search(
            [("partner_id", "=", self.partner_id.id)], limit=1, order="create_date desc"
        )
        if lead:
            lead.message_post(
                body=self.env._(
                    "New salon appointment %(ref)s: %(service)s with %(employee)s on %(when)s.",
                    ref=self.name,
                    service=self.service_id.name,
                    employee=self.employee_id.name,
                    when=self.start_display,
                )
            )
            return lead
        vals = {
            "name": self.env._("%(partner)s - Salon", partner=self.partner_id.name),
            "partner_id": self.partner_id.id,
            "company_id": self.company_id.id,
            "user_id": False,  # left unassigned for a salesperson to triage
        }
        if self.appointment_type_id.crm_team_id:
            vals["team_id"] = self.appointment_type_id.crm_team_id.id
        return Lead.create(vals)

    def _find_or_create_sale_order(self):
        self.ensure_one()
        return (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.partner_id.id,
                    "company_id": self.company_id.id,
                    "origin": self.name,
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.service_id.product_variant_id.id,
                                "product_uom_qty": 1.0,
                            },
                        )
                    ],
                }
            )
        )

    def _sync_sales_crm(self):
        """Keep the appointment's lead and sale order attached and in step
        with its state. Never lets a downstream accounting/CRM hiccup (e.g. a
        locked order) block the appointment's own workflow - it logs instead
        of raising, since the booking itself already succeeded.
        """
        for appt in self:
            if not appt.lead_id:
                appt.lead_id = appt._find_or_create_lead()
            if not appt.sale_order_id:
                appt.sale_order_id = appt._find_or_create_sale_order()

            order = appt.sale_order_id.sudo()
            try:
                if appt.state in ("confirmed", "done") and order.state == "draft":
                    order.action_confirm()
                if appt.state == "done":
                    invoices = order._create_invoices()
                    invoices.action_post()
                elif appt.state in ("cancelled", "no_show") and order.state not in ("cancel",):
                    order.action_cancel()
            except Exception:
                _logger.exception(
                    "Salon appointment %s: could not sync sale order %s to state %s",
                    appt.name, order.name, appt.state,
                )

    # --- smart button openers -----------------------------------------------------
    def action_view_calendar_event(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Calendar Event"),
            "res_model": "calendar.event",
            "view_mode": "form",
            "res_id": self.calendar_event_id.id,
        }

    def action_view_lead(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Lead"),
            "res_model": "crm.lead",
            "view_mode": "form",
            "res_id": self.lead_id.id,
        }

    def action_view_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Sales Order"),
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    # --- CRUD ------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "salon.appointment"
                ) or self.env._("New")
        records = super().create(vals_list)
        records._sync_sales_crm()
        records._sync_calendar_event()
        return records

    _CALENDAR_SYNC_FIELDS = {
        "state", "start", "duration", "buffer", "employee_id", "service_id",
        "partner_id", "note",
    }
    _SALES_SYNC_FIELDS = {"state"}

    def write(self, vals):
        res = super().write(vals)
        if self._SALES_SYNC_FIELDS & set(vals):
            self._sync_sales_crm()
        if self._CALENDAR_SYNC_FIELDS & set(vals):
            self._sync_calendar_event()
        return res

    # --- state transitions --------------------------------------------------------
    def _transition(self, state):
        self.write({"state": state})
        # Flush immediately: a cancel that frees a slot (or a confirm that takes
        # one) must be visible to the `_no_overlap` DB constraint before any
        # other appointment is written in the same transaction - e.g. a
        # "reschedule" that cancels the old slot and books a new one at once.
        self.flush_recordset(["state"])

    def action_confirm(self):
        self._transition("confirmed")

    def action_done(self):
        self._transition("done")

    def action_no_show(self):
        self._transition("no_show")

    def action_cancel(self):
        self._transition("cancelled")

    def action_draft(self):
        self._transition("draft")
