{
    "name": "citas beauty",
    "summary": "Manage appointments for a beauty salom",
    "description": """
Long description of module's purpose
    """,
    "author": "Omar",
    "website": "https://www.yourcompany.com",
    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    "category": "Services/Appointments",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "application": True,
    "pre_init_hook": "_pre_init_salon",
    # any module necessary for this one to work correctly
    "depends": [
        "sale_management",
        "crm",
        "account",
        "calendar",
        "website",
        "portal",
        "resource",
        "hr",
        "mail",
        "sms",
    ],
    # always loaded
    "data": [
        "security/salon_security.xml",
        "security/ir.model.access.csv",
        "data/salon_data.xml",
        "data/salon_mail_templates.xml",
        "data/salon_calendar_alarms.xml",
        "views/res_partner_views.xml",
        "views/salon_appointment_views.xml",
        "views/salon_appointment_type_views.xml",
        "views/product_template_views.xml",
        "views/hr_employee_views.xml",
        "views/calendar_event_views.xml",
        "views/crm_lead_views.xml",
        "views/sale_order_views.xml",
        "views/menus.xml",
        "views/templates.xml",
    ],
    # only loaded in demonstration mode
    "demo": [
        "demo/salon_demo.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "beauty_appointment/static/src/css/salon_booking.css",
        ],
        # `assets_frontend` JS is lazy-loaded after `window.load` and only
        # replays clicks made during that window for <a>/<button>/.btn
        # elements (see web/static/src/legacy/js/public/lazyloader.js). Our
        # booking cards are plain <div role="button">, so a click made in
        # that window would be silently lost. `assets_frontend_minimal` is
        # deferred (not lazy) - it runs right after the DOM is ready, with
        # no such race - which is what a one-page interactive funnel needs.
        "web.assets_frontend_minimal": [
            "beauty_appointment/static/src/js/salon_booking.js",
        ],
    },
}
