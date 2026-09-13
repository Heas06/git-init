from datetime import timedelta

import psycopg2
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

# Simple, dependency-free abuse guard: no more than this many public bookings
# from the same IP per hour. Real rate limiting (per-IP request throttling)
# belongs at the reverse-proxy / Cloudflare layer; this only bounds how many
# *appointments* one visitor can create in our own database.
MAX_BOOKINGS_PER_IP_PER_HOUR = 5


class SalonBookingController(http.Controller):
    @staticmethod
    def _get_client_ip():
        """The visitor's real IP, even behind a reverse proxy that Odoo's own
        `proxy_mode` doesn't recognize (e.g. a Cloudflare Quick Tunnel, which
        sends `X-Forwarded-For` but not the `X-Forwarded-Host` that Odoo's
        ProxyFix requires before it will trust forwarded headers at all -
        see odoo/http.py). This only feeds our own soft rate limit, never an
        access-control decision, so trusting a client-suppliable header here
        is an acceptable trade-off.
        """
        forwarded = request.httprequest.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.httprequest.remote_addr

    def _get_type(self, slug):
        return (
            request.env["salon.appointment.type"]
            .sudo()
            .search([("slug", "=", slug), ("active", "=", True)], limit=1)
        )

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    @http.route("/salon/<string:slug>", type="http", auth="public", website=True, sitemap=False)
    def salon_booking_page(self, slug, **kwargs):
        atype = self._get_type(slug)
        if not atype:
            raise NotFound()

        earliest, latest = atype._booking_window()
        return request.render(
            "beauty_appointment.salon_booking_page",
            {
                "atype": atype,
                "services": atype.service_ids.filtered("active"),
                "employees": atype.employee_ids,
                "min_date": earliest.date().isoformat(),
                "max_date": latest.date().isoformat(),
            },
        )

    @http.route(
        "/salon/booking/<string:token>", type="http", auth="public", website=True, sitemap=False
    )
    def salon_booking_status(self, token, **kwargs):
        appointment = (
            request.env["salon.appointment"].sudo().search([("access_token", "=", token)], limit=1)
        )
        if not appointment:
            raise NotFound()
        return request.render(
            "beauty_appointment.salon_booking_status", {"appointment": appointment}
        )

    # ------------------------------------------------------------------
    # JSON endpoints
    # ------------------------------------------------------------------
    @http.route("/salon/<string:slug>/slots", type="jsonrpc", auth="public", website=True)
    def salon_booking_slots(self, slug, service_id=None, employee_id=None, date=None, **kwargs):
        atype = self._get_type(slug)
        if not atype:
            return {"error": "not_found"}

        service = self._browse_int(request.env["product.template"], service_id)
        if not service or service not in atype.service_ids:
            return {"error": "invalid_service"}

        employee = request.env["hr.employee"]
        if employee_id:
            employee = self._browse_int(request.env["hr.employee"], employee_id)
            if not employee or employee not in atype.employee_ids:
                return {"error": "invalid_employee"}

        day = fields.Date.from_string(date) if date else fields.Date.context_today(request.env.user)
        slots = atype.sudo().get_available_slots(
            service, employee=employee or None, day_from=day, day_to=day
        )
        return {
            "slots": [
                {
                    "start": fields.Datetime.to_string(slot["start"]),
                    "label": slot["start_local"].strftime("%H:%M"),
                    "employee_id": slot["employee_id"],
                    "employee_name": slot["employee_name"],
                }
                for slot in slots
            ]
        }

    @http.route("/salon/<string:slug>/submit", type="jsonrpc", auth="public", website=True)
    def salon_booking_submit(self, slug, **post):
        atype = self._get_type(slug)
        if not atype:
            return {"error": "not_found"}

        # Honeypot: a real visitor never sees or fills this field; a bot that
        # fills every input will. Pretend success so it doesn't learn to adapt.
        if (post.get("hp") or "").strip():
            return {"ok": True}

        name = (post.get("name") or "").strip()
        email = (post.get("email") or "").strip()
        phone = (post.get("phone") or "").strip()
        if not name or len(name) < 2:
            return {"error": "invalid_name"}
        if not email and not phone:
            return {"error": "missing_contact"}

        service = self._browse_int(request.env["product.template"], post.get("service_id"))
        if not service or service not in atype.service_ids:
            return {"error": "invalid_service"}

        employee = request.env["hr.employee"]
        if post.get("employee_id"):
            employee = self._browse_int(request.env["hr.employee"], post.get("employee_id"))
            if not employee or employee not in atype.employee_ids:
                return {"error": "invalid_employee"}

        start = fields.Datetime.from_string(post.get("start") or "")
        if not start:
            return {"error": "invalid_input"}

        ip = self._get_client_ip()
        Appointment = request.env["salon.appointment"].sudo()
        since = fields.Datetime.to_string(fields.Datetime.now() - timedelta(hours=1))
        recent = Appointment.search_count(
            [("source_ip", "=", ip), ("create_date", ">=", since)]
        )
        if recent >= MAX_BOOKINGS_PER_IP_PER_HOUR:
            return {"error": "rate_limited"}

        # Never trust the slot the browser claims is free - recompute now.
        resolved_employee = atype.sudo()._validate_requested_slot(service, employee, start)
        if not resolved_employee:
            return {"error": "slot_unavailable"}

        partner = Appointment._find_or_create_partner(name, email, phone)

        try:
            with request.env.cr.savepoint():
                appointment = Appointment._public_book(
                    atype.sudo(), service, resolved_employee, start, partner, source_ip=ip
                )
        except (ValidationError, psycopg2.Error):
            # Someone else took the slot between our check and our write.
            return {"error": "slot_unavailable"}

        appointment._send_public_confirmation()
        return {
            "ok": True,
            "redirect": f"/salon/booking/{appointment.access_token}",
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _browse_int(model, value):
        try:
            record = model.sudo().browse(int(value)).exists()
        except (TypeError, ValueError):
            return None
        return record or None
