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
        not_found: "Esta página de citas ya no está disponible.",
        invalid_service: "Por favor elige un servicio.",
        invalid_employee: "Por favor elige un profesional.",
        invalid_name: "Por favor ingresa tu nombre.",
        missing_contact: "Por favor ingresa un teléfono o correo electrónico.",
        invalid_input: "Por favor elige un horario.",
        slot_unavailable:
            "Lo sentimos, ese horario acaba de ser reservado por alguien más. Por favor elige otro.",
        rate_limited: "Demasiados intentos de reserva. Por favor intenta más tarde.",
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

        var stepService = document.getElementById("o_salon_step_service");
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

        // --- Accordion: once a step's choice is made, collapse it to a
        // single summary line so the next step is visible without scrolling
        // past a long list of services (important on a phone). The header
        // stays clickable so a visitor can reopen a step to change an
        // earlier answer. -------------------------------------------------
        function collapseStep(stepEl, summaryText) {
            var summary = stepEl.querySelector(".o_salon_step_summary");
            if (summary) {
                summary.textContent = summaryText || "";
            }
            stepEl.classList.add("o_salon_collapsed");
        }

        function resetStep(stepEl) {
            var summary = stepEl.querySelector(".o_salon_step_summary");
            if (summary) {
                summary.textContent = "";
            }
            stepEl.classList.remove("o_salon_collapsed");
        }

        // Collapsing a long step (e.g. 14 service cards) shrinks the page a
        // lot in one frame. Left alone, the browser keeps the same scrollY,
        // which can now be past the end of the (much shorter) document, so
        // it clamps to the bottom and the visitor ends up staring at the
        // footer. Scroll back to the very top instead, so the salon header
        // and the whole step trail are visible - on a phone, landing mid-page
        // on just the next step (with no header/title in view) reads as if
        // the page had lost its content.
        function scrollToStep() {
            requestAnimationFrame(function () {
                window.scrollTo({ top: 0, behavior: "smooth" });
            });
        }

        [stepService, stepStaff, stepDate].forEach(function (stepEl) {
            stepEl
                .querySelector(".o_salon_step_header")
                .addEventListener("click", function () {
                    stepEl.classList.toggle("o_salon_collapsed");
                });
        });

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

                var duration = card.dataset.serviceDuration;
                collapseStep(
                    stepService,
                    card.dataset.serviceName + (duration ? " · " + duration + " h" : "")
                );
                resetStep(stepStaff);
                resetStep(stepDate);
                stepStaff.classList.remove("d-none");
                stepDate.classList.add("d-none");
                stepContact.classList.add("d-none");
                clearError();
                scrollToStep(stepStaff);
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

                collapseStep(
                    stepStaff,
                    card.dataset.employeeName || "Cualquiera disponible"
                );
                resetStep(stepDate);
                stepDate.classList.remove("d-none");
                stepContact.classList.add("d-none");
                clearError();
                scrollToStep(stepDate);
                loadSlots();
            });
        });

        // --- Step 3: date -> slots --------------------------------------------
        dateInput.addEventListener("change", function () {
            state.start = null;
            stepContact.classList.add("d-none");
            loadSlots();
        });

        function formatDateLabel(isoDate) {
            if (!isoDate) {
                return "";
            }
            // Parse as local date (new Date("YYYY-MM-DD") would be UTC midnight
            // and could shift a day depending on the visitor's timezone).
            var parts = isoDate.split("-");
            var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
            return d.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
        }

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
                            collapseStep(stepDate, formatDateLabel(dateInput.value) + " · " + slot.label);
                            stepContact.classList.remove("d-none");
                            clearError();
                            scrollToStep(stepContact);
                        });
                        slotsBox.appendChild(btn);
                    });
                })
                .catch(function () {
                    showError("No se pudieron cargar los horarios disponibles. Intenta de nuevo.");
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
                        showError(ERROR_MESSAGES[result.error] || "Algo salió mal.");
                        if (result.error === "slot_unavailable") {
                            loadSlots();
                        }
                    }
                    submitBtn.disabled = false;
                })
                .catch(function () {
                    showError("Algo salió mal. Intenta de nuevo.");
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
