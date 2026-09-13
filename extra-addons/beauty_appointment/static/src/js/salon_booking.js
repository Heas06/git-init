(function () {
    "use strict";

    /** Minimal JSON-RPC 2.0 client for our `type="jsonrpc"` routes. Plain
     * fetch() on purpose: this page is a standalone public funnel, not part
     * of the backend, so it doesn't need the OWL/services stack. */
    function jsonRpc(url, params) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: params || {},
                id: Math.floor(Math.random() * 1e9),
            }),
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                if (data.error) {
                    throw new Error(
                        (data.error.data && data.error.data.message) || "RPC error"
                    );
                }
                return data.result;
            });
    }

    var ERROR_MESSAGES = {
        not_found: "This booking page is no longer available.",
        invalid_service: "Please choose a service.",
        invalid_employee: "Please choose a staff member.",
        invalid_name: "Please enter your name.",
        missing_contact: "Please enter a phone number or email.",
        invalid_input: "Please pick a time slot.",
        slot_unavailable:
            "Sorry, that time was just booked by someone else. Please pick another slot.",
        rate_limited: "Too many booking attempts. Please try again later.",
    };

    // NOTE: this file is loaded through Odoo's `web.assets_frontend_lazy`
    // bundle, which is only injected into the page *after* the `load` event
    // fires (see web/static/src/legacy/js/public/lazyloader.js) - by the time
    // this code runs, `DOMContentLoaded` has already happened, so a listener
    // for it would never fire. The DOM is already fully ready here.
    function init() {
        var root = document.querySelector(".o_salon_booking");
        if (!root) {
            return;
        }

        var slug = root.dataset.slug;
        var minDate = root.dataset.minDate;
        var maxDate = root.dataset.maxDate;

        var state = { serviceId: null, employeeId: "", start: null };

        var stepStaff = document.getElementById("o_salon_step_staff");
        var stepDate = document.getElementById("o_salon_step_date");
        var stepContact = document.getElementById("o_salon_step_contact");
        var dateInput = document.getElementById("o_salon_date");
        var slotsBox = document.getElementById("o_salon_slots");
        var slotsEmpty = document.getElementById("o_salon_slots_empty");
        var form = document.getElementById("o_salon_form");
        var errorBox = document.getElementById("o_salon_error");
        var submitBtn = document.getElementById("o_salon_submit");

        function showError(message) {
            errorBox.textContent = message;
            errorBox.classList.remove("d-none");
        }

        function clearError() {
            errorBox.classList.add("d-none");
            errorBox.textContent = "";
        }

        // --- Step 1: service ------------------------------------------------
        document.querySelectorAll(".o_salon_service_card").forEach(function (card) {
            card.addEventListener("click", function () {
                document
                    .querySelectorAll(".o_salon_service_card")
                    .forEach(function (c) { c.classList.remove("active"); });
                card.classList.add("active");

                state.serviceId = card.dataset.serviceId;
                state.employeeId = "";
                state.start = null;

                document.querySelectorAll(".o_salon_staff_card").forEach(function (staffCard) {
                    var ids = staffCard.dataset.serviceIds;
                    var ok = !ids || ids.split(",").indexOf(state.serviceId) !== -1;
                    staffCard.classList.toggle("o_salon_disabled", !ok);
                    staffCard.classList.remove("active");
                });

                stepStaff.classList.remove("d-none");
                stepDate.classList.add("d-none");
                stepContact.classList.add("d-none");
                clearError();
            });
        });

        // --- Step 2: staff ---------------------------------------------------
        document.querySelectorAll(".o_salon_staff_card").forEach(function (card) {
            card.addEventListener("click", function () {
                if (card.classList.contains("o_salon_disabled")) {
                    return;
                }
                document
                    .querySelectorAll(".o_salon_staff_card")
                    .forEach(function (c) { c.classList.remove("active"); });
                card.classList.add("active");

                state.employeeId = card.dataset.employeeId || "";
                state.start = null;

                if (!dateInput.value) {
                    dateInput.value = minDate;
                }
                dateInput.min = minDate;
                dateInput.max = maxDate;

                stepDate.classList.remove("d-none");
                stepContact.classList.add("d-none");
                clearError();
                loadSlots();
            });
        });

        // --- Step 3: date -> slots --------------------------------------------
        dateInput.addEventListener("change", function () {
            state.start = null;
            stepContact.classList.add("d-none");
            loadSlots();
        });

        function loadSlots() {
            slotsBox.innerHTML = "";
            slotsEmpty.classList.add("d-none");
            if (!state.serviceId || !dateInput.value) {
                return;
            }
            jsonRpc("/salon/" + slug + "/slots", {
                service_id: state.serviceId,
                employee_id: state.employeeId || undefined,
                date: dateInput.value,
            })
                .then(function (result) {
                    var slots = (result && result.slots) || [];
                    if (!slots.length) {
                        slotsEmpty.classList.remove("d-none");
                        return;
                    }
                    slots.forEach(function (slot) {
                        var btn = document.createElement("button");
                        btn.type = "button";
                        btn.className = "btn btn-outline-primary o_salon_slot_btn";
                        btn.textContent = state.employeeId
                            ? slot.label
                            : slot.label + " · " + slot.employee_name;
                        btn.addEventListener("click", function () {
                            document
                                .querySelectorAll(".o_salon_slot_btn")
                                .forEach(function (b) { b.classList.remove("active"); });
                            btn.classList.add("active");
                            state.start = slot.start;
                            stepContact.classList.remove("d-none");
                            clearError();
                        });
                        slotsBox.appendChild(btn);
                    });
                })
                .catch(function () {
                    showError("Could not load available times. Please try again.");
                });
        }

        // --- Step 4: submit ----------------------------------------------------
        form.addEventListener("submit", function (ev) {
            ev.preventDefault();
            clearError();
            if (!state.start) {
                showError(ERROR_MESSAGES.invalid_input);
                return;
            }
            var data = new FormData(form);
            submitBtn.disabled = true;
            jsonRpc("/salon/" + slug + "/submit", {
                service_id: state.serviceId,
                employee_id: state.employeeId || undefined,
                start: state.start,
                name: data.get("name"),
                phone: data.get("phone"),
                email: data.get("email"),
                hp: data.get("hp"),
            })
                .then(function (result) {
                    if (result && result.redirect) {
                        window.location.href = result.redirect;
                        return;
                    }
                    if (result && result.error) {
                        showError(ERROR_MESSAGES[result.error] || "Something went wrong.");
                        if (result.error === "slot_unavailable") {
                            loadSlots();
                        }
                    }
                    submitBtn.disabled = false;
                })
                .catch(function () {
                    showError("Something went wrong. Please try again.");
                    submitBtn.disabled = false;
                });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
