// Shared admin helper that renders the per-challenge languages repeater on
// the create.html and update.html forms. Both pages load this file via a
// <script> tag injected by their respective entry-point JS so the same DOM
// markup works in both contexts.

(function () {
    if (typeof window.setupCodesubflagLanguagesEditor === "function") return;

    const CONTAINER_ID = "codesubflag-languages";
    const HIDDEN_ID    = "codesubflag-languages-json";
    const ADD_BTN_ID   = "codesubflag-add-language";

    function el(html) {
        const tpl = document.createElement("template");
        tpl.innerHTML = html.trim();
        return tpl.content.firstChild;
    }

    function loadRuntimes() {
        return CTFd.fetch("/api/v1/codesubflags/runtimes", { method: "GET" })
            .then(r => r.json())
            .then(j => (j && j.success && Array.isArray(j.data)) ? j.data : [])
            .catch(() => []);
    }

    function buildSelect(runtimes, current) {
        const select = document.createElement("select");
        select.className = "form-control codesubflag-lang-select";

        // Always include the currently-saved option even if piston no longer
        // reports it, so an admin re-saving an existing challenge doesn't
        // silently overwrite their selection just because the runtime was
        // uninstalled or piston was offline at the time of editing.
        const seen = new Set();
        runtimes.forEach(rt => {
            const key = rt.language + "|" + rt.version;
            seen.add(key);
            const opt = document.createElement("option");
            opt.value = key;
            opt.textContent = rt.label || (rt.language + " - " + rt.version);
            select.appendChild(opt);
        });

        if (current && current.language && current.version) {
            const key = current.language + "|" + current.version;
            if (!seen.has(key)) {
                const opt = document.createElement("option");
                opt.value = key;
                opt.textContent = current.language + " - " + current.version + " (not installed)";
                select.appendChild(opt);
            }
            select.value = key;
        }
        return select;
    }

    function renderRow(container, runtimes, prefill) {
        const row = el(`
            <div class="codesubflag-lang-row mt-2" style="border:1px solid #dee2e6;border-radius:4px;padding:8px;">
                <div class="form-group mb-2">
                    <small class="form-text text-muted mb-1">Language & version</small>
                    <span class="codesubflag-lang-slot"></span>
                </div>
                <div class="form-group mb-2">
                    <small class="form-text text-muted mb-1">Template (run_file)</small>
                    <input type="text" class="form-control codesubflag-runfile" placeholder="e.g. main.py">
                </div>
                <div class="form-group mb-2">
                    <small class="form-text text-muted mb-1">Data file (optional)</small>
                    <input type="text" class="form-control codesubflag-datafile" placeholder="e.g. data.csv">
                </div>
                <div class="text-right">
                    <button type="button" class="btn btn-sm btn-outline-danger codesubflag-lang-remove">Remove</button>
                </div>
            </div>
        `);

        const select = buildSelect(runtimes, prefill || {});
        row.querySelector(".codesubflag-lang-slot").appendChild(select);
        row.querySelector(".codesubflag-runfile").value = (prefill && prefill.run_file) || "";
        row.querySelector(".codesubflag-datafile").value = (prefill && prefill.data_file) || "";
        row.querySelector(".codesubflag-lang-remove").addEventListener("click", function () {
            row.parentNode.removeChild(row);
        });
        container.appendChild(row);
    }

    function serialize(container) {
        const rows = container.querySelectorAll(".codesubflag-lang-row");
        const out = [];
        rows.forEach((row, idx) => {
            const select = row.querySelector(".codesubflag-lang-select");
            if (!select || !select.value) return;
            const parts = select.value.split("|");
            if (parts.length !== 2) return;
            const language = parts[0].trim();
            const version  = parts[1].trim();
            const run_file = (row.querySelector(".codesubflag-runfile").value || "").trim();
            const data_file = (row.querySelector(".codesubflag-datafile").value || "").trim();
            if (!language || !version || !run_file) return;
            out.push({
                language: language,
                version: version,
                run_file: run_file,
                data_file: data_file,
                sort_order: idx
            });
        });
        return out;
    }

    function attachFormHook(container, hidden) {
        // Walk up to the nearest <form> and serialise the rows just before
        // submit. Using a capture-phase listener ensures we run before any
        // CTFd form-handler that reads form.serialize() / FormData.
        let node = container;
        while (node && node.tagName !== "FORM") node = node.parentNode;
        if (!node) return;

        node.addEventListener("submit", function (event) {
            const rows = serialize(container);
            if (!rows.length) {
                event.preventDefault();
                event.stopPropagation();
                alert("Add at least one language before saving.");
                return;
            }
            hidden.value = JSON.stringify(rows);
        }, true);
    }

    window.setupCodesubflagLanguagesEditor = function (opts) {
        opts = opts || {};
        const container = document.getElementById(CONTAINER_ID);
        const hidden    = document.getElementById(HIDDEN_ID);
        const addBtn    = document.getElementById(ADD_BTN_ID);
        if (!container || !hidden || !addBtn) return;

        loadRuntimes().then(runtimes => {
            const initial = opts.prefill || [];
            initial.forEach(p => renderRow(container, runtimes, p));
            if (!initial.length) {
                renderRow(container, runtimes, {});
            }
            addBtn.addEventListener("click", () => renderRow(container, runtimes, {}));
            attachFormHook(container, hidden);
        });
    };
})();
