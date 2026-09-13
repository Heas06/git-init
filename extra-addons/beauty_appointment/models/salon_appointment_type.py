import math
import re
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models


class SalonAppointmentType(models.Model):
    """A shareable booking configuration.

    One record = one public booking link (``/salon/<slug>``) with its own set of
    offered services, bookable staff, timezone and scheduling rules. It also owns
    the availability engine used by the public funnel (Phase 5).
    """

    _name = "salon.appointment.type"
    _description = "Salon Booking Page"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    slug = fields.Char(
        string="URL Slug",
        copy=False,
        help="Identifier used in the public booking URL: /salon/<slug>.",
    )
    tz = fields.Selection(
        selection=lambda self: [(x, x) for x in sorted(pytz.all_timezones)],
        string="Timezone",
        required=True,
        default=lambda self: self.env.user.tz or "UTC",
        help="All slots are computed and displayed in this timezone.",
    )
    service_ids = fields.Many2many(
        "product.template",
        string="Services",
        domain=[("salon_service", "=", True)],
    )
    employee_ids = fields.Many2many(
        "hr.employee",
        string="Staff",
        domain=[("is_salon_staff", "=", True)],
    )
    min_hours_before = fields.Float(
        string="Minimum Notice (hours)",
        default=2.0,
        help="A customer cannot book a slot starting sooner than this.",
    )
    max_days_ahead = fields.Integer(
        string="Booking Window (days)",
        default=30,
        help="How far into the future customers may book.",
    )
    slot_granularity = fields.Float(
        string="Slot Interval (hours)",
        default=0.5,
        help="Spacing between two proposed start times (e.g. 0.5 = every 30 min).",
    )
    appointment_count = fields.Integer(compute="_compute_appointment_count")
    public_url = fields.Char(string="Public Booking Link", compute="_compute_public_url")
    crm_team_id = fields.Many2one(
        "crm.team",
        string="Sales Team",
        help="Leads created from bookings on this page are attached to this team. "
        "Leave empty to use the default team resolution.",
    )

    _slug_unique = models.UniqueIndex(
        "(slug) WHERE slug IS NOT NULL",
        "The booking page slug must be unique.",
    )

    def _compute_appointment_count(self):
        groups = self.env["salon.appointment"]._read_group(
            [("appointment_type_id", "in", self.ids)],
            groupby=["appointment_type_id"],
            aggregates=["__count"],
        )
        counts = {atype.id: count for atype, count in groups}
        for record in self:
            record.appointment_count = counts.get(record.id, 0)

    def _compute_public_url(self):
        for record in self:
            record.public_url = (
                f"{record.get_base_url()}/salon/{record.slug}" if record.slug else False
            )

    @staticmethod
    def _slugify(value):
        return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("slug"):
                vals["slug"] = self._slugify(vals.get("name")) or False
        return super().create(vals_list)

    def action_view_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Appointments"),
            "res_model": "salon.appointment",
            "view_mode": "calendar,list,form",
            "domain": [("appointment_type_id", "=", self.id)],
            "context": {"default_appointment_type_id": self.id},
        }

    # ------------------------------------------------------------------
    # Availability engine
    # ------------------------------------------------------------------
    def _timezone(self):
        self.ensure_one()
        return pytz.timezone(self.tz or "UTC")

    def _booking_window(self):
        """Return ``(earliest, latest)`` timezone-aware datetimes bounding what a
        customer may book right now: no sooner than the minimum notice, no later
        than the booking window."""
        self.ensure_one()
        tz = self._timezone()
        now = datetime.now(tz)
        earliest = now + timedelta(hours=self.min_hours_before or 0.0)
        latest = now + timedelta(days=self.max_days_ahead or 30)
        return earliest, latest

    def _bookable_employees(self, service, employee=None):
        """Staff of this page who can perform ``service`` (and have a schedule)."""
        self.ensure_one()
        employees = self.employee_ids.filtered("resource_calendar_id")
        if service.salon_employee_ids:
            employees &= service.salon_employee_ids
        if employee:
            employees &= employee
        return employees

    def _align_up(self, dt_utc, granularity, tz):
        """Round a UTC-aware datetime *up* to the next slot boundary, where
        boundaries are multiples of ``granularity`` measured from local midnight
        (so a 30-min grid lands on :00 / :30 local time)."""
        local = dt_utc.astimezone(tz)
        midnight_local = tz.localize(
            datetime.combine(local.date(), datetime.min.time())
        )
        midnight_utc = midnight_local.astimezone(pytz.utc)
        step = granularity.total_seconds()
        elapsed = (dt_utc - midnight_utc).total_seconds()
        k = math.ceil(elapsed / step - 1e-6)
        return midnight_utc + timedelta(seconds=k * step)

    def get_available_slots(self, service, employee=None, day_from=None, day_to=None):
        """Return the list of free slots for ``service`` on this booking page.

        :param service: a ``product.template`` (single record).
        :param employee: optional ``hr.employee`` to restrict the search.
        :param day_from/day_to: optional ``date`` objects to narrow the window.
        :return: list of dicts sorted by time, each::

            {
                'start': datetime,          # naive UTC, as stored on salon.appointment
                'start_local': datetime,    # tz-aware, in this page's timezone
                'employee_id': int,
                'employee_name': str,
                'duration': float,          # hours
            }
        """
        self.ensure_one()
        service.ensure_one()
        if service not in self.service_ids:
            return []
        tz = self._timezone()
        duration = service.salon_duration or 1.0
        buffer_h = service.salon_buffer or 0.0
        needed = timedelta(hours=duration + buffer_h)
        granularity = timedelta(hours=self.slot_granularity or 0.5)

        earliest, latest = self._booking_window()
        if day_from:
            bound = tz.localize(datetime.combine(day_from, datetime.min.time()))
            earliest = max(earliest, bound)
        if day_to:
            bound = tz.localize(datetime.combine(day_to, datetime.max.time()))
            latest = min(latest, bound)
        if earliest >= latest:
            return []

        employees = self._bookable_employees(service, employee)
        if not employees:
            return []

        Appointment = self.env["salon.appointment"]
        earliest_utc = earliest.astimezone(pytz.utc)
        slots = []
        for emp in employees:
            resource = emp.resource_id
            calendar = emp.resource_calendar_id
            work = calendar._work_intervals_batch(
                earliest, latest, resources=resource, tz=tz
            )[resource.id]
            busy = Appointment._busy_intervals(emp, earliest, latest)
            free = work - busy
            for start, stop, _meta in free:
                start_utc = start.astimezone(pytz.utc)
                stop_utc = stop.astimezone(pytz.utc)
                cursor = self._align_up(start_utc, granularity, tz)
                while cursor + needed <= stop_utc:
                    if cursor >= earliest_utc:
                        slots.append(
                            {
                                "start": cursor.replace(tzinfo=None),
                                "start_local": cursor.astimezone(tz),
                                "employee_id": emp.id,
                                "employee_name": emp.name,
                                "duration": duration,
                            }
                        )
                    cursor += granularity

        slots.sort(key=lambda s: (s["start"], s["employee_name"]))
        return slots

    def _validate_requested_slot(self, service, employee, start):
        """Re-check, at submit time, that ``start`` is still genuinely free.

        Never trust a slot the client claims was free when it fetched the list
        moments earlier - always recompute. Also resolves "any available staff"
        (``employee`` falsy) to whichever employee's slot actually matches.

        :return: the ``hr.employee`` to book, or an empty recordset if the
            slot is no longer available.
        """
        self.ensure_one()
        if not start:
            return self.env["hr.employee"]
        tz = self._timezone()
        start_local = pytz.utc.localize(start).astimezone(tz)
        slots = self.get_available_slots(
            service, employee=employee, day_from=start_local.date(), day_to=start_local.date()
        )
        for slot in slots:
            if slot["start"] == start and (not employee or slot["employee_id"] == employee.id):
                return self.env["hr.employee"].browse(slot["employee_id"])
        return self.env["hr.employee"]
